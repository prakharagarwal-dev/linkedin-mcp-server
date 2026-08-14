from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from pydantic import HttpUrl

from linkedin_mcp.application import (
    CapabilityRunner,
    CapabilityWorker,
    PaginationManager,
    bind_client_execution,
)
from linkedin_mcp.domain.models import (
    ActionOutcome,
    ActionOutput,
    ActionResult,
    ActionType,
    CapabilityName,
    CompanyGetInput,
    CompanyGetOutput,
    CompanyProfileCoverage,
    CompanyProfileObservation,
    CompanySearchCoverage,
    CompanySearchInput,
    CompanySearchOutput,
    ConnectionsListInput,
    ConnectionsSearchFilters,
    ConnectionsSearchInput,
    ConnectionsSearchOutput,
    ConversationGetInput,
    ConversationSearchInput,
    EvidenceField,
    InvitationAcceptInput,
    InvitationIgnoreInput,
    InvitationListInput,
    InvitationSendInput,
    JobDetailInput,
    JobDetailObservation,
    JobDetailOutput,
    JobSearchCoverage,
    JobSearchInput,
    JobSearchOutput,
    MessageSendInput,
    PaginatedInput,
    PaginationMetadata,
    PeopleGetInput,
    PeopleGetOutput,
    PeopleSearchCoverage,
    PeopleSearchInput,
    PeopleSearchOutput,
    PersonProfileCoverage,
    PersonProfileObservation,
    PostAuthor,
    PostAuthorType,
    PostCommentInput,
    PostCommentsCoverage,
    PostCommentsListInput,
    PostCommentsListOutput,
    PostCreateInput,
    PostDetailCoverage,
    PostGetInput,
    PostGetOutput,
    PostObservation,
    PostReactionInput,
    PostSearchCoverage,
    PostSearchInput,
    PostSearchOutput,
    ReactionState,
    StopReason,
    TextPostContent,
)
from linkedin_mcp.errors import BrowserUnavailableError, IdempotencyConflictError


def _pagination(request: PaginatedInput) -> PaginationMetadata:
    return PaginationMetadata(
        scan_id=str(uuid.uuid4()),
        page_size=request.page_size,
        returned_count=0,
        cumulative_count=0,
        has_more=False,
    )


def _search_output(request: JobSearchInput) -> JobSearchOutput:
    return JobSearchOutput(
        context_id=request.context_id,
        request_id=request.request_id,
        jobs=(),
        coverage=JobSearchCoverage(
            query=request.query,
            location=request.location,
            freshness_hours=request.freshness_hours,
            pages_visited=1,
            result_count=0,
            max_results=request.max_results,
            stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
            captured_at=datetime.now(UTC),
        ),
        pagination=_pagination(request),
        sources=(),
    )


ActionRequest = (
    InvitationSendInput
    | InvitationAcceptInput
    | InvitationIgnoreInput
    | MessageSendInput
    | PostCreateInput
    | PostCommentInput
    | PostReactionInput
)


def _action_output(
    request: ActionRequest,
    *,
    action_type: ActionType,
    final_state: str,
) -> ActionOutput:
    now = datetime.now(UTC)
    return ActionOutput(
        context_id=request.context_id,
        request_id=request.request_id,
        result=ActionResult(
            action_type=action_type,
            outcome=ActionOutcome.VERIFIED,
            performed=True,
            final_state=final_state,
            detail="Fixture action verified.",
            started_at=now,
            completed_at=now,
        ),
        sources=(),
    )


