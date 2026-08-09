"""Idempotent execution of registered LinkedIn capabilities."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

import structlog

from linkedin_mcp.application.client_context import (
    current_client_id,
    current_execution_context,
)
from linkedin_mcp.application.pagination import (
    PaginationLease,
    PaginationManager,
    request_binding,
    select_page,
)
from linkedin_mcp.capabilities import CapabilityRegistry
from linkedin_mcp.config import Settings
from linkedin_mcp.domain.evidence import (
    canonical_action_payload_hash,
    canonical_input_fingerprint,
    source_from_action_execution,
    source_from_action_preparation,
    source_from_company_search,
    source_from_connections,
    source_from_conversation,
    source_from_conversation_search,
    source_from_invitation_list,
    source_from_job_detail,
    source_from_job_search,
    source_from_people_search,
    source_from_post,
    source_from_post_comments,
    source_from_post_search,
    sources_from_company_profile,
    sources_from_person_profile,
)
from linkedin_mcp.domain.models import (
    ActionDraft,
    ActionExecuteInput,
    ActionExecuteOutput,
    ActionExecutionResult,
    ActionOutcome,
    ActionPageResult,
    ActionPayload,
    ActionPreparationCapture,
    ActionPrepareOutput,
    ActionStatus,
    ActionType,
    CapabilityName,
    CommentCreatePayload,
    CommentThread,
    CompanyGetInput,
    CompanyGetOutput,
    CompanyProfileObservation,
    CompanyProfilePageCapture,
    CompanySearchCoverage,
    CompanySearchInput,
    CompanySearchOutput,
    CompanySummary,
    ConnectionsListCoverage,
    ConnectionsListInput,
    ConnectionsListOutput,
    ConnectionsSearchInput,
    ConnectionsSearchOutput,
    ConnectionSummary,
    ConversationGetInput,
    ConversationGetOutput,
    ConversationObservation,
    ConversationSearchCoverage,
    ConversationSearchInput,
    ConversationSearchOutput,
    ConversationSummary,
    InvitationAcceptPayload,
    InvitationAcceptPrepareInput,
    InvitationIgnorePayload,
    InvitationIgnorePrepareInput,
    InvitationListCoverage,
    InvitationListInput,
    InvitationListOutput,
    InvitationSendPayload,
    InvitationSendPrepareInput,
    InvitationSummary,
    JobDetailInput,
    JobDetailObservation,
    JobDetailOutput,
    JobSearchCoverage,
    JobSearchInput,
    JobSearchOutput,
    JobSummary,
    MessagePrepareInput,
    MessageSendPayload,
    PaginatedInput,
    PeopleGetInput,
    PeopleGetOutput,
    PeopleSearchCoverage,
    PeopleSearchInput,
    PeopleSearchOutput,
    PersonConnectionDegree,
    PersonProfileObservation,
    PersonProfilePageCapture,
    PersonSummary,
    PostCommentPrepareInput,
    PostCommentsCoverage,
    PostCommentsListInput,
    PostCommentsListOutput,
    PostCreatePayload,
    PostCreatePrepareInput,
    PostGetInput,
    PostGetOutput,
    PostObservation,
    PostReactionPrepareInput,
    PostSearchCoverage,
    PostSearchInput,
    PostSearchOutput,
    PostSummary,
    PreparedPostAsset,
    ReactionSetPayload,
    StopReason,
    StrictModel,
    action_approval_preview,
)
from linkedin_mcp.errors import (
    BrowserUnavailableError,
    ErrorCode,
    IdempotencyConflictError,
    InternalServerError,
    LinkedInMCPError,
    ParserDriftError,
)
from linkedin_mcp.persistence.contracts import (
    ActionAttemptStart,
    CallStart,
    CallStatus,
    Repository,
)
from linkedin_mcp.policy import AuthorizationPolicy

logger = structlog.get_logger(__name__)
ProgressReporter = Callable[[int, int, str], Awaitable[None]]


class JobSearchProvider(Protocol):
    async def collect(
        self,
        request: JobSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[JobSummary, ...], JobSearchCoverage, str, str]: ...


class JobDetailProvider(Protocol):
    async def read(self, request: JobDetailInput) -> JobDetailObservation: ...


class PeopleSearchProvider(Protocol):
    async def collect(
        self,
        request: PeopleSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[PersonSummary, ...], PeopleSearchCoverage, str, str]: ...


class PersonProfileProvider(Protocol):
    async def read(
        self,
        request: PeopleGetInput,
    ) -> tuple[PersonProfileObservation, tuple[PersonProfilePageCapture, ...]]: ...


class CompanySearchProvider(Protocol):
    async def collect(
        self,
        request: CompanySearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[CompanySummary, ...], CompanySearchCoverage, str, str]: ...


class CompanyProfileProvider(Protocol):
    async def read(
        self,
        request: CompanyGetInput,
    ) -> tuple[CompanyProfileObservation, tuple[CompanyProfilePageCapture, ...]]: ...


class PostSearchProvider(Protocol):
    async def collect(
        self,
        request: PostSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[PostSummary, ...], PostSearchCoverage, str, str]: ...


class PostDetailProvider(Protocol):
    async def read(self, request: PostGetInput) -> PostObservation: ...


class PostCommentsProvider(Protocol):
    async def collect(
        self,
        request: PostCommentsListInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[CommentThread, ...], PostCommentsCoverage, str, str]: ...


class PostPublishingProvider(Protocol):
    async def prepare_assets(
        self,
        request: PostCreatePrepareInput,
    ) -> tuple[PreparedPostAsset, ...]: ...

    async def prepare_post(
        self,
        request: PostCreatePrepareInput,
    ) -> ActionPreparationCapture: ...

    async def execute_post(self, draft: ActionDraft) -> ActionPageResult: ...


class PostEngagementProvider(Protocol):
    async def prepare_comment_assets(
        self,
        request: PostCommentPrepareInput,
    ) -> tuple[PreparedPostAsset, ...]: ...

    async def prepare_comment(
        self,
        request: PostCommentPrepareInput,
    ) -> ActionPreparationCapture: ...

    async def execute_comment(self, draft: ActionDraft) -> ActionPageResult: ...

    async def prepare_reaction(
        self,
        request: PostReactionPrepareInput,
    ) -> ActionPreparationCapture: ...

    async def execute_reaction(self, draft: ActionDraft) -> ActionPageResult: ...


class InvitationListProvider(Protocol):
    async def collect(
        self,
        request: InvitationListInput,
        *,
        result_limit: int | None = None,
        progress: ProgressReporter | None = None,
    ) -> tuple[
        tuple[InvitationSummary, ...],
        InvitationListCoverage,
        str,
        str,
    ]: ...


class ConnectionsListProvider(Protocol):
    async def collect(
        self,
        request: ConnectionsListInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[
        tuple[ConnectionSummary, ...],
        ConnectionsListCoverage,
        str,
        str,
    ]: ...


class InvitationActionProvider(Protocol):
    async def prepare_send(
        self,
        request: InvitationSendPrepareInput,
    ) -> ActionPreparationCapture: ...

    async def prepare_accept(
        self,
        request: InvitationAcceptPrepareInput,
    ) -> ActionPreparationCapture: ...

    async def prepare_ignore(
        self,
        request: InvitationIgnorePrepareInput,
    ) -> ActionPreparationCapture: ...

    async def execute_send(self, draft: ActionDraft) -> ActionPageResult: ...

    async def execute_accept(self, draft: ActionDraft) -> ActionPageResult: ...

    async def execute_ignore(self, draft: ActionDraft) -> ActionPageResult: ...


class ConversationSearchProvider(Protocol):
    async def collect(
        self,
        request: ConversationSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[
        tuple[ConversationSummary, ...],
        ConversationSearchCoverage,
        str,
        str,
    ]: ...


class ConversationProvider(Protocol):
    async def read(self, request: ConversationGetInput) -> ConversationObservation: ...

    async def prepare_message(
        self,
        request: MessagePrepareInput,
    ) -> ActionPreparationCapture: ...

    async def prepare_message_assets(
        self,
        request: MessagePrepareInput,
    ) -> tuple[PreparedPostAsset, ...]: ...

    async def execute_message(self, draft: ActionDraft) -> ActionPageResult: ...


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


class CapabilityExecutor:
    def __init__(
        self,
        *,
        settings: Settings,
        registry: CapabilityRegistry,
        repository: Repository,
        job_search: JobSearchProvider,
        job_detail: JobDetailProvider,
        people_search: PeopleSearchProvider,
        person_profile: PersonProfileProvider,
        company_search: CompanySearchProvider,
        company_profile: CompanyProfileProvider,
        post_search: PostSearchProvider,
        post_detail: PostDetailProvider,
        post_comments: PostCommentsProvider,
        post_publishing: PostPublishingProvider,
        post_engagement: PostEngagementProvider,
        invitation_list: InvitationListProvider,
        connections_list: ConnectionsListProvider,
        invitation_actions: InvitationActionProvider,
        conversation_search: ConversationSearchProvider,
        conversation: ConversationProvider,
        pagination: PaginationManager | None = None,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._repository = repository
        self._job_search = job_search
        self._job_detail = job_detail
        self._people_search = people_search
        self._person_profile = person_profile
        self._company_search = company_search
        self._company_profile = company_profile
        self._post_search = post_search
        self._post_detail = post_detail
        self._post_comments = post_comments
        self._post_publishing = post_publishing
        self._post_engagement = post_engagement
        self._invitation_list = invitation_list
        self._connections_list = connections_list
        self._invitation_actions = invitation_actions
        self._conversation_search = conversation_search
        self._conversation = conversation
        self._pagination = pagination or PaginationManager(
            ttl_seconds=settings.pagination_cursor_ttl_seconds,
            max_active_cursors=settings.pagination_max_active_cursors,
            max_seen_items_per_cursor=settings.pagination_max_seen_items_per_cursor,
        )
        self._authorization = AuthorizationPolicy(settings)

    async def close(self) -> None:
        await self._pagination.close()

    async def search_jobs(self, request: JobSearchInput) -> JobSearchOutput:
        descriptor = self._registry.get(CapabilityName.JOBS_SEARCH)
        self._authorization.authorize(descriptor)
        call = await self._begin_call(descriptor.name, request)
        replay = self._replayed_output(call, JobSearchOutput)
        if replay is not None:
            return replay
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(descriptor.name, request)
            jobs, coverage, captured_text, source_url = await self._job_search.collect(
                request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
            )
            page = select_page(
                jobs,
                key=lambda job: job.job_id,
                seen_keys=lease.seen_keys,
                page_size=self._pagination.page_capacity(lease, request.page_size),
            )
            provider_has_more = page.has_lookahead or coverage.stop_reason in {
                StopReason.RESULT_LIMIT,
                StopReason.SAFETY_BOUND,
            }
            page_coverage = coverage.model_copy(
                update={
                    "result_count": len(page.items),
                    "max_results": request.page_size,
                    "stop_reason": (
                        StopReason.RESULT_LIMIT if provider_has_more else coverage.stop_reason
                    ),
                }
            )
            source = source_from_job_search(
                source_url=source_url,
                captured_text=captured_text,
                jobs=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
            )
            output = JobSearchOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                jobs=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source.reference(),),
            )
            await self._repository.complete_call(
                call_id=call.call_id,
                output=output.model_dump(mode="json"),
                sources=(source,),
            )
            return output
        except asyncio.CancelledError:
            await self._record_failure(
                call.call_id,
                BrowserUnavailableError("The LinkedIn job search was interrupted."),
            )
            raise
        except Exception as error:
            await self._record_failure(call.call_id, error)
            raise
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def get_job(self, request: JobDetailInput) -> JobDetailOutput:
        descriptor = self._registry.get(CapabilityName.JOBS_GET)
        self._authorization.authorize(descriptor)
        call = await self._begin_call(descriptor.name, request)
        replay = self._replayed_output(call, JobDetailOutput)
        if replay is not None:
            return replay
        try:
            job = await self._job_detail.read(request)
            source = source_from_job_detail(job)
            output = JobDetailOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                job=job,
                sources=(source.reference(),),
            )
            await self._repository.complete_call(
                call_id=call.call_id,
                output=output.model_dump(mode="json"),
                sources=(source,),
            )
            return output
        except asyncio.CancelledError:
            await self._record_failure(
                call.call_id,
                BrowserUnavailableError("The LinkedIn job read was interrupted."),
            )
            raise
        except Exception as error:
            await self._record_failure(call.call_id, error)
            raise

    async def search_people(self, request: PeopleSearchInput) -> PeopleSearchOutput:
        descriptor = self._registry.get(CapabilityName.PEOPLE_SEARCH)
        self._authorization.authorize(descriptor)
        call = await self._begin_call(descriptor.name, request)
        replay = self._replayed_output(call, PeopleSearchOutput)
        if replay is not None:
            return replay
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(descriptor.name, request)
            people, coverage, captured_text, source_url = await self._people_search.collect(
                request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
            )
            page = select_page(
                people,
                key=lambda person: person.profile_slug,
                seen_keys=lease.seen_keys,
                page_size=self._pagination.page_capacity(lease, request.page_size),
            )
            provider_has_more = page.has_lookahead or coverage.stop_reason in {
                StopReason.RESULT_LIMIT,
                StopReason.SAFETY_BOUND,
            }
            page_coverage = coverage.model_copy(
                update={
                    "result_count": len(page.items),
                    "max_results": request.page_size,
                    "stop_reason": (
                        StopReason.RESULT_LIMIT if provider_has_more else coverage.stop_reason
                    ),
                }
            )
            source = source_from_people_search(
                source_url=source_url,
                captured_text=captured_text,
                people=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
            )
            output = PeopleSearchOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                people=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source.reference(),),
            )
            await self._repository.complete_call(
                call_id=call.call_id,
                output=output.model_dump(mode="json"),
                sources=(source,),
            )
            return output
        except asyncio.CancelledError:
            await self._record_failure(
                call.call_id,
                BrowserUnavailableError("The LinkedIn People search was interrupted."),
            )
            raise
        except Exception as error:
            await self._record_failure(call.call_id, error)
            raise
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def search_connections(
        self,
        request: ConnectionsSearchInput,
    ) -> ConnectionsSearchOutput:
        descriptor = self._registry.get(CapabilityName.CONNECTIONS_SEARCH)
        self._authorization.authorize(descriptor)
        call = await self._begin_call(descriptor.name, request)
        replay = self._replayed_output(call, ConnectionsSearchOutput)
        if replay is not None:
            return replay
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(descriptor.name, request)
            people_request = request.as_people_search_input()
            people, coverage, captured_text, source_url = await self._people_search.collect(
                people_request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
            )
            if any(
                person.connection_degree is not PersonConnectionDegree.FIRST for person in people
            ):
                raise ParserDriftError(
                    "LinkedIn Connections search returned a result that was not visibly "
                    "first-degree."
                )
            page = select_page(
                people,
                key=lambda person: person.profile_slug,
                seen_keys=lease.seen_keys,
                page_size=self._pagination.page_capacity(lease, request.page_size),
            )
            provider_has_more = page.has_lookahead or coverage.stop_reason in {
                StopReason.RESULT_LIMIT,
                StopReason.SAFETY_BOUND,
            }
            page_coverage = coverage.model_copy(
                update={
                    "result_count": len(page.items),
                    "max_results": request.page_size,
                    "stop_reason": (
                        StopReason.RESULT_LIMIT if provider_has_more else coverage.stop_reason
                    ),
                }
            )
            source = source_from_people_search(
                source_url=source_url,
                captured_text=captured_text,
                people=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
            )
            output = ConnectionsSearchOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                people=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source.reference(),),
            )
            await self._repository.complete_call(
                call_id=call.call_id,
                output=output.model_dump(mode="json"),
                sources=(source,),
            )
            return output
        except asyncio.CancelledError:
            await self._record_failure(
                call.call_id,
                BrowserUnavailableError("The LinkedIn Connections search was interrupted."),
            )
            raise
        except Exception as error:
            await self._record_failure(call.call_id, error)
            raise
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def get_person(self, request: PeopleGetInput) -> PeopleGetOutput:
        descriptor = self._registry.get(CapabilityName.PEOPLE_GET)
        self._authorization.authorize(descriptor)
        call = await self._begin_call(descriptor.name, request)
        replay = self._replayed_output(call, PeopleGetOutput)
        if replay is not None:
            return replay
        try:
            person, captures = await self._person_profile.read(request)
            sources = sources_from_person_profile(person, captures)
            output = PeopleGetOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                person=person,
                sources=tuple(source.reference() for source in sources),
            )
            await self._repository.complete_call(
                call_id=call.call_id,
                output=output.model_dump(mode="json"),
                sources=sources,
            )
            return output
        except asyncio.CancelledError:
            await self._record_failure(
                call.call_id,
                BrowserUnavailableError("The LinkedIn member-profile read was interrupted."),
            )
            raise
        except Exception as error:
            await self._record_failure(call.call_id, error)
            raise

    async def search_companies(self, request: CompanySearchInput) -> CompanySearchOutput:
        descriptor = self._registry.get(CapabilityName.COMPANIES_SEARCH)
        self._authorization.authorize(descriptor)
        call = await self._begin_call(descriptor.name, request)
        replay = self._replayed_output(call, CompanySearchOutput)
        if replay is not None:
            return replay
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(descriptor.name, request)
            companies, coverage, captured_text, source_url = await self._company_search.collect(
                request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
            )
            page = select_page(
                companies,
                key=lambda company: company.company_slug,
                seen_keys=lease.seen_keys,
                page_size=self._pagination.page_capacity(lease, request.page_size),
            )
            provider_has_more = page.has_lookahead or coverage.stop_reason in {
                StopReason.RESULT_LIMIT,
                StopReason.SAFETY_BOUND,
            }
            page_coverage = coverage.model_copy(
                update={
                    "result_count": len(page.items),
                    "max_results": request.page_size,
                    "stop_reason": (
                        StopReason.RESULT_LIMIT if provider_has_more else coverage.stop_reason
                    ),
                }
            )
            source = source_from_company_search(
                source_url=source_url,
                captured_text=captured_text,
                companies=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
            )
            output = CompanySearchOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                companies=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source.reference(),),
            )
            await self._repository.complete_call(
                call_id=call.call_id,
                output=output.model_dump(mode="json"),
                sources=(source,),
            )
            return output
        except asyncio.CancelledError:
            await self._record_failure(
                call.call_id,
                BrowserUnavailableError("The LinkedIn Company search was interrupted."),
            )
            raise
        except Exception as error:
            await self._record_failure(call.call_id, error)
            raise
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def get_company(self, request: CompanyGetInput) -> CompanyGetOutput:
        descriptor = self._registry.get(CapabilityName.COMPANIES_GET)
        self._authorization.authorize(descriptor)
        call = await self._begin_call(descriptor.name, request)
        replay = self._replayed_output(call, CompanyGetOutput)
        if replay is not None:
            return replay
        try:
            company, captures = await self._company_profile.read(request)
            sources = sources_from_company_profile(company, captures)
            output = CompanyGetOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                company=company,
                sources=tuple(source.reference() for source in sources),
            )
            await self._repository.complete_call(
                call_id=call.call_id,
                output=output.model_dump(mode="json"),
                sources=sources,
            )
            return output
        except asyncio.CancelledError:
            await self._record_failure(
                call.call_id,
                BrowserUnavailableError("The LinkedIn company-profile read was interrupted."),
            )
            raise
        except Exception as error:
            await self._record_failure(call.call_id, error)
            raise

    async def search_posts(self, request: PostSearchInput) -> PostSearchOutput:
        descriptor = self._registry.get(CapabilityName.POSTS_SEARCH)
        self._authorization.authorize(descriptor)
        call = await self._begin_call(descriptor.name, request)
        replay = self._replayed_output(call, PostSearchOutput)
        if replay is not None:
            return replay
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(descriptor.name, request)
            posts, coverage, captured_text, source_url = await self._post_search.collect(
                request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
            )
            page = select_page(
                posts,
                key=lambda post: post.post_ref,
                seen_keys=lease.seen_keys,
                page_size=self._pagination.page_capacity(lease, request.page_size),
            )
            provider_has_more = page.has_lookahead or coverage.stop_reason in {
                StopReason.RESULT_LIMIT,
                StopReason.SAFETY_BOUND,
            }
            page_coverage = coverage.model_copy(
                update={
                    "result_count": len(page.items),
                    "max_results": request.page_size,
                    "stop_reason": (
                        StopReason.RESULT_LIMIT if provider_has_more else coverage.stop_reason
                    ),
                }
            )
            source = source_from_post_search(
                source_url=source_url,
                captured_text=captured_text,
                posts=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
            )
            output = PostSearchOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                posts=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source.reference(),),
            )
            await self._repository.complete_call(
                call_id=call.call_id,
                output=output.model_dump(mode="json"),
                sources=(source,),
            )
            return output
        except asyncio.CancelledError:
            await self._record_failure(
                call.call_id,
                BrowserUnavailableError("The LinkedIn post search was interrupted."),
            )
            raise
        except Exception as error:
            await self._record_failure(call.call_id, error)
            raise
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def get_post(self, request: PostGetInput) -> PostGetOutput:
        descriptor = self._registry.get(CapabilityName.POSTS_GET)
        self._authorization.authorize(descriptor)
        call = await self._begin_call(descriptor.name, request)
        replay = self._replayed_output(call, PostGetOutput)
        if replay is not None:
            return replay
        try:
            post = await self._post_detail.read(request)
            source = source_from_post(post)
            output = PostGetOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                post=post,
                sources=(source.reference(),),
            )
            await self._repository.complete_call(
                call_id=call.call_id,
                output=output.model_dump(mode="json"),
                sources=(source,),
            )
            return output
        except asyncio.CancelledError:
            await self._record_failure(
                call.call_id,
                BrowserUnavailableError("The LinkedIn post read was interrupted."),
            )
            raise
        except Exception as error:
            await self._record_failure(call.call_id, error)
            raise

    async def list_post_comments(
        self,
        request: PostCommentsListInput,
    ) -> PostCommentsListOutput:
        descriptor = self._registry.get(CapabilityName.POST_COMMENTS_LIST)
        self._authorization.authorize(descriptor)
        call = await self._begin_call(descriptor.name, request)
        replay = self._replayed_output(call, PostCommentsListOutput)
        if replay is not None:
            return replay
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(descriptor.name, request)
            threads, coverage, captured_text, source_url = await self._post_comments.collect(
                request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
            )
            page = select_page(
                threads,
                key=lambda thread: thread.comment.comment_ref,
                seen_keys=lease.seen_keys,
                page_size=self._pagination.page_capacity(lease, request.page_size),
            )
            provider_has_more = (
                page.has_lookahead or coverage.top_level_visible > coverage.top_level_returned
            )
            replies_returned = sum(len(thread.replies) for thread in page.items)
            page_coverage = coverage.model_copy(
                update={
                    "top_level_returned": len(page.items),
                    "replies_returned": replies_returned,
                    "max_comments": request.page_size,
                    "truncated": coverage.truncated or provider_has_more,
                }
            )
            source = source_from_post_comments(
                source_url=source_url,
                captured_text=captured_text,
                threads=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
                force_truncated=coverage.truncated and not provider_has_more,
            )
            output = PostCommentsListOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                threads=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source.reference(),),
            )
            await self._repository.complete_call(
                call_id=call.call_id,
                output=output.model_dump(mode="json"),
                sources=(source,),
            )
            return output
        except asyncio.CancelledError:
            await self._record_failure(
                call.call_id,
                BrowserUnavailableError("The LinkedIn post discussion read was interrupted."),
            )
            raise
        except Exception as error:
            await self._record_failure(call.call_id, error)
            raise
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def list_invitations(
        self,
        request: InvitationListInput,
        progress: ProgressReporter | None = None,
    ) -> InvitationListOutput:
        descriptor = self._registry.get(CapabilityName.INVITATIONS_LIST)
        self._authorization.authorize(descriptor)
        call = await self._begin_call(descriptor.name, request)
        replay = self._replayed_output(call, InvitationListOutput)
        if replay is not None:
            return replay
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(descriptor.name, request)
            invitations, coverage, captured_text, source_url = await self._invitation_list.collect(
                request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
                progress=progress,
            )
            page = select_page(
                invitations,
                key=lambda invitation: invitation.invitation_ref,
                seen_keys=lease.seen_keys,
                page_size=self._pagination.page_capacity(lease, request.page_size),
            )
            provider_has_more = page.has_lookahead or coverage.stop_reason in {
                StopReason.RESULT_LIMIT,
                StopReason.SAFETY_BOUND,
            }
            page_stop_reason = (
                StopReason.RESULT_LIMIT
                if page.has_lookahead or coverage.stop_reason is StopReason.RESULT_LIMIT
                else coverage.stop_reason
            )
            page_coverage = coverage.model_copy(
                update={
                    "result_count": len(page.items),
                    "max_results": request.page_size,
                    "stop_reason": page_stop_reason,
                }
            )
            advertised_label = captured_text.split("\n\n", maxsplit=1)[0].strip()
            page_text = "\n\n".join((advertised_label, *(item.visible_text for item in page.items)))
            source = source_from_invitation_list(
                source_url=source_url,
                captured_text=page_text,
                invitations=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
            )
            output = InvitationListOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                invitations=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source.reference(),),
            )
            await self._repository.complete_call(
                call_id=call.call_id,
                output=output.model_dump(mode="json"),
                sources=(source,),
            )
            return output
        except asyncio.CancelledError:
            await self._record_failure(
                call.call_id,
                BrowserUnavailableError("The LinkedIn invitation read was interrupted."),
            )
            raise
        except Exception as error:
            await self._record_failure(call.call_id, error)
            raise
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def list_connections(self, request: ConnectionsListInput) -> ConnectionsListOutput:
        descriptor = self._registry.get(CapabilityName.CONNECTIONS_LIST)
        self._authorization.authorize(descriptor)
        call = await self._begin_call(descriptor.name, request)
        replay = self._replayed_output(call, ConnectionsListOutput)
        if replay is not None:
            return replay
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(descriptor.name, request)
            connections, coverage, captured_text, source_url = await self._connections_list.collect(
                request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
            )
            page = select_page(
                connections,
                key=lambda connection: connection.profile_slug,
                seen_keys=lease.seen_keys,
                page_size=self._pagination.page_capacity(lease, request.page_size),
            )
            provider_has_more = page.has_lookahead or coverage.stop_reason in {
                StopReason.RESULT_LIMIT,
                StopReason.SAFETY_BOUND,
            }
            page_coverage = coverage.model_copy(
                update={
                    "result_count": len(page.items),
                    "max_results": request.page_size,
                    "stop_reason": (
                        StopReason.RESULT_LIMIT if provider_has_more else coverage.stop_reason
                    ),
                }
            )
            source = source_from_connections(
                source_url=source_url,
                captured_text=captured_text,
                connections=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
            )
            output = ConnectionsListOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                connections=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source.reference(),),
            )
            await self._repository.complete_call(
                call_id=call.call_id,
                output=output.model_dump(mode="json"),
                sources=(source,),
            )
            return output
        except asyncio.CancelledError:
            await self._record_failure(
                call.call_id,
                BrowserUnavailableError("The LinkedIn connections read was interrupted."),
            )
            raise
        except Exception as error:
            await self._record_failure(call.call_id, error)
            raise
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def search_messages(
        self,
        request: ConversationSearchInput,
    ) -> ConversationSearchOutput:
        descriptor = self._registry.get(CapabilityName.MESSAGING_SEARCH)
        self._authorization.authorize(descriptor)
        call = await self._begin_call(descriptor.name, request)
        replay = self._replayed_output(call, ConversationSearchOutput)
        if replay is not None:
            return replay
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(descriptor.name, request)
            (
                conversations,
                coverage,
                captured_text,
                source_url,
            ) = await self._conversation_search.collect(
                request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
            )
            page = select_page(
                conversations,
                key=lambda conversation: (
                    conversation.conversation_id or conversation.conversation_ref
                ),
                seen_keys=lease.seen_keys,
                page_size=self._pagination.page_capacity(lease, request.page_size),
            )
            provider_has_more = page.has_lookahead or coverage.stop_reason in {
                StopReason.RESULT_LIMIT,
                StopReason.SAFETY_BOUND,
            }
            page_coverage = coverage.model_copy(
                update={
                    "result_count": len(page.items),
                    "max_results": request.page_size,
                    "stop_reason": (
                        StopReason.RESULT_LIMIT if provider_has_more else coverage.stop_reason
                    ),
                }
            )
            source = source_from_conversation_search(
                source_url=source_url,
                captured_text=captured_text,
                conversations=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
            )
            output = ConversationSearchOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                conversations=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source.reference(),),
            )
            await self._repository.complete_call(
                call_id=call.call_id,
                output=output.model_dump(mode="json"),
                sources=(source,),
            )
            return output
        except asyncio.CancelledError:
            await self._record_failure(
                call.call_id,
                BrowserUnavailableError("The LinkedIn inbox read was interrupted."),
            )
            raise
        except Exception as error:
            await self._record_failure(call.call_id, error)
            raise
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def get_conversation(
        self,
        request: ConversationGetInput,
    ) -> ConversationGetOutput:
        descriptor = self._registry.get(CapabilityName.MESSAGING_CONVERSATION_GET)
        self._authorization.authorize(descriptor)
        call = await self._begin_call(descriptor.name, request)
        replay = self._replayed_output(call, ConversationGetOutput)
        if replay is not None:
            return replay
        try:
            observation = await self._conversation.read(request)
            source = source_from_conversation(observation)
            output = ConversationGetOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                conversation=observation,
                sources=(source.reference(),),
            )
            await self._repository.complete_call(
                call_id=call.call_id,
                output=output.model_dump(mode="json"),
                sources=(source,),
            )
            return output
        except asyncio.CancelledError:
            await self._record_failure(
                call.call_id,
                BrowserUnavailableError("The LinkedIn conversation read was interrupted."),
            )
            raise
        except Exception as error:
            await self._record_failure(call.call_id, error)
            raise

    async def prepare_invitation_send(
        self,
        request: InvitationSendPrepareInput,
    ) -> ActionPrepareOutput:
        return await self._prepare_action(
            capability_name=CapabilityName.INVITATION_SEND_PREPARE,
            request=request,
            action_type=ActionType.INVITATION_SEND,
            payload=InvitationSendPayload(note=request.note),
            prepare=lambda: self._invitation_actions.prepare_send(request),
        )

    async def prepare_invitation_accept(
        self,
        request: InvitationAcceptPrepareInput,
    ) -> ActionPrepareOutput:
        return await self._prepare_action(
            capability_name=CapabilityName.INVITATION_ACCEPT_PREPARE,
            request=request,
            action_type=ActionType.INVITATION_ACCEPT,
            payload_factory=lambda capture: InvitationAcceptPayload(
                invitation_ref=(
                    capture.target.invitation_ref or self._missing_invitation_reference()
                )
            ),
            prepare=lambda: self._invitation_actions.prepare_accept(request),
        )

    async def prepare_invitation_ignore(
        self,
        request: InvitationIgnorePrepareInput,
    ) -> ActionPrepareOutput:
        return await self._prepare_action(
            capability_name=CapabilityName.INVITATION_IGNORE_PREPARE,
            request=request,
            action_type=ActionType.INVITATION_IGNORE,
            payload_factory=lambda capture: InvitationIgnorePayload(
                invitation_ref=(
                    capture.target.invitation_ref or self._missing_invitation_reference()
                )
            ),
            prepare=lambda: self._invitation_actions.prepare_ignore(request),
        )

    async def prepare_message(self, request: MessagePrepareInput) -> ActionPrepareOutput:
        async def payload_factory(
            _: ActionPreparationCapture,
        ) -> ActionPayload:
            assets = await self._conversation.prepare_message_assets(request)
            return MessageSendPayload(
                message=request.message,
                attachment_refs=tuple(attachment.asset_ref for attachment in request.attachments),
                gif=request.gif,
                reply_to_message_ref=request.reply_to_message_ref,
                assets=assets,
            )

        return await self._prepare_action(
            capability_name=CapabilityName.MESSAGING_MESSAGE_PREPARE,
            request=request,
            action_type=ActionType.MESSAGE_SEND,
            async_payload_factory=payload_factory,
            prepare=lambda: self._conversation.prepare_message(request),
        )

    async def prepare_post_create(
        self,
        request: PostCreatePrepareInput,
    ) -> ActionPrepareOutput:
        async def payload_factory(
            _: ActionPreparationCapture,
        ) -> ActionPayload:
            assets = await self._post_publishing.prepare_assets(request)
            return PostCreatePayload(
                content=request.content,
                audience=request.audience,
                group_target=request.group_target,
                comment_control=request.comment_control,
                brand_partnership=request.brand_partnership,
                collaborators=request.collaborators,
                scheduled_at=request.scheduled_at,
                assets=assets,
            )

        return await self._prepare_action(
            capability_name=CapabilityName.POSTS_CREATE_PREPARE,
            request=request,
            action_type=ActionType.POST_CREATE,
            async_payload_factory=payload_factory,
            prepare=lambda: self._post_publishing.prepare_post(request),
        )

    async def prepare_post_comment(
        self,
        request: PostCommentPrepareInput,
    ) -> ActionPrepareOutput:
        async def payload_factory(
            _: ActionPreparationCapture,
        ) -> ActionPayload:
            assets = await self._post_engagement.prepare_comment_assets(request)
            return CommentCreatePayload(
                post_ref=request.post_ref,
                parent_comment_ref=request.parent_comment_ref,
                text=request.text,
                mentions=request.mentions,
                attachment=request.attachment,
                assets=assets,
            )

        return await self._prepare_action(
            capability_name=CapabilityName.POST_COMMENT_PREPARE,
            request=request,
            action_type=ActionType.COMMENT_CREATE,
            async_payload_factory=payload_factory,
            prepare=lambda: self._post_engagement.prepare_comment(request),
        )

    async def prepare_post_reaction(
        self,
        request: PostReactionPrepareInput,
    ) -> ActionPrepareOutput:
        def payload_factory(capture: ActionPreparationCapture) -> ActionPayload:
            if capture.existing_reaction is None:
                raise RuntimeError("Reaction preparation captured no visible reaction state.")
            return ReactionSetPayload(
                post_ref=request.post_ref,
                comment_ref=request.comment_ref,
                existing_reaction=capture.existing_reaction,
                desired_reaction=request.desired_reaction,
            )

        return await self._prepare_action(
            capability_name=CapabilityName.POST_REACTION_PREPARE,
            request=request,
            action_type=ActionType.REACTION_SET,
            payload_factory=payload_factory,
            prepare=lambda: self._post_engagement.prepare_reaction(request),
        )

    async def execute_invitation_send(
        self,
        request: ActionExecuteInput,
    ) -> ActionExecuteOutput:
        return await self._execute_action(
            capability_name=CapabilityName.INVITATION_SEND_EXECUTE,
            request=request,
            action_type=ActionType.INVITATION_SEND,
            execute=self._invitation_actions.execute_send,
        )

    async def execute_invitation_accept(
        self,
        request: ActionExecuteInput,
    ) -> ActionExecuteOutput:
        return await self._execute_action(
            capability_name=CapabilityName.INVITATION_ACCEPT_EXECUTE,
            request=request,
            action_type=ActionType.INVITATION_ACCEPT,
            execute=self._invitation_actions.execute_accept,
        )

    async def execute_invitation_ignore(
        self,
        request: ActionExecuteInput,
    ) -> ActionExecuteOutput:
        return await self._execute_action(
            capability_name=CapabilityName.INVITATION_IGNORE_EXECUTE,
            request=request,
            action_type=ActionType.INVITATION_IGNORE,
            execute=self._invitation_actions.execute_ignore,
        )

    async def execute_message(self, request: ActionExecuteInput) -> ActionExecuteOutput:
        return await self._execute_action(
            capability_name=CapabilityName.MESSAGING_MESSAGE_EXECUTE,
            request=request,
            action_type=ActionType.MESSAGE_SEND,
            execute=self._conversation.execute_message,
        )

    async def execute_post_create(
        self,
        request: ActionExecuteInput,
    ) -> ActionExecuteOutput:
        return await self._execute_action(
            capability_name=CapabilityName.POSTS_CREATE_EXECUTE,
            request=request,
            action_type=ActionType.POST_CREATE,
            execute=self._post_publishing.execute_post,
        )

    async def execute_post_comment(
        self,
        request: ActionExecuteInput,
    ) -> ActionExecuteOutput:
        return await self._execute_action(
            capability_name=CapabilityName.POST_COMMENT_EXECUTE,
            request=request,
            action_type=ActionType.COMMENT_CREATE,
            execute=self._post_engagement.execute_comment,
        )

    async def execute_post_reaction(
        self,
        request: ActionExecuteInput,
    ) -> ActionExecuteOutput:
        return await self._execute_action(
            capability_name=CapabilityName.POST_REACTION_EXECUTE,
            request=request,
            action_type=ActionType.REACTION_SET,
            execute=self._post_engagement.execute_reaction,
        )

    async def _prepare_action(
        self,
        *,
        capability_name: CapabilityName,
        request: (
            InvitationSendPrepareInput
            | InvitationAcceptPrepareInput
            | InvitationIgnorePrepareInput
            | MessagePrepareInput
            | PostCreatePrepareInput
            | PostCommentPrepareInput
            | PostReactionPrepareInput
        ),
        action_type: ActionType,
        prepare: Callable[[], Awaitable[ActionPreparationCapture]],
        payload: ActionPayload | None = None,
        payload_factory: Callable[[ActionPreparationCapture], ActionPayload] | None = None,
        async_payload_factory: (
            Callable[[ActionPreparationCapture], Awaitable[ActionPayload]] | None
        ) = None,
    ) -> ActionPrepareOutput:
        descriptor = self._registry.get(capability_name)
        self._authorization.authorize(descriptor)
        call = await self._begin_call(descriptor.name, request)
        replay = self._replayed_output(call, ActionPrepareOutput)
        if replay is not None:
            return replay
        try:
            capture = await prepare()
            if async_payload_factory is not None:
                resolved_payload = await async_payload_factory(capture)
            else:
                resolved_payload = (
                    payload_factory(capture) if payload_factory is not None else payload
                )
            if resolved_payload is None:
                raise RuntimeError("Action preparation has no typed payload.")
            created_at = datetime.now(UTC)
            expires_at = created_at + timedelta(seconds=self._settings.action_draft_ttl_seconds)
            payload_hash = canonical_action_payload_hash(
                action_type=action_type.value,
                target=capture.target,
                payload=resolved_payload,
            )
            draft = ActionDraft(
                action_id=str(uuid.uuid4()),
                action_type=action_type,
                target=capture.target,
                payload=resolved_payload,
                payload_hash=payload_hash,
                status=ActionStatus.READY_FOR_CONFIRMATION,
                created_at=created_at,
                expires_at=expires_at,
            )
            source = source_from_action_preparation(action_type.value, capture)
            output = ActionPrepareOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                draft=draft,
                approval_preview=action_approval_preview(draft),
                sources=(source.reference(),),
            )
            await self._repository.complete_preparation_call(
                call_id=call.call_id,
                draft=draft,
                output=output.model_dump(mode="json"),
                sources=(source,),
            )
            return output
        except asyncio.CancelledError:
            await self._record_failure(
                call.call_id,
                BrowserUnavailableError("The LinkedIn action preparation was interrupted."),
            )
            raise
        except Exception as error:
            await self._record_failure(call.call_id, error)
            raise

    async def _execute_action(
        self,
        *,
        capability_name: CapabilityName,
        request: ActionExecuteInput,
        action_type: ActionType,
        execute: Callable[[ActionDraft], Awaitable[ActionPageResult]],
    ) -> ActionExecuteOutput:
        descriptor = self._registry.get(capability_name)
        self._authorization.authorize(descriptor)
        call = await self._begin_call(descriptor.name, request)
        replay = self._replayed_output(call, ActionExecuteOutput)
        if replay is not None:
            return replay
        attempt: ActionAttemptStart | None = None
        action_completed = False
        try:
            attempt = await self._repository.begin_action_attempt(
                account_id=self._settings.account_id,
                client_id=current_client_id(),
                action_id=request.action_id,
                expected_action_type=action_type,
                expected_payload_hash=request.payload_hash,
                approval_preview=request.approval_preview,
                idempotency_key=request.idempotency_key,
            )
            if not attempt.created:
                if attempt.result is None:
                    raise IdempotencyConflictError(
                        "The terminal action attempt has no process-local result."
                    )
                result = ActionExecutionResult.model_validate(attempt.result)
                output = ActionExecuteOutput(
                    context_id=request.context_id,
                    request_id=request.request_id,
                    result=result,
                    sources=tuple(source.reference() for source in attempt.sources),
                    replayed=True,
                )
                await self._repository.complete_call(
                    call_id=call.call_id,
                    output=output.model_dump(mode="json"),
                    sources=attempt.sources,
                )
                return output

            page_result = await execute(attempt.action)
            completed_at = datetime.now(UTC)
            result = ActionExecutionResult(
                action_id=attempt.action.action_id,
                action_type=action_type,
                attempt_id=attempt.attempt_id,
                idempotency_key=request.idempotency_key,
                outcome=page_result.outcome,
                performed=page_result.performed,
                final_state=page_result.final_state,
                detail=page_result.detail,
                started_at=attempt.started_at,
                completed_at=completed_at,
            )
            source = source_from_action_execution(attempt.action, result, page_result)
            await self._repository.complete_action_attempt(
                account_id=self._settings.account_id,
                client_id=current_client_id(),
                context_id=request.context_id,
                attempt_id=attempt.attempt_id,
                outcome=result.outcome,
                result=result.model_dump(mode="json"),
                sources=(source,),
            )
            action_completed = True
            output = ActionExecuteOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                result=result,
                sources=(source.reference(),),
            )
            await self._repository.complete_call(
                call_id=call.call_id,
                output=output.model_dump(mode="json"),
                sources=(source,),
            )
            return output
        except asyncio.CancelledError:
            if attempt is not None and attempt.created and not action_completed:
                await self._record_uncertain_attempt(request, attempt)
            await self._record_failure(
                call.call_id,
                BrowserUnavailableError("The LinkedIn write was interrupted."),
            )
            raise
        except Exception as error:
            if attempt is not None and attempt.created and not action_completed:
                logger.error(
                    "action_execution_interrupted",
                    capability_name=capability_name.value,
                    action_id=request.action_id,
                    error_type=type(error).__name__,
                )
                try:
                    output = await self._record_uncertain_attempt(request, attempt)
                    await self._repository.complete_call(
                        call_id=call.call_id,
                        output=output.model_dump(mode="json"),
                        sources=(),
                    )
                    return output
                except Exception as recording_error:
                    logger.error(
                        "action_uncertain_recording_failed",
                        action_id=request.action_id,
                        error_type=type(recording_error).__name__,
                    )
            await self._record_failure(call.call_id, error)
            raise

    async def _record_uncertain_attempt(
        self,
        request: ActionExecuteInput,
        attempt: ActionAttemptStart,
    ) -> ActionExecuteOutput:
        completed_at = datetime.now(UTC)
        result = ActionExecutionResult(
            action_id=attempt.action.action_id,
            action_type=attempt.action.action_type,
            attempt_id=attempt.attempt_id,
            idempotency_key=request.idempotency_key,
            outcome=ActionOutcome.UNCERTAIN,
            performed=None,
            final_state="unknown_after_interruption",
            detail=(
                "Execution stopped without a verified visible outcome; operator review is required."
            ),
            started_at=attempt.started_at,
            completed_at=completed_at,
        )
        await self._repository.complete_action_attempt(
            account_id=self._settings.account_id,
            client_id=current_client_id(),
            context_id=request.context_id,
            attempt_id=attempt.attempt_id,
            outcome=ActionOutcome.UNCERTAIN,
            result=result.model_dump(mode="json"),
            sources=(),
        )
        return ActionExecuteOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            result=result,
            sources=(),
        )

    @staticmethod
    def _missing_invitation_reference() -> str:
        raise RuntimeError("Acceptance preparation did not return an invitation reference.")

    async def _begin_call(
        self,
        capability_name: CapabilityName,
        request: CapabilityRequest,
    ) -> CallStart:
        value = request.model_dump(mode="json")
        return await self._repository.begin_call(
            account_id=self._settings.account_id,
            client_id=current_client_id(),
            context_id=request.context_id,
            request_id=request.request_id,
            capability_name=capability_name,
            input_fingerprint=canonical_input_fingerprint(value),
            input_value=value,
        )

    async def _pagination_lease(
        self,
        capability_name: CapabilityName,
        request: PaginatedInput,
    ) -> PaginationLease:
        execution = current_execution_context()
        lease = execution.pagination_lease
        if lease is None:
            return await self._pagination.acquire(
                account_id=self._settings.account_id,
                client_id=execution.client_id,
                capability_name=capability_name,
                request=request,
            )
        if (
            lease.account_id != self._settings.account_id
            or lease.client_id != execution.client_id
            or lease.capability_name is not capability_name
            or lease.binding != request_binding(capability_name, request)
        ):
            raise RuntimeError("The queued pagination lease does not match this atomic call.")
        return lease

    @staticmethod
    def _replayed_output[OutputT: StrictModel](
        call: CallStart,
        output_type: type[OutputT],
    ) -> OutputT | None:
        if call.created:
            return None
        if call.status is CallStatus.COMPLETED and call.output is not None:
            return output_type.model_validate(call.output).model_copy(update={"replayed": True})
        if call.status is CallStatus.STARTED:
            raise IdempotencyConflictError("An identical request is already executing.")
        message = call.error_message or "The previous attempt failed."
        raise IdempotencyConflictError(
            f"This request ID belongs to a failed attempt: {message} Use a new request ID."
        )

    async def _record_failure(self, call_id: str, error: Exception) -> None:
        if isinstance(error, LinkedInMCPError):
            code = error.code.value
            message = error.safe_message
        else:
            code = ErrorCode.INTERNAL_ERROR.value
            message = "The capability failed unexpectedly."
        try:
            await self._repository.fail_call(
                call_id=call_id,
                error_code=code,
                error_message=message,
            )
        except Exception as recording_error:
            logger.error(
                "capability_failure_recording_failed",
                call_id=call_id,
                original_error_code=code,
                recording_error_type=type(recording_error).__name__,
            )


def safe_capability_error(error: Exception) -> LinkedInMCPError:
    if isinstance(error, LinkedInMCPError):
        return error
    return InternalServerError()
