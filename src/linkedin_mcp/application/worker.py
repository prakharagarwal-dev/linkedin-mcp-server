"""Single-consumer in-process queue for LinkedIn capability execution."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol

from linkedin_mcp.application.client_context import (
    bind_client_execution,
    current_client_id,
)
from linkedin_mcp.application.pagination import PaginationLease, PaginationManager
from linkedin_mcp.application.scheduler import FairClientScheduler, SchedulerClosedError
from linkedin_mcp.domain.evidence import canonical_input_fingerprint
from linkedin_mcp.domain.models import (
    ActionExecuteInput,
    ActionExecuteOutput,
    ActionPrepareOutput,
    CapabilityName,
    CompanyGetInput,
    CompanyGetOutput,
    CompanySearchInput,
    CompanySearchOutput,
    ConnectionsListInput,
    ConnectionsListOutput,
    ConnectionsSearchInput,
    ConnectionsSearchOutput,
    ConversationGetInput,
    ConversationGetOutput,
    ConversationSearchInput,
    ConversationSearchOutput,
    InvitationAcceptPrepareInput,
    InvitationIgnorePrepareInput,
    InvitationListInput,
    InvitationListOutput,
    InvitationSendPrepareInput,
    JobDetailInput,
    JobDetailOutput,
    JobSearchInput,
    JobSearchOutput,
    MessagePrepareInput,
    PaginatedInput,
    PeopleGetInput,
    PeopleGetOutput,
    PeopleSearchInput,
    PeopleSearchOutput,
    PostCommentPrepareInput,
    PostCommentsListInput,
    PostCommentsListOutput,
    PostCreatePrepareInput,
    PostGetInput,
    PostGetOutput,
    PostReactionPrepareInput,
    PostSearchInput,
    PostSearchOutput,
)
from linkedin_mcp.errors import (
    BrowserUnavailableError,
    IdempotencyConflictError,
)
from linkedin_mcp.persistence.contracts import CallStart

CapabilityRequest = (
    JobSearchInput
    | JobDetailInput
    | PeopleSearchInput
    | PeopleGetInput
    | CompanySearchInput
    | CompanyGetInput
    | PostSearchInput
    | PostGetInput
    | PostCommentsListInput
    | PostCreatePrepareInput
    | PostCommentPrepareInput
    | PostReactionPrepareInput
    | InvitationListInput
    | ConnectionsListInput
    | ConnectionsSearchInput
    | ConversationSearchInput
    | ConversationGetInput
    | InvitationSendPrepareInput
    | InvitationAcceptPrepareInput
    | InvitationIgnorePrepareInput
    | MessagePrepareInput
    | ActionExecuteInput
)
CapabilityOutput = (
    JobSearchOutput
    | JobDetailOutput
    | PeopleSearchOutput
    | PeopleGetOutput
    | CompanySearchOutput
    | CompanyGetOutput
    | PostSearchOutput
    | PostGetOutput
    | PostCommentsListOutput
    | InvitationListOutput
    | ConnectionsListOutput
    | ConnectionsSearchOutput
    | ConversationSearchOutput
    | ConversationGetOutput
    | ActionPrepareOutput
    | ActionExecuteOutput
)
WorkKey = tuple[str, CapabilityName, str]
ProgressReporter = Callable[[int, int, str], Awaitable[None]]


class CallLookup(Protocol):
    async def __call__(
        self,
        *,
        account_id: str,
        client_id: str,
        request_id: str,
        capability_name: CapabilityName,
    ) -> CallStart | None: ...


class CapabilityRunner(Protocol):
    async def search_jobs(self, request: JobSearchInput) -> JobSearchOutput: ...

    async def get_job(self, request: JobDetailInput) -> JobDetailOutput: ...

    async def search_people(self, request: PeopleSearchInput) -> PeopleSearchOutput: ...

    async def get_person(self, request: PeopleGetInput) -> PeopleGetOutput: ...

    async def search_companies(self, request: CompanySearchInput) -> CompanySearchOutput: ...

    async def get_company(self, request: CompanyGetInput) -> CompanyGetOutput: ...

    async def search_posts(self, request: PostSearchInput) -> PostSearchOutput: ...

    async def get_post(self, request: PostGetInput) -> PostGetOutput: ...

    async def list_post_comments(
        self,
        request: PostCommentsListInput,
    ) -> PostCommentsListOutput: ...

    async def list_invitations(
        self,
        request: InvitationListInput,
        progress: ProgressReporter | None = None,
    ) -> InvitationListOutput: ...

    async def list_connections(self, request: ConnectionsListInput) -> ConnectionsListOutput: ...

    async def search_connections(
        self,
        request: ConnectionsSearchInput,
    ) -> ConnectionsSearchOutput: ...

    async def search_messages(
        self,
        request: ConversationSearchInput,
    ) -> ConversationSearchOutput: ...

    async def get_conversation(
        self,
        request: ConversationGetInput,
    ) -> ConversationGetOutput: ...

    async def prepare_invitation_send(
        self,
        request: InvitationSendPrepareInput,
    ) -> ActionPrepareOutput: ...

    async def prepare_invitation_accept(
        self,
        request: InvitationAcceptPrepareInput,
    ) -> ActionPrepareOutput: ...

    async def prepare_invitation_ignore(
        self,
        request: InvitationIgnorePrepareInput,
    ) -> ActionPrepareOutput: ...

    async def prepare_message(self, request: MessagePrepareInput) -> ActionPrepareOutput: ...

    async def prepare_post_create(
        self,
        request: PostCreatePrepareInput,
    ) -> ActionPrepareOutput: ...

    async def prepare_post_comment(
        self,
        request: PostCommentPrepareInput,
    ) -> ActionPrepareOutput: ...

    async def prepare_post_reaction(
        self,
        request: PostReactionPrepareInput,
    ) -> ActionPrepareOutput: ...

    async def execute_invitation_send(
        self,
        request: ActionExecuteInput,
    ) -> ActionExecuteOutput: ...

    async def execute_invitation_accept(
        self,
        request: ActionExecuteInput,
    ) -> ActionExecuteOutput: ...

    async def execute_invitation_ignore(
        self,
        request: ActionExecuteInput,
    ) -> ActionExecuteOutput: ...

    async def execute_message(self, request: ActionExecuteInput) -> ActionExecuteOutput: ...

    async def execute_post_create(
        self,
        request: ActionExecuteInput,
    ) -> ActionExecuteOutput: ...

    async def execute_post_comment(
        self,
        request: ActionExecuteInput,
    ) -> ActionExecuteOutput: ...

    async def execute_post_reaction(
        self,
        request: ActionExecuteInput,
    ) -> ActionExecuteOutput: ...


@dataclass(slots=True)
class _WorkItem:
    key: WorkKey
    client_id: str
    capability_name: CapabilityName
    request: CapabilityRequest
    future: asyncio.Future[CapabilityOutput]
    progress: ProgressReporter | None = None
    pagination_lease: PaginationLease | None = None
    cancel_requested: bool = False
    enqueue_task: asyncio.Task[None] | None = None


@dataclass(slots=True)
class _InFlight:
    fingerprint: str
    future: asyncio.Future[CapabilityOutput]
    item: _WorkItem
    waiters: int = 1


def _observe_future(future: asyncio.Future[CapabilityOutput]) -> None:
    if future.cancelled():
        return
    future.exception()


_EXECUTE_CAPABILITIES = frozenset(
    {
        CapabilityName.INVITATION_SEND_EXECUTE,
        CapabilityName.INVITATION_ACCEPT_EXECUTE,
        CapabilityName.INVITATION_IGNORE_EXECUTE,
        CapabilityName.MESSAGING_MESSAGE_EXECUTE,
        CapabilityName.POSTS_CREATE_EXECUTE,
        CapabilityName.POST_COMMENT_EXECUTE,
        CapabilityName.POST_REACTION_EXECUTE,
    }
)


def _is_execute_capability(capability_name: CapabilityName) -> bool:
    return capability_name in _EXECUTE_CAPABILITIES


class CapabilityWorker:
    """Serialize every browser-backed capability through one local worker."""

    def __init__(
        self,
        runner: CapabilityRunner,
        *,
        queue_capacity: int,
        pagination: PaginationManager | None = None,
        account_id: str = "personal",
        call_lookup: CallLookup | None = None,
    ) -> None:
        self._runner = runner
        self._scheduler: FairClientScheduler[str, _WorkItem] = FairClientScheduler(
            capacity=queue_capacity
        )
        self._pagination = pagination
        self._account_id = account_id
        self._call_lookup = call_lookup
        self._inflight: dict[WorkKey, _InFlight] = {}
        self._inflight_lock = asyncio.Lock()
        self._enqueue_tasks: set[asyncio.Task[None]] = set()
        self._task: asyncio.Task[None] | None = None
        self._accepting = False
        self._closing = False
        self._active = False
        self._active_item: _WorkItem | None = None
        self._active_task: asyncio.Task[CapabilityOutput] | None = None
        self._idle = asyncio.Event()
        self._idle.set()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def queue_depth(self) -> int:
        return self._scheduler.qsize

    @property
    def queued_clients(self) -> int:
        return self._scheduler.client_count

    @property
    def accepting(self) -> bool:
        return self._accepting

    @property
    def active(self) -> bool:
        return self._active

    @property
    def active_capability(self) -> CapabilityName | None:
        item = self._active_item
        return item.capability_name if item is not None else None

    async def start(self) -> None:
        if self.running:
            return
        self._accepting = True
        self._closing = False
        self._idle.set()
        self._task = asyncio.create_task(
            self._run(),
            name="linkedin-capability-worker",
        )

    async def search_jobs(self, request: JobSearchInput) -> JobSearchOutput:
        output = await self._submit(CapabilityName.JOBS_SEARCH, request)
        if not isinstance(output, JobSearchOutput):
            raise RuntimeError("The capability worker returned an invalid job-search output.")
        return output

    async def get_job(self, request: JobDetailInput) -> JobDetailOutput:
        output = await self._submit(CapabilityName.JOBS_GET, request)
        if not isinstance(output, JobDetailOutput):
            raise RuntimeError("The capability worker returned an invalid job-detail output.")
        return output

    async def search_people(self, request: PeopleSearchInput) -> PeopleSearchOutput:
        output = await self._submit(CapabilityName.PEOPLE_SEARCH, request)
        if not isinstance(output, PeopleSearchOutput):
            raise RuntimeError("The capability worker returned an invalid People-search output.")
        return output

    async def get_person(self, request: PeopleGetInput) -> PeopleGetOutput:
        output = await self._submit(CapabilityName.PEOPLE_GET, request)
        if not isinstance(output, PeopleGetOutput):
            raise RuntimeError("The capability worker returned an invalid member-profile output.")
        return output

    async def search_companies(self, request: CompanySearchInput) -> CompanySearchOutput:
        output = await self._submit(CapabilityName.COMPANIES_SEARCH, request)
        if not isinstance(output, CompanySearchOutput):
            raise RuntimeError("The capability worker returned an invalid Company-search output.")
        return output

    async def get_company(self, request: CompanyGetInput) -> CompanyGetOutput:
        output = await self._submit(CapabilityName.COMPANIES_GET, request)
        if not isinstance(output, CompanyGetOutput):
            raise RuntimeError("The capability worker returned an invalid company-profile output.")
        return output

    async def search_posts(self, request: PostSearchInput) -> PostSearchOutput:
        output = await self._submit(CapabilityName.POSTS_SEARCH, request)
        if not isinstance(output, PostSearchOutput):
            raise RuntimeError("The capability worker returned an invalid post-search output.")
        return output

    async def get_post(self, request: PostGetInput) -> PostGetOutput:
        output = await self._submit(CapabilityName.POSTS_GET, request)
        if not isinstance(output, PostGetOutput):
            raise RuntimeError("The capability worker returned an invalid post-detail output.")
        return output

    async def list_post_comments(
        self,
        request: PostCommentsListInput,
    ) -> PostCommentsListOutput:
        output = await self._submit(CapabilityName.POST_COMMENTS_LIST, request)
        if not isinstance(output, PostCommentsListOutput):
            raise RuntimeError("The capability worker returned an invalid post-discussion output.")
        return output

    async def list_invitations(
        self,
        request: InvitationListInput,
        progress: ProgressReporter | None = None,
    ) -> InvitationListOutput:
        output = await self._submit(
            CapabilityName.INVITATIONS_LIST,
            request,
            progress=progress,
        )
        if not isinstance(output, InvitationListOutput):
            raise RuntimeError("The capability worker returned an invalid invitation output.")
        return output

    async def list_connections(self, request: ConnectionsListInput) -> ConnectionsListOutput:
        output = await self._submit(CapabilityName.CONNECTIONS_LIST, request)
        if not isinstance(output, ConnectionsListOutput):
            raise RuntimeError("The capability worker returned an invalid connections output.")
        return output

    async def search_connections(
        self,
        request: ConnectionsSearchInput,
    ) -> ConnectionsSearchOutput:
        output = await self._submit(CapabilityName.CONNECTIONS_SEARCH, request)
        if not isinstance(output, ConnectionsSearchOutput):
            raise RuntimeError(
                "The capability worker returned an invalid connections-search output."
            )
        return output

    async def search_messages(
        self,
        request: ConversationSearchInput,
    ) -> ConversationSearchOutput:
        output = await self._submit(CapabilityName.MESSAGING_SEARCH, request)
        if not isinstance(output, ConversationSearchOutput):
            raise RuntimeError("The capability worker returned an invalid inbox output.")
        return output

    async def get_conversation(
        self,
        request: ConversationGetInput,
    ) -> ConversationGetOutput:
        output = await self._submit(CapabilityName.MESSAGING_CONVERSATION_GET, request)
        if not isinstance(output, ConversationGetOutput):
            raise RuntimeError("The capability worker returned an invalid conversation output.")
        return output

    async def prepare_invitation_send(
        self,
        request: InvitationSendPrepareInput,
    ) -> ActionPrepareOutput:
        output = await self._submit(CapabilityName.INVITATION_SEND_PREPARE, request)
        if not isinstance(output, ActionPrepareOutput):
            raise RuntimeError("The capability worker returned an invalid invitation draft.")
        return output

    async def prepare_invitation_accept(
        self,
        request: InvitationAcceptPrepareInput,
    ) -> ActionPrepareOutput:
        output = await self._submit(CapabilityName.INVITATION_ACCEPT_PREPARE, request)
        if not isinstance(output, ActionPrepareOutput):
            raise RuntimeError("The capability worker returned an invalid acceptance draft.")
        return output

    async def prepare_invitation_ignore(
        self,
        request: InvitationIgnorePrepareInput,
    ) -> ActionPrepareOutput:
        output = await self._submit(CapabilityName.INVITATION_IGNORE_PREPARE, request)
        if not isinstance(output, ActionPrepareOutput):
            raise RuntimeError("The capability worker returned an invalid ignore draft.")
        return output

    async def prepare_message(self, request: MessagePrepareInput) -> ActionPrepareOutput:
        output = await self._submit(CapabilityName.MESSAGING_MESSAGE_PREPARE, request)
        if not isinstance(output, ActionPrepareOutput):
            raise RuntimeError("The capability worker returned an invalid message draft.")
        return output

    async def prepare_post_create(
        self,
        request: PostCreatePrepareInput,
    ) -> ActionPrepareOutput:
        output = await self._submit(CapabilityName.POSTS_CREATE_PREPARE, request)
        if not isinstance(output, ActionPrepareOutput):
            raise RuntimeError("The capability worker returned an invalid post draft.")
        return output

    async def prepare_post_comment(
        self,
        request: PostCommentPrepareInput,
    ) -> ActionPrepareOutput:
        output = await self._submit(CapabilityName.POST_COMMENT_PREPARE, request)
        if not isinstance(output, ActionPrepareOutput):
            raise RuntimeError("The capability worker returned an invalid comment draft.")
        return output

    async def prepare_post_reaction(
        self,
        request: PostReactionPrepareInput,
    ) -> ActionPrepareOutput:
        output = await self._submit(CapabilityName.POST_REACTION_PREPARE, request)
        if not isinstance(output, ActionPrepareOutput):
            raise RuntimeError("The capability worker returned an invalid reaction draft.")
        return output

    async def execute_invitation_send(
        self,
        request: ActionExecuteInput,
    ) -> ActionExecuteOutput:
        output = await self._submit(CapabilityName.INVITATION_SEND_EXECUTE, request)
        if not isinstance(output, ActionExecuteOutput):
            raise RuntimeError("The capability worker returned an invalid invitation execution.")
        return output

    async def execute_invitation_accept(
        self,
        request: ActionExecuteInput,
    ) -> ActionExecuteOutput:
        output = await self._submit(CapabilityName.INVITATION_ACCEPT_EXECUTE, request)
        if not isinstance(output, ActionExecuteOutput):
            raise RuntimeError("The capability worker returned an invalid acceptance execution.")
        return output

    async def execute_invitation_ignore(
        self,
        request: ActionExecuteInput,
    ) -> ActionExecuteOutput:
        output = await self._submit(CapabilityName.INVITATION_IGNORE_EXECUTE, request)
        if not isinstance(output, ActionExecuteOutput):
            raise RuntimeError("The capability worker returned an invalid ignore execution.")
        return output

    async def execute_message(self, request: ActionExecuteInput) -> ActionExecuteOutput:
        output = await self._submit(CapabilityName.MESSAGING_MESSAGE_EXECUTE, request)
        if not isinstance(output, ActionExecuteOutput):
            raise RuntimeError("The capability worker returned an invalid message execution.")
        return output

    async def execute_post_create(
        self,
        request: ActionExecuteInput,
    ) -> ActionExecuteOutput:
        output = await self._submit(CapabilityName.POSTS_CREATE_EXECUTE, request)
        if not isinstance(output, ActionExecuteOutput):
            raise RuntimeError("The capability worker returned an invalid post execution.")
        return output

    async def execute_post_comment(
        self,
        request: ActionExecuteInput,
    ) -> ActionExecuteOutput:
        output = await self._submit(CapabilityName.POST_COMMENT_EXECUTE, request)
        if not isinstance(output, ActionExecuteOutput):
            raise RuntimeError("The capability worker returned an invalid comment execution.")
        return output

    async def execute_post_reaction(
        self,
        request: ActionExecuteInput,
    ) -> ActionExecuteOutput:
        output = await self._submit(CapabilityName.POST_REACTION_EXECUTE, request)
        if not isinstance(output, ActionExecuteOutput):
            raise RuntimeError("The capability worker returned an invalid reaction execution.")
        return output

    async def _submit(
        self,
        capability_name: CapabilityName,
        request: CapabilityRequest,
        *,
        progress: ProgressReporter | None = None,
    ) -> CapabilityOutput:
        if not self._accepting or not self.running:
            raise BrowserUnavailableError("The local LinkedIn worker is not running.")

        client_id = current_client_id()
        key = (client_id, capability_name, request.request_id)
        fingerprint = canonical_input_fingerprint(request)
        item: _WorkItem | None = None
        async with self._inflight_lock:
            if not self._accepting or not self.running:
                raise BrowserUnavailableError("The local LinkedIn worker is not running.")
            existing = self._inflight.get(key)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise IdempotencyConflictError(
                        "The request ID is already queued with different arguments."
                    )
                existing.waiters += 1
                future = existing.future
            else:
                pagination_lease = await self._reserve_pagination(
                    client_id=client_id,
                    capability_name=capability_name,
                    request=request,
                )
                future = asyncio.get_running_loop().create_future()
                future.add_done_callback(_observe_future)
                item = _WorkItem(
                    key=key,
                    client_id=client_id,
                    capability_name=capability_name,
                    request=request,
                    future=future,
                    progress=progress,
                    pagination_lease=pagination_lease,
                )
                self._inflight[key] = _InFlight(
                    fingerprint=fingerprint,
                    future=future,
                    item=item,
                )

        if item is not None:
            enqueue_task = asyncio.create_task(
                self._enqueue(item),
                name=f"linkedin-enqueue:{item.capability_name.value}",
            )
            item.enqueue_task = enqueue_task
            self._enqueue_tasks.add(enqueue_task)
            enqueue_task.add_done_callback(self._enqueue_tasks.discard)

        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            await self._release_cancelled_waiter(key, future)
            raise

    async def _enqueue(self, item: _WorkItem) -> None:
        try:
            await self._scheduler.put(item.client_id, item)
        except SchedulerClosedError:
            await self._remove_unqueued(item)
            if not item.future.done():
                item.future.set_exception(
                    BrowserUnavailableError("The local LinkedIn worker is shutting down.")
                )
        except asyncio.CancelledError:
            await self._remove_unqueued(item)
            if not item.future.done():
                item.future.cancel()
            raise
        except Exception as error:
            await self._remove_unqueued(item)
            if not item.future.done():
                item.future.set_exception(error)

    async def _reserve_pagination(
        self,
        *,
        client_id: str,
        capability_name: CapabilityName,
        request: CapabilityRequest,
    ) -> PaginationLease | None:
        if self._pagination is None or not isinstance(request, PaginatedInput):
            return None
        if self._call_lookup is not None:
            recorded = await self._call_lookup(
                account_id=self._account_id,
                client_id=client_id,
                request_id=request.request_id,
                capability_name=capability_name,
            )
            if recorded is not None:
                return None
        return await self._pagination.acquire(
            account_id=self._account_id,
            client_id=client_id,
            capability_name=capability_name,
            request=request,
        )

    async def _remove_unqueued(self, item: _WorkItem) -> None:
        async with self._inflight_lock:
            current = self._inflight.get(item.key)
            if current is not None and current.future is item.future:
                self._inflight.pop(item.key, None)
        await self._abort_pagination(item)

    async def _release_cancelled_waiter(
        self,
        key: WorkKey,
        future: asyncio.Future[CapabilityOutput],
    ) -> None:
        item: _WorkItem
        active_task: asyncio.Task[CapabilityOutput] | None = None
        async with self._inflight_lock:
            inflight = self._inflight.get(key)
            if inflight is None or inflight.future is not future:
                return
            inflight.waiters -= 1
            if inflight.waiters > 0:
                return
            item = inflight.item
            item.cancel_requested = True
            if self._active_item is item:
                if not _is_execute_capability(item.capability_name):
                    active_task = self._active_task
            else:
                removed = await self._scheduler.remove(item.client_id, item)
                if removed:
                    self._inflight.pop(key, None)
                    if not future.done():
                        future.cancel()
                elif item.enqueue_task is not None and not item.enqueue_task.done():
                    item.enqueue_task.cancel()
        if active_task is not None:
            active_task.cancel()
        elif future.cancelled():
            await self._abort_pagination(item)

    async def _run(self) -> None:
        while True:
            try:
                item = await self._scheduler.get()
            except SchedulerClosedError:
                self._idle.set()
                return

            operation = asyncio.create_task(
                self._execute_bound(item),
                name=f"linkedin-capability:{item.capability_name.value}",
            )
            async with self._inflight_lock:
                self._active = True
                self._active_item = item
                self._active_task = operation
                self._idle.clear()
                inflight = self._inflight.get(item.key)
                no_waiters = inflight is None or inflight.waiters == 0
                if (
                    item.cancel_requested
                    and no_waiters
                    and not _is_execute_capability(item.capability_name)
                ):
                    operation.cancel()
            try:
                output = await operation
            except asyncio.CancelledError:
                if not item.future.done():
                    if self._closing:
                        item.future.set_exception(
                            BrowserUnavailableError("The local LinkedIn worker was interrupted.")
                        )
                    else:
                        item.future.cancel()
            except Exception as error:
                if not item.future.done():
                    item.future.set_exception(error)
            else:
                if not item.future.done():
                    item.future.set_result(output)
            finally:
                async with self._inflight_lock:
                    current = self._inflight.get(item.key)
                    if current is not None and current.future is item.future:
                        self._inflight.pop(item.key, None)
                    self._active_item = None
                    self._active_task = None
                self._active = False
                await self._abort_pagination(item)
                if self._scheduler.qsize == 0:
                    self._idle.set()

    async def _execute_bound(self, item: _WorkItem) -> CapabilityOutput:
        with bind_client_execution(
            item.client_id,
            pagination_lease=item.pagination_lease,
        ):
            return await self._execute(item)

    async def _abort_pagination(self, item: _WorkItem) -> None:
        if self._pagination is not None and item.pagination_lease is not None:
            await self._pagination.abort(item.pagination_lease)

    async def _execute(self, item: _WorkItem) -> CapabilityOutput:
        if item.capability_name is CapabilityName.JOBS_SEARCH:
            if not isinstance(item.request, JobSearchInput):
                raise RuntimeError("The queued job-search request has an invalid type.")
            return await self._runner.search_jobs(item.request)
        if item.capability_name is CapabilityName.JOBS_GET:
            if not isinstance(item.request, JobDetailInput):
                raise RuntimeError("The queued job-detail request has an invalid type.")
            return await self._runner.get_job(item.request)
        if item.capability_name is CapabilityName.PEOPLE_SEARCH:
            if not isinstance(item.request, PeopleSearchInput):
                raise RuntimeError("The queued People-search request has an invalid type.")
            return await self._runner.search_people(item.request)
        if item.capability_name is CapabilityName.PEOPLE_GET:
            if not isinstance(item.request, PeopleGetInput):
                raise RuntimeError("The queued member-profile request has an invalid type.")
            return await self._runner.get_person(item.request)
        if item.capability_name is CapabilityName.COMPANIES_SEARCH:
            if not isinstance(item.request, CompanySearchInput):
                raise RuntimeError("The queued Company-search request has an invalid type.")
            return await self._runner.search_companies(item.request)
        if item.capability_name is CapabilityName.COMPANIES_GET:
            if not isinstance(item.request, CompanyGetInput):
                raise RuntimeError("The queued company-profile request has an invalid type.")
            return await self._runner.get_company(item.request)
        if item.capability_name is CapabilityName.POSTS_SEARCH:
            if not isinstance(item.request, PostSearchInput):
                raise RuntimeError("The queued post-search request has an invalid type.")
            return await self._runner.search_posts(item.request)
        if item.capability_name is CapabilityName.POSTS_GET:
            if not isinstance(item.request, PostGetInput):
                raise RuntimeError("The queued post-detail request has an invalid type.")
            return await self._runner.get_post(item.request)
        if item.capability_name is CapabilityName.POST_COMMENTS_LIST:
            if not isinstance(item.request, PostCommentsListInput):
                raise RuntimeError("The queued post-discussion request has an invalid type.")
            return await self._runner.list_post_comments(item.request)
        if item.capability_name is CapabilityName.INVITATIONS_LIST:
            if not isinstance(item.request, InvitationListInput):
                raise RuntimeError("The queued invitation-list request has an invalid type.")
            return await self._runner.list_invitations(
                item.request,
                progress=item.progress,
            )
        if item.capability_name is CapabilityName.CONNECTIONS_LIST:
            if not isinstance(item.request, ConnectionsListInput):
                raise RuntimeError("The queued connections-list request has an invalid type.")
            return await self._runner.list_connections(item.request)
        if item.capability_name is CapabilityName.CONNECTIONS_SEARCH:
            if not isinstance(item.request, ConnectionsSearchInput):
                raise RuntimeError("The queued connections-search request has an invalid type.")
            return await self._runner.search_connections(item.request)
        if item.capability_name is CapabilityName.MESSAGING_SEARCH:
            if not isinstance(item.request, ConversationSearchInput):
                raise RuntimeError("The queued inbox request has an invalid type.")
            return await self._runner.search_messages(item.request)
        if item.capability_name is CapabilityName.MESSAGING_CONVERSATION_GET:
            if not isinstance(item.request, ConversationGetInput):
                raise RuntimeError("The queued conversation request has an invalid type.")
            return await self._runner.get_conversation(item.request)
        if item.capability_name is CapabilityName.INVITATION_SEND_PREPARE:
            if not isinstance(item.request, InvitationSendPrepareInput):
                raise RuntimeError("The queued invitation-draft request has an invalid type.")
            return await self._runner.prepare_invitation_send(item.request)
        if item.capability_name is CapabilityName.INVITATION_ACCEPT_PREPARE:
            if not isinstance(item.request, InvitationAcceptPrepareInput):
                raise RuntimeError("The queued acceptance-draft request has an invalid type.")
            return await self._runner.prepare_invitation_accept(item.request)
        if item.capability_name is CapabilityName.INVITATION_IGNORE_PREPARE:
            if not isinstance(item.request, InvitationIgnorePrepareInput):
                raise RuntimeError("The queued ignore-draft request has an invalid type.")
            return await self._runner.prepare_invitation_ignore(item.request)
        if item.capability_name is CapabilityName.MESSAGING_MESSAGE_PREPARE:
            if not isinstance(item.request, MessagePrepareInput):
                raise RuntimeError("The queued message-draft request has an invalid type.")
            return await self._runner.prepare_message(item.request)
        if item.capability_name is CapabilityName.POSTS_CREATE_PREPARE:
            if not isinstance(item.request, PostCreatePrepareInput):
                raise RuntimeError("The queued post-draft request has an invalid type.")
            return await self._runner.prepare_post_create(item.request)
        if item.capability_name is CapabilityName.POST_COMMENT_PREPARE:
            if not isinstance(item.request, PostCommentPrepareInput):
                raise RuntimeError("The queued comment-draft request has an invalid type.")
            return await self._runner.prepare_post_comment(item.request)
        if item.capability_name is CapabilityName.POST_REACTION_PREPARE:
            if not isinstance(item.request, PostReactionPrepareInput):
                raise RuntimeError("The queued reaction-draft request has an invalid type.")
            return await self._runner.prepare_post_reaction(item.request)
        if item.capability_name is CapabilityName.INVITATION_SEND_EXECUTE:
            if not isinstance(item.request, ActionExecuteInput):
                raise RuntimeError("The queued invitation execution has an invalid type.")
            return await self._runner.execute_invitation_send(item.request)
        if item.capability_name is CapabilityName.INVITATION_ACCEPT_EXECUTE:
            if not isinstance(item.request, ActionExecuteInput):
                raise RuntimeError("The queued acceptance execution has an invalid type.")
            return await self._runner.execute_invitation_accept(item.request)
        if item.capability_name is CapabilityName.INVITATION_IGNORE_EXECUTE:
            if not isinstance(item.request, ActionExecuteInput):
                raise RuntimeError("The queued ignore execution has an invalid type.")
            return await self._runner.execute_invitation_ignore(item.request)
        if item.capability_name is CapabilityName.MESSAGING_MESSAGE_EXECUTE:
            if not isinstance(item.request, ActionExecuteInput):
                raise RuntimeError("The queued message execution has an invalid type.")
            return await self._runner.execute_message(item.request)
        if item.capability_name is CapabilityName.POSTS_CREATE_EXECUTE:
            if not isinstance(item.request, ActionExecuteInput):
                raise RuntimeError("The queued post execution has an invalid type.")
            return await self._runner.execute_post_create(item.request)
        if item.capability_name is CapabilityName.POST_COMMENT_EXECUTE:
            if not isinstance(item.request, ActionExecuteInput):
                raise RuntimeError("The queued comment execution has an invalid type.")
            return await self._runner.execute_post_comment(item.request)
        if item.capability_name is CapabilityName.POST_REACTION_EXECUTE:
            if not isinstance(item.request, ActionExecuteInput):
                raise RuntimeError("The queued reaction execution has an invalid type.")
            return await self._runner.execute_post_reaction(item.request)
        raise RuntimeError(f"Unsupported queued capability: {item.capability_name.value}")

    async def quiesce(self) -> None:
        """Reject queued work and wait for the one active operation to finish."""

        self._accepting = False
        queued = await self._scheduler.close()
        await self._finish_enqueue_tasks()
        await self._reject_queued(queued)
        if not self._active:
            self._idle.set()
        await self._idle.wait()

    async def close(self) -> None:
        self._accepting = False
        self._closing = True
        queued = await self._scheduler.close()
        await self._finish_enqueue_tasks()
        await self._reject_queued(queued)

        active_task = self._active_task
        active_item = self._active_item
        if (
            active_task is not None
            and active_item is not None
            and not _is_execute_capability(active_item.capability_name)
        ):
            active_task.cancel()
        if active_item is not None and _is_execute_capability(active_item.capability_name):
            await self._idle.wait()

        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        async with self._inflight_lock:
            for inflight in self._inflight.values():
                if not inflight.future.done():
                    inflight.future.set_exception(
                        BrowserUnavailableError("The local LinkedIn worker is shutting down.")
                    )
            self._inflight.clear()

    async def _reject_queued(self, queued: tuple[_WorkItem, ...]) -> None:
        if not queued:
            return
        shutdown_error = BrowserUnavailableError("The local LinkedIn worker is shutting down.")
        async with self._inflight_lock:
            for item in queued:
                current = self._inflight.get(item.key)
                if current is not None and current.future is item.future:
                    self._inflight.pop(item.key, None)
                if not item.future.done():
                    item.future.set_exception(shutdown_error)
        for item in queued:
            await self._abort_pagination(item)

    async def _finish_enqueue_tasks(self) -> None:
        tasks = tuple(self._enqueue_tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