class BlockingRunner:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.search_queries: list[str | None] = []
        self.people_calls: list[str] = []
        self.company_calls: list[str] = []
        self.extension_calls: list[str] = []

    async def search_jobs(self, request: JobSearchInput) -> JobSearchOutput:
        self.search_queries.append(request.query)
        if len(self.search_queries) == 1:
            self.started.set()
            await self.release.wait()
        return _search_output(request)

    async def get_job(self, request: JobDetailInput) -> JobDetailOutput:
        title = f"Job {request.job_id}"
        return JobDetailOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            job=JobDetailObservation(
                job_id=request.job_id,
                job_url=HttpUrl(f"https://www.linkedin.com/jobs/view/{request.job_id}/"),
                title=title,
                visible_text=title,
                evidence=(EvidenceField(field="title", quote=title),),
                captured_at=datetime.now(UTC),
            ),
            sources=(),
        )

    async def search_people(self, request: PeopleSearchInput) -> PeopleSearchOutput:
        self.people_calls.append("search")
        return PeopleSearchOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            people=(),
            coverage=PeopleSearchCoverage(
                query=request.query,
                title_keywords=request.title_keywords,
                filters=request.filters,
                pages_visited=1,
                result_count=0,
                max_results=request.max_results,
                stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=datetime.now(UTC),
            ),
            pagination=_pagination(request),
            sources=(),
        )

    async def search_connections(
        self,
        request: ConnectionsSearchInput,
    ) -> ConnectionsSearchOutput:
        self.people_calls.append("connections-search")
        return ConnectionsSearchOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            people=(),
            coverage=PeopleSearchCoverage(
                query=request.query,
                title_keywords=request.title_keywords,
                filters=request.filters.as_people_search_filters(),
                pages_visited=1,
                result_count=0,
                max_results=request.max_results,
                stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=datetime.now(UTC),
            ),
            pagination=_pagination(request),
            sources=(),
        )

    async def get_person(self, request: PeopleGetInput) -> PeopleGetOutput:
        self.people_calls.append("get")
        captured_at = datetime.now(UTC)
        visible_text = "Jane Doe"
        return PeopleGetOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            person=PersonProfileObservation(
                profile_slug=request.profile_slug,
                profile_url=HttpUrl(f"https://www.linkedin.com/in/{request.profile_slug}/"),
                name=visible_text,
                visible_text=visible_text,
                evidence=(),
                coverage=PersonProfileCoverage(
                    pages_visited=1,
                    detail_pages_discovered=0,
                    detail_pages_visited=0,
                    detail_page_limit=20,
                    truncated=False,
                    captured_at=captured_at,
                ),
                captured_at=captured_at,
            ),
            sources=(),
        )

    async def search_companies(self, request: CompanySearchInput) -> CompanySearchOutput:
        self.company_calls.append("search")
        return CompanySearchOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            companies=(),
            coverage=CompanySearchCoverage(
                query=request.query,
                filters=request.filters,
                pages_visited=1,
                result_count=0,
                max_results=request.max_results,
                stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=datetime.now(UTC),
            ),
            pagination=_pagination(request),
            sources=(),
        )

    async def get_company(self, request: CompanyGetInput) -> CompanyGetOutput:
        self.company_calls.append("get")
        captured_at = datetime.now(UTC)
        visible_text = "Acme Cloud"
        return CompanyGetOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            company=CompanyProfileObservation(
                company_slug=request.company_slug,
                company_url=HttpUrl(f"https://www.linkedin.com/company/{request.company_slug}/"),
                name=visible_text,
                visible_text=visible_text,
                evidence=(),
                coverage=CompanyProfileCoverage(captured_at=captured_at),
                captured_at=captured_at,
            ),
            sources=(),
        )

    async def search_posts(self, request: PostSearchInput) -> PostSearchOutput:
        self.extension_calls.append("post-search")
        return PostSearchOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            posts=(),
            coverage=PostSearchCoverage(
                query=request.query,
                filters=request.filters,
                pages_visited=1,
                result_count=0,
                max_results=request.max_results,
                stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=datetime.now(UTC),
            ),
            pagination=_pagination(request),
            sources=(),
        )

    async def get_post(self, request: PostGetInput) -> PostGetOutput:
        self.extension_calls.append("post-get")
        visible_text = "Jane Doe\nA reliable post"
        captured_at = datetime.now(UTC)
        post_url = HttpUrl(f"https://www.linkedin.com/feed/update/urn:li:{request.post_ref}/")
        return PostGetOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            post=PostObservation(
                post_ref=request.post_ref,
                displayed_post_ref=request.post_ref,
                post_url=post_url,
                author=PostAuthor(
                    author_type=PostAuthorType.MEMBER,
                    name="Jane Doe",
                    profile_slug="jane-doe",
                ),
                text="A reliable post",
                visible_text=visible_text,
                evidence=(),
                coverage=PostDetailCoverage(
                    requested_post_ref=request.post_ref,
                    displayed_post_ref=request.post_ref,
                    pages_visited=1,
                    source_urls=(post_url,),
                    text_expanded=True,
                    attachment_count=0,
                    link_count=0,
                    mention_count=0,
                    hashtag_count=0,
                    poll_present=False,
                    reshared_post_present=False,
                    captured_at=captured_at,
                ),
                captured_at=captured_at,
            ),
            sources=(),
        )

    async def list_post_comments(
        self,
        request: PostCommentsListInput,
    ) -> PostCommentsListOutput:
        self.extension_calls.append("post-comments")
        return PostCommentsListOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            threads=(),
            coverage=PostCommentsCoverage(
                post_ref=request.post_ref,
                discussion_post_ref=request.post_ref,
                sort_by=request.sort_by,
                expansion_rounds=0,
                top_level_visible=0,
                top_level_returned=0,
                replies_visible=0,
                replies_returned=0,
                max_comments=request.max_comments,
                max_replies_per_comment=request.max_replies_per_comment,
                truncated=False,
                captured_at=datetime.now(UTC),
            ),
            pagination=_pagination(request),
            sources=(),
        )

    async def send_invitation(self, request: InvitationSendInput) -> ActionOutput:
        self.extension_calls.append("invitation-send")
        return _action_output(
            request,
            action_type=ActionType.INVITATION_SEND,
            final_state="invitation_pending",
        )

    async def accept_invitation(self, request: InvitationAcceptInput) -> ActionOutput:
        self.extension_calls.append("invitation-accept")
        return _action_output(
            request,
            action_type=ActionType.INVITATION_ACCEPT,
            final_state="invitation_accepted",
        )

    async def ignore_invitation(self, request: InvitationIgnoreInput) -> ActionOutput:
        self.extension_calls.append("invitation-ignore")
        return _action_output(
            request,
            action_type=ActionType.INVITATION_IGNORE,
            final_state="invitation_ignored",
        )

    async def send_message(self, request: MessageSendInput) -> ActionOutput:
        self.extension_calls.append("message-send")
        return _action_output(
            request,
            action_type=ActionType.MESSAGE_SEND,
            final_state="message_sent",
        )

    async def create_post(self, request: PostCreateInput) -> ActionOutput:
        self.extension_calls.append("post-create")
        return _action_output(
            request,
            action_type=ActionType.POST_CREATE,
            final_state="post_published",
        )

    async def comment_on_post(self, request: PostCommentInput) -> ActionOutput:
        self.extension_calls.append("post-comment")
        return _action_output(
            request,
            action_type=ActionType.COMMENT_CREATE,
            final_state="comment_published",
        )

    async def react_to_post(self, request: PostReactionInput) -> ActionOutput:
        self.extension_calls.append("post-react")
        return _action_output(
            request,
            action_type=ActionType.REACTION_SET,
            final_state="reaction_set:love",
        )


