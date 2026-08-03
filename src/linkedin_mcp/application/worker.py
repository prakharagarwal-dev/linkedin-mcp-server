"""Single-consumer in-process queue for LinkedIn capability execution."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol

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
WorkKey = tuple[CapabilityName, str]
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
    capability_name: CapabilityName
    request: CapabilityRequest
    future: asyncio.Future[CapabilityOutput]
    progress: ProgressReporter | None = None


@dataclass(slots=True)
class _InFlight:
    fingerprint: str
    future: asyncio.Future[CapabilityOutput]


class _EnqueuedCallerCancelled(asyncio.CancelledError):
    """Signal that caller cancellation occurred after queue ownership transferred."""


def _observe_future(future: asyncio.Future[CapabilityOutput]) -> None:
    if future.cancelled():
        return
    future.exception()


class CapabilityWorker:
    """Serialize every browser-backed capability through one local worker."""

    def __init__(self, runner: CapabilityRunner, *, queue_capacity: int) -> None:
        self._runner = runner
        self._queue: asyncio.Queue[_WorkItem] = asyncio.Queue(maxsize=queue_capacity)
        self._inflight: dict[WorkKey, _InFlight] = {}
        self._inflight_lock = asyncio.Lock()
        self._shutdown = asyncio.Event()
        self._pending_puts: set[asyncio.Task[None]] = set()
        self._task: asyncio.Task[None] | None = None
        self._accepting = False
        self._active = False
        self._idle = asyncio.Event()
        self._idle.set()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    async def start(self) -> None:
        if self.running:
            return
        self._shutdown.clear()
        self._accepting = True
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

        key = (capability_name, request.request_id)
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
                future = existing.future
            else:
                future = asyncio.get_running_loop().create_future()
                future.add_done_callback(_observe_future)
                self._inflight[key] = _InFlight(
                    fingerprint=fingerprint,
                    future=future,
                )
                item = _WorkItem(
                    key=key,
                    capability_name=capability_name,
                    request=request,
                    future=future,
                    progress=progress,
                )

        if item is not None:
            try:
                await self._enqueue_or_shutdown(item)
            except _EnqueuedCallerCancelled:
                raise asyncio.CancelledError from None
            except asyncio.CancelledError:
                await self._remove_unqueued(item)
                if not future.done():
                    future.cancel()
                raise
            except Exception as error:
                await self._remove_unqueued(item)
                if not future.done():
                    future.set_exception(error)
                raise

        return await asyncio.shield(future)

    async def _enqueue_or_shutdown(self, item: _WorkItem) -> None:
        put_task = asyncio.create_task(self._queue.put(item))
        self._pending_puts.add(put_task)
        shutdown_task = asyncio.create_task(self._shutdown.wait())
        try:
            try:
                done, _ = await asyncio.wait(
                    (put_task, shutdown_task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
            except asyncio.CancelledError as error:
                if put_task.done() and not put_task.cancelled() and put_task.exception() is None:
                    raise _EnqueuedCallerCancelled from error
                raise
            if shutdown_task in done:
                put_task.cancel()
                with suppress(asyncio.CancelledError):
                    await put_task
                raise BrowserUnavailableError("The local LinkedIn worker is shutting down.")
            await put_task
        finally:
            self._pending_puts.discard(put_task)
            shutdown_task.cancel()
            with suppress(asyncio.CancelledError):
                await shutdown_task

    async def _remove_unqueued(self, item: _WorkItem) -> None:
        async with self._inflight_lock:
            current = self._inflight.get(item.key)
            if current is not None and current.future is item.future:
                self._inflight.pop(item.key, None)

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            self._active = True
            self._idle.clear()
            try:
                output = await self._execute(item)
            except asyncio.CancelledError:
                if not item.future.done():
                    item.future.set_exception(
                        BrowserUnavailableError("The local LinkedIn worker was interrupted.")
                    )
                raise
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
                self._queue.task_done()
                self._active = False
                if self._queue.empty():
                    self._idle.set()

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
        self._shutdown.set()
        pending_puts = tuple(self._pending_puts)
        for put_task in pending_puts:
            put_task.cancel()
        if pending_puts:
            await asyncio.gather(*pending_puts, return_exceptions=True)

        shutdown_error = BrowserUnavailableError("The local LinkedIn worker is shutting down.")
        while True:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if not item.future.done():
                item.future.set_exception(shutdown_error)
            self._queue.task_done()
        if not self._active:
            self._idle.set()
        await self._idle.wait()

    async def close(self) -> None:
        self._accepting = False
        self._shutdown.set()
        pending_puts = tuple(self._pending_puts)
        for put_task in pending_puts:
            put_task.cancel()
        if pending_puts:
            await asyncio.gather(*pending_puts, return_exceptions=True)

        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        shutdown_error = BrowserUnavailableError("The local LinkedIn worker is shutting down.")
        while True:
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if not item.future.done():
                item.future.set_exception(shutdown_error)
            self._queue.task_done()

        async with self._inflight_lock:
            for inflight in self._inflight.values():
                if not inflight.future.done():
                    inflight.future.set_exception(shutdown_error)
            self._inflight.clear()
