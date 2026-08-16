"""Single-consumer in-process queue for LinkedIn capability execution."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol

from linkedin_mcp.app.pagination import PaginationLease, PaginationManager
from linkedin_mcp.app.scheduler import FairClientScheduler, SchedulerClosedError
from linkedin_mcp.errors import BrowserUnavailableError
from linkedin_mcp.linkedin.actions import ActionOutput
from linkedin_mcp.linkedin.common import CapabilityName, PaginatedInput
from linkedin_mcp.linkedin.companies.models import (
    CompanyGetInput,
    CompanyGetOutput,
    CompanySearchInput,
    CompanySearchOutput,
)
from linkedin_mcp.linkedin.jobs.models import (
    JobDetailInput,
    JobDetailOutput,
    JobSearchInput,
    JobSearchOutput,
)
from linkedin_mcp.linkedin.messaging.models import (
    ConversationGetInput,
    ConversationGetOutput,
    ConversationSearchInput,
    ConversationSearchOutput,
    MessageSendInput,
)
from linkedin_mcp.linkedin.network.models import (
    ConnectionsListInput,
    ConnectionsListOutput,
    ConnectionsSearchInput,
    ConnectionsSearchOutput,
    InvitationAcceptInput,
    InvitationIgnoreInput,
    InvitationListInput,
    InvitationListOutput,
    InvitationSendInput,
)
from linkedin_mcp.linkedin.people.models import (
    PeopleGetInput,
    PeopleGetOutput,
    PeopleSearchInput,
    PeopleSearchOutput,
)
from linkedin_mcp.linkedin.posts.models import (
    PostCommentInput,
    PostCommentsListInput,
    PostCommentsListOutput,
    PostCreateInput,
    PostGetInput,
    PostGetOutput,
    PostReactionInput,
    PostSearchInput,
    PostSearchOutput,
)
from linkedin_mcp.mcp.context import (
    bind_client_execution,
    current_client_id,
)

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
    | PostCreateInput
    | PostCommentInput
    | PostReactionInput
    | InvitationListInput
    | ConnectionsListInput
    | ConnectionsSearchInput
    | ConversationSearchInput
    | ConversationGetInput
    | InvitationSendInput
    | InvitationAcceptInput
    | InvitationIgnoreInput
    | MessageSendInput
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
    | ActionOutput
)
WorkKey = tuple[str, CapabilityName, str]
ProgressReporter = Callable[[int, int, str], Awaitable[None]]


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

    async def send_invitation(self, request: InvitationSendInput) -> ActionOutput: ...

    async def accept_invitation(self, request: InvitationAcceptInput) -> ActionOutput: ...

    async def ignore_invitation(self, request: InvitationIgnoreInput) -> ActionOutput: ...

    async def send_message(self, request: MessageSendInput) -> ActionOutput: ...

    async def create_post(self, request: PostCreateInput) -> ActionOutput: ...

    async def comment_on_post(self, request: PostCommentInput) -> ActionOutput: ...

    async def react_to_post(self, request: PostReactionInput) -> ActionOutput: ...


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


def _observe_future(future: asyncio.Future[CapabilityOutput]) -> None:
    if future.cancelled():
        return
    future.exception()


_WRITE_CAPABILITIES = frozenset(
    {
        CapabilityName.INVITATION_SEND,
        CapabilityName.INVITATION_ACCEPT,
        CapabilityName.INVITATION_IGNORE,
        CapabilityName.MESSAGING_SEND,
        CapabilityName.POSTS_CREATE,
        CapabilityName.POST_COMMENT,
        CapabilityName.POST_REACT,
    }
)


def _is_write_capability(capability_name: CapabilityName) -> bool:
    return capability_name in _WRITE_CAPABILITIES


class CapabilityWorker:
    """Serialize every browser-backed capability through one local worker."""

    def __init__(
        self,
        runner: CapabilityRunner,
        *,
        queue_capacity: int,
        pagination: PaginationManager | None = None,
        account_id: str = "personal",
    ) -> None:
        self._runner = runner
        self._scheduler: FairClientScheduler[str, _WorkItem] = FairClientScheduler(
            capacity=queue_capacity
        )
        self._pagination = pagination
        self._account_id = account_id
        self._inflight: dict[WorkKey, _WorkItem] = {}
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

    async def send_invitation(self, request: InvitationSendInput) -> ActionOutput:
        output = await self._submit(CapabilityName.INVITATION_SEND, request)
        if not isinstance(output, ActionOutput):
            raise RuntimeError("The capability worker returned an invalid invitation result.")
        return output

    async def accept_invitation(self, request: InvitationAcceptInput) -> ActionOutput:
        output = await self._submit(CapabilityName.INVITATION_ACCEPT, request)
        if not isinstance(output, ActionOutput):
            raise RuntimeError("The capability worker returned an invalid acceptance result.")
        return output

    async def ignore_invitation(self, request: InvitationIgnoreInput) -> ActionOutput:
        output = await self._submit(CapabilityName.INVITATION_IGNORE, request)
        if not isinstance(output, ActionOutput):
            raise RuntimeError("The capability worker returned an invalid ignore result.")
        return output

    async def send_message(self, request: MessageSendInput) -> ActionOutput:
        output = await self._submit(CapabilityName.MESSAGING_SEND, request)
        if not isinstance(output, ActionOutput):
            raise RuntimeError("The capability worker returned an invalid message result.")
        return output

    async def create_post(self, request: PostCreateInput) -> ActionOutput:
        output = await self._submit(CapabilityName.POSTS_CREATE, request)
        if not isinstance(output, ActionOutput):
            raise RuntimeError("The capability worker returned an invalid post result.")
        return output

    async def comment_on_post(self, request: PostCommentInput) -> ActionOutput:
        output = await self._submit(CapabilityName.POST_COMMENT, request)
        if not isinstance(output, ActionOutput):
            raise RuntimeError("The capability worker returned an invalid comment result.")
        return output

    async def react_to_post(self, request: PostReactionInput) -> ActionOutput:
        output = await self._submit(CapabilityName.POST_REACT, request)
        if not isinstance(output, ActionOutput):
            raise RuntimeError("The capability worker returned an invalid reaction result.")
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
        key = (client_id, capability_name, str(uuid.uuid4()))
        async with self._inflight_lock:
            if not self._accepting or not self.running:
                raise BrowserUnavailableError("The local LinkedIn worker is not running.")
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
            self._inflight[key] = item

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
            await self._cancel_submission(key, future)
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
        return await self._pagination.acquire(
            account_id=self._account_id,
            client_id=client_id,
            capability_name=capability_name,
            request=request,
        )

    async def _remove_unqueued(self, item: _WorkItem) -> None:
        async with self._inflight_lock:
            current = self._inflight.get(item.key)
            if current is item:
                self._inflight.pop(item.key, None)
        await self._abort_pagination(item)

    async def _cancel_submission(
        self,
        key: WorkKey,
        future: asyncio.Future[CapabilityOutput],
    ) -> None:
        item: _WorkItem
        active_task: asyncio.Task[CapabilityOutput] | None = None
        async with self._inflight_lock:
            current = self._inflight.get(key)
            if current is None or current.future is not future:
                return
            item = current
            item.cancel_requested = True
            if self._active_item is item:
                if not _is_write_capability(item.capability_name):
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
                if item.cancel_requested and not _is_write_capability(item.capability_name):
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
                    if current is item:
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
        if item.capability_name is CapabilityName.INVITATION_SEND:
            if not isinstance(item.request, InvitationSendInput):
                raise RuntimeError("The queued invitation request has an invalid type.")
            return await self._runner.send_invitation(item.request)
        if item.capability_name is CapabilityName.INVITATION_ACCEPT:
            if not isinstance(item.request, InvitationAcceptInput):
                raise RuntimeError("The queued acceptance request has an invalid type.")
            return await self._runner.accept_invitation(item.request)
        if item.capability_name is CapabilityName.INVITATION_IGNORE:
            if not isinstance(item.request, InvitationIgnoreInput):
                raise RuntimeError("The queued ignore request has an invalid type.")
            return await self._runner.ignore_invitation(item.request)
        if item.capability_name is CapabilityName.MESSAGING_SEND:
            if not isinstance(item.request, MessageSendInput):
                raise RuntimeError("The queued message request has an invalid type.")
            return await self._runner.send_message(item.request)
        if item.capability_name is CapabilityName.POSTS_CREATE:
            if not isinstance(item.request, PostCreateInput):
                raise RuntimeError("The queued post request has an invalid type.")
            return await self._runner.create_post(item.request)
        if item.capability_name is CapabilityName.POST_COMMENT:
            if not isinstance(item.request, PostCommentInput):
                raise RuntimeError("The queued comment request has an invalid type.")
            return await self._runner.comment_on_post(item.request)
        if item.capability_name is CapabilityName.POST_REACT:
            if not isinstance(item.request, PostReactionInput):
                raise RuntimeError("The queued reaction request has an invalid type.")
            return await self._runner.react_to_post(item.request)
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
            and not _is_write_capability(active_item.capability_name)
        ):
            active_task.cancel()
        if active_item is not None and _is_write_capability(active_item.capability_name):
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
                if current is item:
                    self._inflight.pop(item.key, None)
                if not item.future.done():
                    item.future.set_exception(shutdown_error)
        for item in queued:
            await self._abort_pagination(item)

    async def _finish_enqueue_tasks(self) -> None:
        tasks = tuple(self._enqueue_tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