class BlockingActionRunner(BlockingRunner):
    def __init__(self) -> None:
        super().__init__()
        self.write_started = asyncio.Event()
        self.write_release = asyncio.Event()
        self.write_completed = asyncio.Event()
        self.write_calls = 0

    async def comment_on_post(self, request: PostCommentInput) -> ActionOutput:
        self.write_calls += 1
        self.write_started.set()
        await self.write_release.wait()
        self.write_completed.set()
        return _action_output(
            request,
            action_type=ActionType.COMMENT_CREATE,
            final_state="comment_published",
        )


async def _wait_for_queue_depth(worker: CapabilityWorker, depth: int) -> None:
    for _ in range(100):
        if worker.queue_depth == depth:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"The worker queue did not reach depth {depth}.")


async def _search_as(
    worker: CapabilityWorker,
    client_id: str,
    request: JobSearchInput,
) -> JobSearchOutput:
    with bind_client_execution(client_id):
        return await worker.search_jobs(request)


@pytest.mark.asyncio
async def test_worker_serializes_fifo_and_coalesces_identical_inflight_calls() -> None:
    runner = BlockingRunner()
    worker = CapabilityWorker(cast(CapabilityRunner, runner), queue_capacity=10)
    await worker.start()
    first_request = JobSearchInput(
        context_id="context-1",
        request_id="request-1",
        query="python",
    )
    second_request = JobSearchInput(
        context_id="context-1",
        request_id="request-2",
        query="rust",
    )

    first = asyncio.create_task(worker.search_jobs(first_request))
    await runner.started.wait()
    duplicate = asyncio.create_task(worker.search_jobs(first_request))
    second = asyncio.create_task(worker.search_jobs(second_request))
    await _wait_for_queue_depth(worker, 1)

    assert runner.search_queries == ["python"]
    assert worker.queue_depth == 1
    with pytest.raises(IdempotencyConflictError, match="different arguments"):
        await worker.search_jobs(first_request.model_copy(update={"query": "go"}))

    runner.release.set()
    first_output, duplicate_output, second_output = await asyncio.gather(
        first,
        duplicate,
        second,
    )
    await worker.close()

    assert first_output == duplicate_output
    assert second_output.request_id == "request-2"
    assert runner.search_queries == ["python", "rust"]
    assert worker.running is False


