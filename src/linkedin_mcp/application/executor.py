"""Execution of registered LinkedIn capabilities."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

import structlog

from linkedin_mcp.application.client_context import current_execution_context
from linkedin_mcp.application.pagination import (
    PaginationLease,
    PaginationManager,
    request_binding,
    select_page,
)
from linkedin_mcp.config import Settings
from linkedin_mcp.domain.evidence import (
    source_from_action_execution,
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
    ActionCommand,
    ActionInspection,
    ActionOutcome,
    ActionOutput,
    ActionPageResult,
    ActionPayload,
    ActionResult,
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
    InvitationAcceptInput,
    InvitationAcceptPayload,
    InvitationIgnoreInput,
    InvitationIgnorePayload,
    InvitationListCoverage,
    InvitationListInput,
    InvitationListOutput,
    InvitationSendInput,
    InvitationSendPayload,
    InvitationSummary,
    JobDetailInput,
    JobDetailObservation,
    JobDetailOutput,
    JobSearchCoverage,
    JobSearchInput,
    JobSearchOutput,
    JobSummary,
    MessageSendInput,
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
    PostCommentInput,
    PostCommentsCoverage,
    PostCommentsListInput,
    PostCommentsListOutput,
    PostCreateInput,
    PostCreatePayload,
    PostGetInput,
    PostGetOutput,
    PostObservation,
    PostReactionInput,
    PostSearchCoverage,
    PostSearchInput,
    PostSearchOutput,
    PostSummary,
    ReactionSetPayload,
    StopReason,
)
from linkedin_mcp.errors import (
    InternalServerError,
    LinkedInMCPError,
    ParserDriftError,
)

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
    async def inspect_post(
        self,
        request: PostCreateInput,
    ) -> ActionInspection: ...

    async def perform_post(self, command: ActionCommand) -> ActionPageResult: ...


class PostEngagementProvider(Protocol):
    async def inspect_comment(
        self,
        request: PostCommentInput,
    ) -> ActionInspection: ...

    async def perform_comment(self, command: ActionCommand) -> ActionPageResult: ...

    async def inspect_reaction(
        self,
        request: PostReactionInput,
    ) -> ActionInspection: ...

    async def perform_reaction(self, command: ActionCommand) -> ActionPageResult: ...


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
    async def inspect_send(
        self,
        request: InvitationSendInput,
    ) -> ActionInspection: ...

    async def inspect_accept(
        self,
        request: InvitationAcceptInput,
    ) -> ActionInspection: ...

    async def inspect_ignore(
        self,
        request: InvitationIgnoreInput,
    ) -> ActionInspection: ...

    async def perform_send(self, command: ActionCommand) -> ActionPageResult: ...

    async def perform_accept(self, command: ActionCommand) -> ActionPageResult: ...

    async def perform_ignore(self, command: ActionCommand) -> ActionPageResult: ...


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

    async def inspect_message(
        self,
        request: MessageSendInput,
    ) -> ActionInspection: ...

    async def perform_message(self, command: ActionCommand) -> ActionPageResult: ...


class CapabilityExecutor:
    def __init__(
        self,
        *,
        settings: Settings,
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

    async def close(self) -> None:
        await self._pagination.close()

    async def search_jobs(self, request: JobSearchInput) -> JobSearchOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.JOBS_SEARCH, request)
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
            return JobSearchOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                jobs=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def get_job(self, request: JobDetailInput) -> JobDetailOutput:
        job = await self._job_detail.read(request)
        source = source_from_job_detail(job)
        return JobDetailOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            job=job,
            sources=(source,),
        )

    async def search_people(self, request: PeopleSearchInput) -> PeopleSearchOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.PEOPLE_SEARCH, request)
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
            return PeopleSearchOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                people=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def search_connections(
        self,
        request: ConnectionsSearchInput,
    ) -> ConnectionsSearchOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.CONNECTIONS_SEARCH, request)
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
            return ConnectionsSearchOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                people=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def get_person(self, request: PeopleGetInput) -> PeopleGetOutput:
        person, captures = await self._person_profile.read(request)
        sources = sources_from_person_profile(person, captures)
        return PeopleGetOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            person=person,
            sources=sources,
        )

    async def search_companies(self, request: CompanySearchInput) -> CompanySearchOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.COMPANIES_SEARCH, request)
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
            return CompanySearchOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                companies=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def get_company(self, request: CompanyGetInput) -> CompanyGetOutput:
        company, captures = await self._company_profile.read(request)
        sources = sources_from_company_profile(company, captures)
        return CompanyGetOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            company=company,
            sources=sources,
        )

    async def search_posts(self, request: PostSearchInput) -> PostSearchOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.POSTS_SEARCH, request)
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
            return PostSearchOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                posts=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def get_post(self, request: PostGetInput) -> PostGetOutput:
        post = await self._post_detail.read(request)
        source = source_from_post(post)
        return PostGetOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            post=post,
            sources=(source,),
        )

    async def list_post_comments(
        self,
        request: PostCommentsListInput,
    ) -> PostCommentsListOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.POST_COMMENTS_LIST, request)
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
            return PostCommentsListOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                threads=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def list_invitations(
        self,
        request: InvitationListInput,
        progress: ProgressReporter | None = None,
    ) -> InvitationListOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.INVITATIONS_LIST, request)
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
            return InvitationListOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                invitations=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def list_connections(self, request: ConnectionsListInput) -> ConnectionsListOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.CONNECTIONS_LIST, request)
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
            return ConnectionsListOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                connections=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def search_messages(
        self,
        request: ConversationSearchInput,
    ) -> ConversationSearchOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.MESSAGING_SEARCH, request)
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
            return ConversationSearchOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                conversations=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def get_conversation(
        self,
        request: ConversationGetInput,
    ) -> ConversationGetOutput:
        observation = await self._conversation.read(request)
        source = source_from_conversation(observation)
        return ConversationGetOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            conversation=observation,
            sources=(source,),
        )

    async def send_invitation(self, request: InvitationSendInput) -> ActionOutput:
        return await self._run_action(
            capability_name=CapabilityName.INVITATION_SEND,
            request=request,
            action_type=ActionType.INVITATION_SEND,
            payload=InvitationSendPayload(note=request.note),
            inspect=lambda: self._invitation_actions.inspect_send(request),
            perform=self._invitation_actions.perform_send,
        )

    async def accept_invitation(self, request: InvitationAcceptInput) -> ActionOutput:
        return await self._run_action(
            capability_name=CapabilityName.INVITATION_ACCEPT,
            request=request,
            action_type=ActionType.INVITATION_ACCEPT,
            payload_factory=lambda inspection: InvitationAcceptPayload(
                invitation_ref=(
                    inspection.target.invitation_ref or self._missing_invitation_reference()
                )
            ),
            inspect=lambda: self._invitation_actions.inspect_accept(request),
            perform=self._invitation_actions.perform_accept,
        )

    async def ignore_invitation(self, request: InvitationIgnoreInput) -> ActionOutput:
        return await self._run_action(
            capability_name=CapabilityName.INVITATION_IGNORE,
            request=request,
            action_type=ActionType.INVITATION_IGNORE,
            payload_factory=lambda inspection: InvitationIgnorePayload(
                invitation_ref=(
                    inspection.target.invitation_ref or self._missing_invitation_reference()
                )
            ),
            inspect=lambda: self._invitation_actions.inspect_ignore(request),
            perform=self._invitation_actions.perform_ignore,
        )

    async def send_message(self, request: MessageSendInput) -> ActionOutput:
        return await self._run_action(
            capability_name=CapabilityName.MESSAGING_SEND,
            request=request,
            action_type=ActionType.MESSAGE_SEND,
            payload=MessageSendPayload(
                message=request.message,
                attachment_refs=tuple(attachment.asset_ref for attachment in request.attachments),
                gif=request.gif,
                reply_to_message_ref=request.reply_to_message_ref,
            ),
            inspect=lambda: self._conversation.inspect_message(request),
            perform=self._conversation.perform_message,
        )

    async def create_post(self, request: PostCreateInput) -> ActionOutput:
        return await self._run_action(
            capability_name=CapabilityName.POSTS_CREATE,
            request=request,
            action_type=ActionType.POST_CREATE,
            payload=PostCreatePayload(
                content=request.content,
                audience=request.audience,
                group_target=request.group_target,
                comment_control=request.comment_control,
                brand_partnership=request.brand_partnership,
                collaborators=request.collaborators,
                scheduled_at=request.scheduled_at,
            ),
            inspect=lambda: self._post_publishing.inspect_post(request),
            perform=self._post_publishing.perform_post,
        )

    async def comment_on_post(self, request: PostCommentInput) -> ActionOutput:
        return await self._run_action(
            capability_name=CapabilityName.POST_COMMENT,
            request=request,
            action_type=ActionType.COMMENT_CREATE,
            payload=CommentCreatePayload(
                post_ref=request.post_ref,
                text=request.text,
                mentions=request.mentions,
                attachment=request.attachment,
            ),
            inspect=lambda: self._post_engagement.inspect_comment(request),
            perform=self._post_engagement.perform_comment,
        )

    async def react_to_post(self, request: PostReactionInput) -> ActionOutput:
        def payload_factory(inspection: ActionInspection) -> ActionPayload:
            if inspection.existing_reaction is None:
                raise RuntimeError("Reaction inspection captured no visible reaction state.")
            return ReactionSetPayload(
                post_ref=request.post_ref,
                existing_reaction=inspection.existing_reaction,
                desired_reaction=request.desired_reaction,
            )

        return await self._run_action(
            capability_name=CapabilityName.POST_REACT,
            request=request,
            action_type=ActionType.REACTION_SET,
            payload_factory=payload_factory,
            inspect=lambda: self._post_engagement.inspect_reaction(request),
            perform=self._post_engagement.perform_reaction,
        )

    async def _run_action(
        self,
        *,
        capability_name: CapabilityName,
        request: (
            InvitationSendInput
            | InvitationAcceptInput
            | InvitationIgnoreInput
            | MessageSendInput
            | PostCreateInput
            | PostCommentInput
            | PostReactionInput
        ),
        action_type: ActionType,
        inspect: Callable[[], Awaitable[ActionInspection]],
        perform: Callable[[ActionCommand], Awaitable[ActionPageResult]],
        payload: ActionPayload | None = None,
        payload_factory: Callable[[ActionInspection], ActionPayload] | None = None,
    ) -> ActionOutput:
        execution_id = str(uuid.uuid4())
        started_at = datetime.now(UTC)
        inspection = await inspect()
        resolved_payload = payload_factory(inspection) if payload_factory is not None else payload
        if resolved_payload is None:
            raise RuntimeError("Action inspection produced no typed payload.")
        command = ActionCommand(
            action_type=action_type,
            target=inspection.target,
            payload=resolved_payload,
        )
        try:
            page_result = await perform(command)
        except asyncio.CancelledError:
            raise
        except LinkedInMCPError:
            raise
        except Exception as error:
            logger.error(
                "action_execution_interrupted",
                capability_name=capability_name.value,
                error_type=type(error).__name__,
            )
            result = ActionResult(
                action_type=action_type,
                outcome=ActionOutcome.UNCERTAIN,
                performed=None,
                final_state="unknown_after_interruption",
                detail=(
                    "Execution stopped without a verified visible outcome; "
                    "operator review is required."
                ),
                started_at=started_at,
                completed_at=datetime.now(UTC),
            )
            return ActionOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                result=result,
                sources=(),
            )

        result = ActionResult(
            action_type=action_type,
            outcome=page_result.outcome,
            performed=page_result.performed,
            final_state=page_result.final_state,
            detail=page_result.detail,
            started_at=started_at,
            completed_at=datetime.now(UTC),
        )
        source = source_from_action_execution(page_result, execution_id=execution_id)
        return ActionOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            result=result,
            sources=(source,),
        )

    @staticmethod
    def _missing_invitation_reference() -> str:
        raise RuntimeError("Invitation inspection did not return an invitation reference.")

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


def safe_capability_error(error: Exception) -> LinkedInMCPError:
    if isinstance(error, LinkedInMCPError):
        return error
    return InternalServerError()