@pytest.mark.asyncio
async def test_worker_round_robins_clients_while_preserving_each_client_order() -> None:
    runner = BlockingRunner()
    worker = CapabilityWorker(cast(CapabilityRunner, runner), queue_capacity=10)
    await worker.start()

    def request(name: str) -> JobSearchInput:
        return JobSearchInput(
            context_id="fairness",
            request_id=name,
            query=name,
        )

    calls = [asyncio.create_task(_search_as(worker, "client-a", request("a-1")))]
    await runner.started.wait()
    calls.extend(
        (
            asyncio.create_task(_search_as(worker, "client-a", request("a-2"))),
            asyncio.create_task(_search_as(worker, "client-a", request("a-3"))),
            asyncio.create_task(_search_as(worker, "client-b", request("b-1"))),
        )
    )
    await _wait_for_queue_depth(worker, 3)

    runner.release.set()
    await asyncio.gather(*calls)
    await worker.close()

    assert runner.search_queries == ["a-1", "b-1", "a-2", "a-3"]


@pytest.mark.asyncio
async def test_worker_namespaces_equal_request_ids_by_client() -> None:
    runner = BlockingRunner()
    worker = CapabilityWorker(cast(CapabilityRunner, runner), queue_capacity=10)
    await worker.start()
    first = JobSearchInput(
        context_id="client-isolation",
        request_id="same-request",
        query="python",
    )
    second = first.model_copy(update={"query": "rust"})

    first_call = asyncio.create_task(_search_as(worker, "client-a", first))
    await runner.started.wait()
    second_call = asyncio.create_task(_search_as(worker, "client-b", second))
    await _wait_for_queue_depth(worker, 1)
    runner.release.set()
    await asyncio.gather(first_call, second_call)
    await worker.close()

    assert runner.search_queries == ["python", "rust"]


@pytest.mark.asyncio
async def test_worker_dispatches_post_read_capabilities() -> None:
    runner = BlockingRunner()
    worker = CapabilityWorker(cast(CapabilityRunner, runner), queue_capacity=10)
    await worker.start()
    post_ref = "activity:7312345678901234567"

    outputs = (
        await worker.search_posts(
            PostSearchInput(
                context_id="context-1",
                request_id="post-search-1",
                query="python",
            )
        ),
        await worker.get_post(
            PostGetInput(
                context_id="context-1",
                request_id="post-get-1",
                post_ref=post_ref,
            )
        ),
        await worker.list_post_comments(
            PostCommentsListInput(
                context_id="context-1",
                request_id="post-comments-1",
                post_ref=post_ref,
            )
        ),
    )
    await worker.close()

    assert tuple(output.request_id for output in outputs) == (
        "post-search-1",
        "post-get-1",
        "post-comments-1",
    )
    assert runner.extension_calls == [
        "post-search",
        "post-get",
        "post-comments",
    ]


@pytest.mark.asyncio
async def test_worker_dispatches_all_atomic_action_capabilities() -> None:
    runner = BlockingRunner()
    worker = CapabilityWorker(cast(CapabilityRunner, runner), queue_capacity=10)
    await worker.start()
    post_ref = "activity:7312345678901234567"

    outputs = (
        await worker.send_invitation(
            InvitationSendInput(
                context_id="context-1",
                request_id="invitation-send-1",
                profile_slug="jane-doe",
            )
        ),
        await worker.accept_invitation(
            InvitationAcceptInput(
                context_id="context-1",
                request_id="invitation-accept-1",
                profile_slug="jane-doe",
            )
        ),
        await worker.ignore_invitation(
            InvitationIgnoreInput(
                context_id="context-1",
                request_id="invitation-ignore-1",
                profile_slug="jane-doe",
            )
        ),
        await worker.send_message(
            MessageSendInput(
                context_id="context-1",
                request_id="message-send-1",
                profile_slug="jane-doe",
                message="Exact queued message.",
            )
        ),
        await worker.create_post(
            PostCreateInput(
                context_id="context-1",
                request_id="post-create-1",
                content=TextPostContent(text="Exact queued post."),
            )
        ),
        await worker.comment_on_post(
            PostCommentInput(
                context_id="context-1",
                request_id="post-comment-1",
                post_ref=post_ref,
                text="Exact queued comment.",
            )
        ),
        await worker.react_to_post(
            PostReactionInput(
                context_id="context-1",
                request_id="post-react-1",
                post_ref=post_ref,
                desired_reaction=ReactionState.LOVE,
            )
        ),
    )
    await worker.close()

    assert tuple(output.result.action_type for output in outputs) == (
        ActionType.INVITATION_SEND,
        ActionType.INVITATION_ACCEPT,
        ActionType.INVITATION_IGNORE,
        ActionType.MESSAGE_SEND,
        ActionType.POST_CREATE,
        ActionType.COMMENT_CREATE,
        ActionType.REACTION_SET,
    )
    assert runner.extension_calls == [
        "invitation-send",
        "invitation-accept",
        "invitation-ignore",
        "message-send",
        "post-create",
        "post-comment",
        "post-react",
    ]


@pytest.mark.asyncio
async def test_worker_does_not_coalesce_repeated_action_requests() -> None:
    runner = BlockingRunner()
    worker = CapabilityWorker(cast(CapabilityRunner, runner), queue_capacity=10)
    await worker.start()
    request = PostCommentInput(
        context_id="context-1",
        request_id="post-comment-repeat",
        post_ref="activity:7312345678901234567",
        text="Exact queued comment.",
    )

    await worker.comment_on_post(request)
    await worker.comment_on_post(request)
    await worker.close()

    assert runner.extension_calls == ["post-comment", "post-comment"]


@pytest.mark.asyncio
async def test_worker_requires_started_local_runtime() -> None:
    worker = CapabilityWorker(
        cast(CapabilityRunner, BlockingRunner()),
        queue_capacity=1,
    )
    request = JobSearchInput(
        context_id="context-1",
        request_id="request-1",
        query="python",
    )

    with pytest.raises(BrowserUnavailableError, match="not running"):
        await worker.search_jobs(request)

    await worker.close()


@pytest.mark.asyncio
async def test_worker_dispatches_people_search_and_profile_read() -> None:
    runner = BlockingRunner()
    worker = CapabilityWorker(cast(CapabilityRunner, runner), queue_capacity=2)
    await worker.start()

    search = await worker.search_people(
        PeopleSearchInput(
            context_id="context-1",
            request_id="people-search-1",
            query="python",
        )
    )
    network_search = await worker.search_connections(
        ConnectionsSearchInput(
            context_id="context-1",
            request_id="connections-search-1",
            filters=ConnectionsSearchFilters(title="Staff Engineer"),
        )
    )
    profile = await worker.get_person(
        PeopleGetInput(
            context_id="context-1",
            request_id="person-get-1",
            profile_slug="jane-doe",
        )
    )
    await worker.close()

    assert search.request_id == "people-search-1"
    assert network_search.request_id == "connections-search-1"
    assert profile.person.profile_slug == "jane-doe"
    assert runner.people_calls == ["search", "connections-search", "get"]


@pytest.mark.asyncio
async def test_worker_dispatches_company_search_and_profile_read() -> None:
    runner = BlockingRunner()
    worker = CapabilityWorker(cast(CapabilityRunner, runner), queue_capacity=2)
    await worker.start()

    search = await worker.search_companies(
        CompanySearchInput(
            context_id="context-1",
            request_id="company-search-1",
            query="cloud",
        )
    )
    profile = await worker.get_company(
        CompanyGetInput(
            context_id="context-1",
            request_id="company-get-1",
            company_slug="acme-cloud",
        )
    )
    await worker.close()

    assert search.request_id == "company-search-1"
    assert profile.company.company_slug == "acme-cloud"
    assert runner.company_calls == ["search", "get"]


@pytest.mark.asyncio
async def test_worker_shutdown_unblocks_a_submitter_waiting_on_a_full_queue() -> None:
    runner = BlockingRunner()
    worker = CapabilityWorker(cast(CapabilityRunner, runner), queue_capacity=1)
    await worker.start()
    requests = [
        JobSearchInput(
            context_id="context-1",
            request_id=f"request-{index}",
            query=f"query-{index}",
        )
        for index in range(3)
    ]

    calls = [asyncio.create_task(worker.search_jobs(requests[0]))]
    await runner.started.wait()
    calls.append(asyncio.create_task(worker.search_jobs(requests[1])))
    await _wait_for_queue_depth(worker, 1)
    calls.append(asyncio.create_task(worker.search_jobs(requests[2])))
    await asyncio.sleep(0)

    await asyncio.wait_for(worker.close(), timeout=1)
    results = await asyncio.gather(*calls, return_exceptions=True)

    assert all(isinstance(result, BrowserUnavailableError) for result in results)
    assert worker.queue_depth == 0
    assert worker.running is False


@pytest.mark.asyncio
async def test_worker_quiesce_rejects_queued_work_but_finishes_active_operation() -> None:
    runner = BlockingRunner()
    worker = CapabilityWorker(cast(CapabilityRunner, runner), queue_capacity=2)
    await worker.start()
    first_request = JobSearchInput(
        context_id="graceful-stop",
        request_id="active",
        query="active",
    )
    queued_request = JobSearchInput(
        context_id="graceful-stop",
        request_id="queued",
        query="queued",
    )

    active = asyncio.create_task(worker.search_jobs(first_request))
    await runner.started.wait()
    queued = asyncio.create_task(worker.search_jobs(queued_request))
    await _wait_for_queue_depth(worker, 1)

    quiescing = asyncio.create_task(worker.quiesce())
    await _wait_for_queue_depth(worker, 0)
    assert quiescing.done() is False
    with pytest.raises(BrowserUnavailableError, match="not running"):
        await worker.search_jobs(
            JobSearchInput(
                context_id="graceful-stop",
                request_id="new",
                query="new",
            )
        )

    runner.release.set()
    active_result = await active
    with pytest.raises(BrowserUnavailableError, match="shutting down"):
        await queued
    await quiescing
    await worker.close()

    assert active_result.request_id == "active"
    assert runner.search_queries == ["active"]
    assert worker.running is False


@pytest.mark.asyncio
async def test_cancelled_caller_does_not_duplicate_already_queued_work() -> None:
    runner = BlockingRunner()
    worker = CapabilityWorker(cast(CapabilityRunner, runner), queue_capacity=2)
    await worker.start()
    first_request = JobSearchInput(
        context_id="context-1",
        request_id="request-first",
        query="first",
    )
    queued_request = JobSearchInput(
        context_id="context-1",
        request_id="request-queued",
        query="queued",
    )

    first = asyncio.create_task(worker.search_jobs(first_request))
    await runner.started.wait()
    abandoned = asyncio.create_task(worker.search_jobs(queued_request))
    await _wait_for_queue_depth(worker, 1)
    abandoned.cancel()
    with pytest.raises(asyncio.CancelledError):
        await abandoned

    retry = asyncio.create_task(worker.search_jobs(queued_request))
    await asyncio.sleep(0)
    runner.release.set()
    first_result, retry_result = await asyncio.gather(first, retry)
    await worker.close()

    assert first_result.request_id == "request-first"
    assert retry_result.request_id == "request-queued"
    assert runner.search_queries == ["first", "queued"]


@pytest.mark.asyncio
async def test_last_cancelled_waiter_removes_queued_read_before_execution() -> None:
    runner = BlockingRunner()
    worker = CapabilityWorker(cast(CapabilityRunner, runner), queue_capacity=2)
    await worker.start()
    active = asyncio.create_task(
        worker.search_jobs(
            JobSearchInput(
                context_id="cancellation",
                request_id="active",
                query="active",
            )
        )
    )
    await runner.started.wait()
    queued = asyncio.create_task(
        worker.search_jobs(
            JobSearchInput(
                context_id="cancellation",
                request_id="queued",
                query="must-not-run",
            )
        )
    )
    await _wait_for_queue_depth(worker, 1)

    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued
    await _wait_for_queue_depth(worker, 0)
    runner.release.set()
    await active
    await worker.close()

    assert runner.search_queries == ["active"]


@pytest.mark.asyncio
async def test_active_read_cancellation_releases_the_single_execution_lane() -> None:
    runner = BlockingRunner()
    worker = CapabilityWorker(cast(CapabilityRunner, runner), queue_capacity=2)
    await worker.start()
    first = asyncio.create_task(
        worker.search_jobs(
            JobSearchInput(
                context_id="active-cancel",
                request_id="first",
                query="first",
            )
        )
    )
    await runner.started.wait()

    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = await asyncio.wait_for(
        worker.search_jobs(
            JobSearchInput(
                context_id="active-cancel",
                request_id="second",
                query="second",
            )
        ),
        timeout=1,
    )
    await worker.close()

    assert second.request_id == "second"
    assert runner.search_queries == ["first", "second"]


@pytest.mark.asyncio
async def test_active_action_survives_caller_cancellation_until_terminal_result() -> None:
    runner = BlockingActionRunner()
    worker = CapabilityWorker(cast(CapabilityRunner, runner), queue_capacity=2)
    await worker.start()
    request = PostCommentInput(
        context_id="write-cancel",
        request_id="comment",
        post_ref="activity:7312345678901234567",
        text="Exact comment",
    )

    caller = asyncio.create_task(worker.comment_on_post(request))
    await runner.write_started.wait()
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert runner.write_completed.is_set() is False

    runner.write_release.set()
    await asyncio.wait_for(runner.write_completed.wait(), timeout=1)
    await worker.close()

    assert runner.write_calls == 1


@pytest.mark.asyncio
async def test_cursor_is_reserved_before_waiting_and_survives_queue_delay() -> None:
    now = [datetime(2026, 8, 4, tzinfo=UTC)]
    pagination = PaginationManager(
        ttl_seconds=60,
        max_active_cursors=10,
        max_seen_items_per_cursor=100,
        clock=lambda: now[0],
    )
    seed = JobSearchInput(
        context_id="cursor-queue",
        request_id="seed",
        query="cursor-query",
        page_size=1,
    )
    seed_lease = await pagination.acquire(
        account_id="personal",
        client_id="cursor-client",
        capability_name=CapabilityName.JOBS_SEARCH,
        request=seed,
    )
    metadata = await pagination.advance(
        seed_lease,
        page_size=1,
        returned_keys=("job-1",),
        provider_has_more=True,
    )
    assert metadata.next_cursor is not None

    runner = BlockingRunner()
    worker = CapabilityWorker(
        cast(CapabilityRunner, runner),
        queue_capacity=2,
        pagination=pagination,
        account_id="personal",
    )
    await worker.start()
    blocker = asyncio.create_task(
        _search_as(
            worker,
            "blocker-client",
            JobSearchInput(
                context_id="cursor-queue",
                request_id="blocker",
                query="blocker",
            ),
        )
    )
    await runner.started.wait()
    continuation = asyncio.create_task(
        _search_as(
            worker,
            "cursor-client",
            seed.model_copy(
                update={
                    "request_id": "continuation",
                    "cursor": metadata.next_cursor,
                }
            ),
        )
    )
    await _wait_for_queue_depth(worker, 1)
    now[0] += timedelta(minutes=5)

    runner.release.set()
    _, continuation_result = await asyncio.gather(blocker, continuation)
    await worker.close()

    assert continuation_result.request_id == "continuation"


def _invalid_output_invocations() -> tuple[Callable[[CapabilityWorker], Awaitable[object]], ...]:
    post_ref = "activity:7312345678901234567"
    return (
        lambda worker: worker.search_jobs(
            JobSearchInput(
                context_id="invalid-output",
                request_id="jobs-search",
                query="python",
            )
        ),
        lambda worker: worker.get_job(
            JobDetailInput(
                context_id="invalid-output",
                request_id="job-get",
                job_id="4100000001",
            )
        ),
        lambda worker: worker.search_people(
            PeopleSearchInput(
                context_id="invalid-output",
                request_id="people-search",
                query="python",
            )
        ),
        lambda worker: worker.search_connections(
            ConnectionsSearchInput(
                context_id="invalid-output",
                request_id="connections-search",
                filters=ConnectionsSearchFilters(title="Staff Engineer"),
            )
        ),
        lambda worker: worker.get_person(
            PeopleGetInput(
                context_id="invalid-output",
                request_id="people-get",
                profile_slug="jane-doe",
            )
        ),
        lambda worker: worker.search_companies(
            CompanySearchInput(
                context_id="invalid-output",
                request_id="companies-search",
                query="cloud",
            )
        ),
        lambda worker: worker.get_company(
            CompanyGetInput(
                context_id="invalid-output",
                request_id="company-get",
                company_slug="acme-cloud",
            )
        ),
        lambda worker: worker.search_posts(
            PostSearchInput(
                context_id="invalid-output",
                request_id="posts-search",
                query="python",
            )
        ),
        lambda worker: worker.get_post(
            PostGetInput(
                context_id="invalid-output",
                request_id="post-get",
                post_ref=post_ref,
            )
        ),
        lambda worker: worker.list_post_comments(
            PostCommentsListInput(
                context_id="invalid-output",
                request_id="comments-list",
                post_ref=post_ref,
            )
        ),
        lambda worker: worker.list_invitations(
            InvitationListInput(
                context_id="invalid-output",
                request_id="invitations-list",
            )
        ),
        lambda worker: worker.list_connections(
            ConnectionsListInput(
                context_id="invalid-output",
                request_id="connections-list",
            )
        ),
        lambda worker: worker.search_messages(
            ConversationSearchInput(
                context_id="invalid-output",
                request_id="conversations-list",
                query="invalid",
            )
        ),
        lambda worker: worker.get_conversation(
            ConversationGetInput(
                context_id="invalid-output",
                request_id="conversation-get",
                conversation_id="thread-123",
            )
        ),
        lambda worker: worker.send_invitation(
            InvitationSendInput(
                context_id="invalid-output",
                request_id="invitation-send",
                profile_slug="jane-doe",
            )
        ),
        lambda worker: worker.accept_invitation(
            InvitationAcceptInput(
                context_id="invalid-output",
                request_id="invitation-accept",
                profile_slug="jane-doe",
            )
        ),
        lambda worker: worker.ignore_invitation(
            InvitationIgnoreInput(
                context_id="invalid-output",
                request_id="invitation-ignore",
                profile_slug="jane-doe",
            )
        ),
        lambda worker: worker.send_message(
            MessageSendInput(
                context_id="invalid-output",
                request_id="message-send",
                conversation_id="thread-123",
                message="Synthetic message.",
            )
        ),
        lambda worker: worker.create_post(
            PostCreateInput(
                context_id="invalid-output",
                request_id="post-create",
                content=TextPostContent(text="Synthetic post."),
            )
        ),
        lambda worker: worker.comment_on_post(
            PostCommentInput(
                context_id="invalid-output",
                request_id="post-comment",
                post_ref=post_ref,
                text="Synthetic comment.",
            )
        ),
        lambda worker: worker.react_to_post(
            PostReactionInput(
                context_id="invalid-output",
                request_id="post-react",
                post_ref=post_ref,
                desired_reaction=ReactionState.LIKE,
            )
        ),
    )


@pytest.mark.asyncio
async def test_every_worker_adapter_rejects_an_invalid_runner_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def invalid_submit(*_: object, **__: object) -> object:
        return object()

    monkeypatch.setattr(CapabilityWorker, "_submit", invalid_submit)
    worker = CapabilityWorker(cast(CapabilityRunner, BlockingRunner()), queue_capacity=1)

    for invoke in _invalid_output_invocations():
        with pytest.raises(RuntimeError, match="invalid"):
            await invoke(worker)
