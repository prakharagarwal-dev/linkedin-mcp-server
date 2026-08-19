"""Core MCP protocol fixtures and end-to-end contract checks."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import anyio
import pytest
from mcp import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.shared.message import SessionMessage
from pydantic import HttpUrl

from linkedin_mcp import __version__
from linkedin_mcp.config import Settings
from linkedin_mcp.infra.cursor import CursorStore
from linkedin_mcp.infra.queue import Scheduler, Worker
from linkedin_mcp.tools import attach_tool_implementations
from linkedin_mcp.tools.companies.get.models import (
    CompanyGetInput,
    CompanyProfileCoverage,
    CompanyProfileObservation,
    CompanyProfilePageCapture,
)
from linkedin_mcp.tools.companies.get.page import CompanyProfilePage
from linkedin_mcp.tools.companies.search.models import (
    CompanySearchCoverage,
    CompanySearchInput,
    CompanySummary,
)
from linkedin_mcp.tools.companies.search.models import (
    StopReason as CompanyStopReason,
)
from linkedin_mcp.tools.companies.search.page import CompanySearchPage
from linkedin_mcp.tools.connections.list.models import (
    ConnectionsListCoverage,
    ConnectionsListInput,
    ConnectionSummary,
)
from linkedin_mcp.tools.connections.list.models import (
    StopReason as ConnectionsStopReason,
)
from linkedin_mcp.tools.connections.list.page import ConnectionsListPage
from linkedin_mcp.tools.connections.search.models import (
    ConnectionsSearchInput,
)
from linkedin_mcp.tools.connections.search.models import (
    PeopleSearchCoverage as ConnectionsSearchCoverage,
)
from linkedin_mcp.tools.connections.search.models import (
    PersonConnectionDegree as ConnectionsSearchDegree,
)
from linkedin_mcp.tools.connections.search.models import (
    PersonSummary as ConnectionsSearchPerson,
)
from linkedin_mcp.tools.connections.search.models import (
    StopReason as ConnectionsSearchStopReason,
)
from linkedin_mcp.tools.connections.search.page import ConnectionsSearchPage
from linkedin_mcp.tools.invitations.accept.models import (
    ActionCommand as AcceptActionCommand,
)
from linkedin_mcp.tools.invitations.accept.models import (
    ActionInspection as AcceptActionInspection,
)
from linkedin_mcp.tools.invitations.accept.models import (
    ActionOutcome as AcceptActionOutcome,
)
from linkedin_mcp.tools.invitations.accept.models import (
    ActionPageResult as AcceptActionPageResult,
)
from linkedin_mcp.tools.invitations.accept.models import (
    ActionTarget as AcceptActionTarget,
)
from linkedin_mcp.tools.invitations.accept.models import (
    InvitationAcceptInput,
)
from linkedin_mcp.tools.invitations.accept.page import AcceptInvitationPage
from linkedin_mcp.tools.invitations.ignore.models import (
    ActionCommand as IgnoreActionCommand,
)
from linkedin_mcp.tools.invitations.ignore.models import (
    ActionInspection as IgnoreActionInspection,
)
from linkedin_mcp.tools.invitations.ignore.models import (
    ActionOutcome as IgnoreActionOutcome,
)
from linkedin_mcp.tools.invitations.ignore.models import (
    ActionPageResult as IgnoreActionPageResult,
)
from linkedin_mcp.tools.invitations.ignore.models import (
    ActionTarget as IgnoreActionTarget,
)
from linkedin_mcp.tools.invitations.ignore.models import (
    InvitationIgnoreInput,
)
from linkedin_mcp.tools.invitations.ignore.page import IgnoreInvitationPage
from linkedin_mcp.tools.invitations.list.models import (
    InvitationAvailableAction,
    InvitationDirection,
    InvitationEntity,
    InvitationEntityType,
    InvitationFilter,
    InvitationListCoverage,
    InvitationListInput,
    InvitationSummary,
    InvitationType,
)
from linkedin_mcp.tools.invitations.list.models import (
    StopReason as InvitationStopReason,
)
from linkedin_mcp.tools.invitations.list.page import InvitationListPage
from linkedin_mcp.tools.invitations.send.models import (
    ActionCommand as SendActionCommand,
)
from linkedin_mcp.tools.invitations.send.models import (
    ActionInspection as SendActionInspection,
)
from linkedin_mcp.tools.invitations.send.models import (
    ActionOutcome as SendActionOutcome,
)
from linkedin_mcp.tools.invitations.send.models import (
    ActionPageResult as SendActionPageResult,
)
from linkedin_mcp.tools.invitations.send.models import (
    ActionTarget as SendActionTarget,
)
from linkedin_mcp.tools.invitations.send.models import (
    InvitationSendInput,
)
from linkedin_mcp.tools.invitations.send.page import SendInvitationPage
from linkedin_mcp.tools.jobs.get.models import (
    EvidenceField,
    JobDetailInput,
    JobDetailObservation,
)
from linkedin_mcp.tools.jobs.get.page import JobDetailPage
from linkedin_mcp.tools.jobs.search.models import (
    JobSearchCoverage,
    JobSearchInput,
    JobSummary,
)
from linkedin_mcp.tools.jobs.search.models import (
    StopReason as JobStopReason,
)
from linkedin_mcp.tools.jobs.search.page import JobSearchPage
from linkedin_mcp.tools.messaging.conversation.get.models import (
    ConversationCoverage,
    ConversationGetInput,
    ConversationObservation,
    MessageDirection,
    MessageObservation,
)
from linkedin_mcp.tools.messaging.conversation.get.models import (
    StopReason as ConversationStopReason,
)
from linkedin_mcp.tools.messaging.conversation.get.page import ConversationGetPage
from linkedin_mcp.tools.messaging.search.models import (
    ConversationSearchCoverage,
    ConversationSearchInput,
    ConversationSummary,
)
from linkedin_mcp.tools.messaging.search.models import (
    StopReason as MessagingStopReason,
)
from linkedin_mcp.tools.messaging.search.page import ConversationSearchPage
from linkedin_mcp.tools.messaging.send.models import (
    ActionCommand as MessageActionCommand,
)
from linkedin_mcp.tools.messaging.send.models import (
    ActionInspection as MessageActionInspection,
)
from linkedin_mcp.tools.messaging.send.models import (
    ActionOutcome as MessageActionOutcome,
)
from linkedin_mcp.tools.messaging.send.models import (
    ActionPageResult as MessageActionPageResult,
)
from linkedin_mcp.tools.messaging.send.models import (
    ActionTarget as MessageActionTarget,
)
from linkedin_mcp.tools.messaging.send.models import (
    MessageSendInput,
)
from linkedin_mcp.tools.messaging.send.page import MessageSendPage
from linkedin_mcp.tools.people.get.models import (
    PeopleGetInput,
    PersonProfileCoverage,
    PersonProfileObservation,
    PersonProfilePageCapture,
)
from linkedin_mcp.tools.people.get.page import PersonProfilePage
from linkedin_mcp.tools.people.search.models import (
    PeopleSearchCoverage,
    PeopleSearchInput,
    PersonConnectionDegree,
    PersonSummary,
)
from linkedin_mcp.tools.people.search.models import (
    StopReason as PeopleStopReason,
)
from linkedin_mcp.tools.people.search.page import PeopleSearchPage
from linkedin_mcp.tools.posts.comment.models import (
    ActionCommand as CommentActionCommand,
)
from linkedin_mcp.tools.posts.comment.models import (
    ActionInspection as CommentActionInspection,
)
from linkedin_mcp.tools.posts.comment.models import (
    ActionOutcome as CommentActionOutcome,
)
from linkedin_mcp.tools.posts.comment.models import (
    ActionPageResult as CommentActionPageResult,
)
from linkedin_mcp.tools.posts.comment.models import (
    ActionTarget as CommentActionTarget,
)
from linkedin_mcp.tools.posts.comment.models import (
    PostCommentInput,
)
from linkedin_mcp.tools.posts.comment.page import PostCommentPage
from linkedin_mcp.tools.posts.comments.list.models import (
    CommentObservation,
    CommentThread,
    PostCommentsCoverage,
    PostCommentsListInput,
)
from linkedin_mcp.tools.posts.comments.list.models import (
    PostAuthor as CommentPostAuthor,
)
from linkedin_mcp.tools.posts.comments.list.models import (
    PostAuthorType as CommentPostAuthorType,
)
from linkedin_mcp.tools.posts.comments.list.page import PostCommentsPage
from linkedin_mcp.tools.posts.create.models import (
    ActionCommand as PostActionCommand,
)
from linkedin_mcp.tools.posts.create.models import (
    ActionInspection as PostActionInspection,
)
from linkedin_mcp.tools.posts.create.models import (
    ActionOutcome as PostActionOutcome,
)
from linkedin_mcp.tools.posts.create.models import (
    ActionPageResult as PostActionPageResult,
)
from linkedin_mcp.tools.posts.create.models import (
    ActionTarget as PostActionTarget,
)
from linkedin_mcp.tools.posts.create.models import (
    PostCreateInput,
)
from linkedin_mcp.tools.posts.create.page import PostPublishingPage
from linkedin_mcp.tools.posts.get.models import (
    PostAuthor as GetPostAuthor,
)
from linkedin_mcp.tools.posts.get.models import (
    PostDetailCoverage,
    PostGetInput,
    PostObservation,
)
from linkedin_mcp.tools.posts.get.page import PostDetailPage
from linkedin_mcp.tools.posts.react.models import (
    ActionCommand as ReactionActionCommand,
)
from linkedin_mcp.tools.posts.react.models import (
    ActionInspection as ReactionActionInspection,
)
from linkedin_mcp.tools.posts.react.models import (
    ActionOutcome as ReactionActionOutcome,
)
from linkedin_mcp.tools.posts.react.models import (
    ActionPageResult as ReactionActionPageResult,
)
from linkedin_mcp.tools.posts.react.models import (
    ActionTarget as ReactionActionTarget,
)
from linkedin_mcp.tools.posts.react.models import (
    PostReactionInput,
    ReactionState,
)
from linkedin_mcp.tools.posts.react.page import PostReactionPage
from linkedin_mcp.tools.posts.search.models import (
    PostAuthor,
    PostAuthorType,
    PostSearchCoverage,
    PostSearchInput,
    PostSummary,
)
from linkedin_mcp.tools.posts.search.models import (
    StopReason as PostStopReason,
)
from linkedin_mcp.tools.posts.search.page import PostSearchPage
from linkedin_mcp.transport.server import create_mcp_server
from linkedin_mcp.ui import LinkedInPlaywright
from tests.support.playwright import empty_playwright

ROOT = Path(__file__).parents[2]


class ProtocolJobSearch:
    async def collect(
        self,
        request: JobSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[JobSummary, ...], JobSearchCoverage, str, str]:
        del result_limit
        job = JobSummary(
            job_id="4100000001",
            job_url=HttpUrl("https://www.linkedin.com/jobs/view/4100000001/"),
            title="Senior Python Engineer",
            company_name="Acme Cloud",
            location="India (Remote)",
            visible_text="Senior Python Engineer\nAcme Cloud\nIndia (Remote)",
        )
        return (
            (job,),
            JobSearchCoverage(
                query=request.query,
                location=request.location,
                freshness_hours=request.freshness_hours,
                filters=request.filters,
                pages_visited=1,
                result_count=1,
                max_results=request.page_size,
                stop_reason=JobStopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=datetime.now(UTC),
            ),
            job.visible_text,
            "https://www.linkedin.com/jobs/search/?keywords=python",
        )


class ProtocolJobDetail:
    async def read(self, request: JobDetailInput) -> JobDetailObservation:
        return JobDetailObservation(
            job_id=request.job_id,
            job_url=HttpUrl(f"https://www.linkedin.com/jobs/view/{request.job_id}/"),
            title="Senior Python Engineer",
            description_text="Build reliable services.",
            visible_text="Senior Python Engineer\nBuild reliable services.",
            evidence=(EvidenceField(field="title", quote="Senior Python Engineer"),),
            captured_at=datetime.now(UTC),
        )


class ProtocolPeopleSearch:
    async def collect(
        self,
        request: PeopleSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[PersonSummary, ...], PeopleSearchCoverage, str, str]:
        del result_limit
        person = PersonSummary(
            profile_slug="jane-doe",
            profile_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
            name="Jane Doe",
            headline="Staff Engineer",
            connection_degree=PersonConnectionDegree.FIRST,
            visible_text="Jane Doe\nStaff Engineer",
        )
        return (
            (person,),
            PeopleSearchCoverage(
                query=request.query,
                filters=request.filters,
                pages_visited=1,
                result_count=1,
                max_results=request.page_size,
                stop_reason=PeopleStopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=datetime.now(UTC),
            ),
            person.visible_text,
            "https://www.linkedin.com/search/results/people/",
        )


class ProtocolConnectionsSearch:
    async def collect(
        self,
        request: ConnectionsSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[
        tuple[ConnectionsSearchPerson, ...],
        ConnectionsSearchCoverage,
        str,
        str,
    ]:
        del result_limit
        visible_text = "Jane Doe\nStaff Engineer"
        person = ConnectionsSearchPerson(
            profile_slug="jane-doe",
            profile_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
            name="Jane Doe",
            headline="Staff Engineer",
            connection_degree=ConnectionsSearchDegree.FIRST,
            visible_text=visible_text,
        )
        return (
            (person,),
            ConnectionsSearchCoverage(
                query=request.query,
                filters=request.as_people_search_input().filters,
                pages_visited=1,
                result_count=1,
                max_results=request.page_size,
                stop_reason=ConnectionsSearchStopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=datetime.now(UTC),
            ),
            visible_text,
            "https://www.linkedin.com/search/results/people/",
        )


class ProtocolPersonProfile:
    async def read(
        self, request: PeopleGetInput
    ) -> tuple[PersonProfileObservation, tuple[PersonProfilePageCapture, ...]]:
        captured_at = datetime.now(UTC)
        profile_url = HttpUrl(f"https://www.linkedin.com/in/{request.profile_slug}/")
        person = PersonProfileObservation(
            profile_slug=request.profile_slug,
            profile_url=profile_url,
            name="Jane Doe",
            visible_text="Jane Doe\nStaff Engineer",
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
        )
        capture = PersonProfilePageCapture(
            source_url=profile_url,
            page_kind="profile",
            captured_text=person.visible_text,
            captured_at=captured_at,
        )
        return person, (capture,)


class ProtocolCompanySearch:
    async def collect(
        self,
        request: CompanySearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[CompanySummary, ...], CompanySearchCoverage, str, str]:
        del result_limit
        captured_at = datetime.now(UTC)
        visible_text = "Acme Cloud\nReliable infrastructure"
        company = CompanySummary(
            company_slug="acme-cloud",
            company_url=HttpUrl("https://www.linkedin.com/company/acme-cloud/"),
            name="Acme Cloud",
            tagline="Reliable infrastructure",
            visible_text=visible_text,
        )
        return (
            (company,),
            CompanySearchCoverage(
                query=request.query,
                filters=request.filters,
                pages_visited=1,
                result_count=1,
                max_results=request.page_size,
                stop_reason=CompanyStopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=captured_at,
            ),
            visible_text,
            "https://www.linkedin.com/search/results/companies/?keywords=acme",
        )


class ProtocolCompanyProfile:
    async def read(
        self,
        request: CompanyGetInput,
    ) -> tuple[CompanyProfileObservation, tuple[CompanyProfilePageCapture, ...]]:
        captured_at = datetime.now(UTC)
        overview_url = HttpUrl(f"https://www.linkedin.com/company/{request.company_slug}/")
        about_url = HttpUrl(f"https://www.linkedin.com/company/{request.company_slug}/about/")
        overview_text = "Acme Cloud\nReliable infrastructure"
        about_text = "About\nCloud infrastructure for reliable teams."
        observation = CompanyProfileObservation(
            company_slug=request.company_slug,
            company_url=overview_url,
            name="Acme Cloud",
            tagline="Reliable infrastructure",
            description="Cloud infrastructure for reliable teams.",
            visible_text=f"{overview_text}\n{about_text}",
            evidence=(),
            coverage=CompanyProfileCoverage(captured_at=captured_at),
            captured_at=captured_at,
        )
        captures = (
            CompanyProfilePageCapture(
                source_url=overview_url,
                page_kind="overview",
                captured_text=overview_text,
                captured_at=captured_at,
            ),
            CompanyProfilePageCapture(
                source_url=about_url,
                page_kind="about",
                captured_text=about_text,
                captured_at=captured_at,
            ),
        )
        return observation, captures


def _protocol_post_author() -> PostAuthor:
    return PostAuthor(
        author_type=PostAuthorType.MEMBER,
        name="Jane Doe",
        profile_slug="jane-doe",
        author_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
    )


class ProtocolPostSearch:
    async def collect(
        self,
        request: PostSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[PostSummary, ...], PostSearchCoverage, str, str]:
        del result_limit
        captured_at = datetime.now(UTC)
        visible_text = "Jane Doe\nA practical Python post."
        post = PostSummary(
            post_ref="activity:7312345678901234567",
            post_url=HttpUrl(
                "https://www.linkedin.com/feed/update/urn:li:activity:7312345678901234567/"
            ),
            author=_protocol_post_author(),
            text="A practical Python post.",
            visible_text=visible_text,
        )
        return (
            (post,),
            PostSearchCoverage(
                query=request.query,
                filters=request.filters,
                pages_visited=1,
                result_count=1,
                unsupported_result_count=1,
                max_results=request.page_size,
                stop_reason=PostStopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=captured_at,
            ),
            visible_text,
            "https://www.linkedin.com/search/results/content/?keywords=python",
        )


class ProtocolPostDetail:
    async def read(self, request: PostGetInput) -> PostObservation:
        captured_at = datetime.now(UTC)
        post_url = HttpUrl(f"https://www.linkedin.com/feed/update/urn:li:{request.post_ref}/")
        return PostObservation(
            post_ref=request.post_ref,
            displayed_post_ref=request.post_ref,
            post_url=post_url,
            author=GetPostAuthor.model_validate(_protocol_post_author().model_dump(mode="python")),
            text="A practical Python post.",
            comments_enabled=True,
            visible_text="Jane Doe\nA practical Python post.",
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
        )


class ProtocolPostComments:
    async def collect(
        self,
        request: PostCommentsListInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[CommentThread, ...], PostCommentsCoverage, str, str]:
        del result_limit
        captured_at = datetime.now(UTC)
        visible_text = "Alex Ray\nHelpful breakdown."
        comment = CommentObservation(
            comment_ref=f"comment:{request.post_ref}:111",
            post_ref=request.post_ref,
            author=CommentPostAuthor(
                author_type=CommentPostAuthorType.MEMBER,
                name="Alex Ray",
                profile_slug="alex-ray",
            ),
            text="Helpful breakdown.",
            visible_text=visible_text,
        )
        return (
            (CommentThread(comment=comment),),
            PostCommentsCoverage(
                post_ref=request.post_ref,
                discussion_post_ref=request.post_ref,
                sort_by=request.sort_by,
                expansion_rounds=1,
                top_level_visible=1,
                top_level_returned=1,
                replies_visible=0,
                replies_returned=0,
                max_comments=request.page_size,
                max_replies_per_comment=request.max_replies_per_comment,
                truncated=False,
                captured_at=captured_at,
            ),
            visible_text,
            f"https://www.linkedin.com/feed/update/urn:li:{request.post_ref}/",
        )


class ProtocolNetwork:
    """Typed fake for current network, messaging, and action contracts."""

    async def collect(
        self,
        request: InvitationListInput | ConnectionsListInput | ConversationSearchInput,
        *,
        result_limit: int | None = None,
        progress: object | None = None,
    ) -> tuple[tuple[object, ...], object, str, str]:
        del result_limit, progress
        captured_at = datetime.now(UTC)
        if isinstance(request, InvitationListInput):
            entity = InvitationEntity(
                entity_ref="member:jane-doe",
                entity_type=InvitationEntityType.PERSON,
                display_name="Jane Doe",
                slug="jane-doe",
                entity_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
            )
            item = InvitationSummary(
                invitation_ref="invitation:" + "a" * 24,
                direction=request.direction,
                invitation_type=InvitationType.CONNECTION_REQUEST,
                primary_entity=entity,
                inviter=entity,
                available_actions=(InvitationAvailableAction.ACCEPT,),
                visible_text="Jane Doe\nAccept\nIgnore",
                evidence=(),
            )
            coverage = InvitationListCoverage(
                direction=request.direction,
                invitation_filter=request.resolved_filter,
                advertised_count=1,
                unique_count=1,
                view_counts={request.resolved_filter: 1},
                view_source_urls={
                    request.resolved_filter: HttpUrl(
                        "https://www.linkedin.com/mynetwork/invitation-manager/received/"
                    )
                },
                view_membership_count=1,
                overlap_count=0,
                result_count=1,
                max_results=request.page_size,
                scroll_rounds=1,
                collection_attempts=1,
                neighboring_recommendation_count=0,
                invitation_type_counts={InvitationType.CONNECTION_REQUEST: 1},
                entity_type_counts={InvitationEntityType.PERSON: 1},
                stop_reason=InvitationStopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=captured_at,
            )
            return (
                (item,),
                coverage,
                item.visible_text,
                "https://www.linkedin.com/mynetwork/invitation-manager/received/",
            )
        if isinstance(request, ConnectionsListInput):
            item = ConnectionSummary(
                profile_slug="jane-doe",
                profile_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
                name="Jane Doe",
                headline="Staff Engineer",
                visible_text="Jane Doe\nStaff Engineer",
            )
            coverage = ConnectionsListCoverage(
                sort_by=request.sort_by,
                rounds_visited=1,
                result_count=1,
                max_results=request.page_size,
                stop_reason=ConnectionsStopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=captured_at,
            )
            return (
                (item,),
                coverage,
                item.visible_text,
                "https://www.linkedin.com/mynetwork/invite-connect/connections/",
            )
        item = ConversationSummary(
            conversation_ref="conversation:" + "c" * 24,
            conversation_id="thread-123",
            participant_profile_slug="jane-doe",
            participant_profile_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
            participant_name="Jane Doe",
            last_message_text="Hello",
            unread=False,
            visible_text="Jane Doe\nHello",
        )
        coverage = ConversationSearchCoverage(
            query=request.query,
            category=request.resolved_category,
            filter=request.filter,
            rounds_visited=1,
            result_count=1,
            max_results=request.page_size,
            stop_reason=MessagingStopReason.VISIBLE_PAGE_COMPLETE,
            captured_at=captured_at,
        )
        return (item,), coverage, item.visible_text, "https://www.linkedin.com/messaging/"

    async def inspect_send(self, request: InvitationSendInput) -> SendActionInspection:
        return self._inspection(
            SendActionInspection,
            SendActionTarget,
            request.profile_slug,
            "connect_available",
        )

    async def inspect_accept(self, request: InvitationAcceptInput) -> AcceptActionInspection:
        return self._inspection(
            AcceptActionInspection,
            AcceptActionTarget,
            request.profile_slug,
            "received_invitation_pending",
            invitation=True,
        )

    async def inspect_ignore(self, request: InvitationIgnoreInput) -> IgnoreActionInspection:
        return self._inspection(
            IgnoreActionInspection,
            IgnoreActionTarget,
            request.profile_slug,
            "received_invitation_pending",
            invitation=True,
        )

    async def perform_send(self, command: SendActionCommand) -> SendActionPageResult:
        return self._result(SendActionPageResult, SendActionOutcome.VERIFIED, "pending_sent")

    async def perform_accept(self, command: AcceptActionCommand) -> AcceptActionPageResult:
        return self._result(AcceptActionPageResult, AcceptActionOutcome.VERIFIED, "connected")

    async def perform_ignore(self, command: IgnoreActionCommand) -> IgnoreActionPageResult:
        return self._result(
            IgnoreActionPageResult,
            IgnoreActionOutcome.VERIFIED,
            "invitation_ignored",
        )

    async def read(self, request: ConversationGetInput) -> ConversationObservation:
        message = MessageObservation(
            message_ref="message:" + "a" * 24,
            direction=MessageDirection.INCOMING,
            sender_name="Jane Doe",
            text="Hello",
            visible_text="Jane Doe\nHello",
        )
        captured_at = datetime.now(UTC)
        return ConversationObservation(
            conversation_ref=request.conversation_ref,
            conversation_id=request.conversation_id or "thread-123",
            participant_profile_slug=request.profile_slug or "jane-doe",
            participant_profile_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
            participant_name="Jane Doe",
            messages=(message,),
            visible_text=message.visible_text,
            coverage=ConversationCoverage(
                messages_observed=1,
                messages_returned=1,
                max_messages=request.max_messages,
                rounds_visited=1,
                stop_reason=ConversationStopReason.VISIBLE_PAGE_COMPLETE,
                history_complete=True,
                truncated=False,
                captured_at=captured_at,
            ),
            captured_at=captured_at,
        )

    async def inspect_message(self, request: MessageSendInput) -> MessageActionInspection:
        target = self._inspection(
            MessageActionInspection,
            MessageActionTarget,
            request.profile_slug or "jane-doe",
            "message_composer_available",
        )
        return target.model_copy(
            update={
                "target": target.target.model_copy(
                    update={"conversation_id": request.conversation_id or "thread-123"}
                ),
                "source_url": HttpUrl("https://www.linkedin.com/messaging/thread/thread-123/"),
            }
        )

    async def perform_message(self, command: MessageActionCommand) -> MessageActionPageResult:
        return self._result(
            MessageActionPageResult,
            MessageActionOutcome.VERIFIED,
            "message_sent",
        )

    async def inspect_post(self, request: PostCreateInput) -> PostActionInspection:
        del request
        return self._inspection(
            PostActionInspection,
            PostActionTarget,
            "current-member",
            "personal_post_composer_ready",
        )

    async def perform_post(self, command: PostActionCommand) -> PostActionPageResult:
        return self._result(
            PostActionPageResult,
            PostActionOutcome.VERIFIED,
            "post_published:activity:7312345678901234567",
        )

    async def inspect_comment(self, request: PostCommentInput) -> CommentActionInspection:
        inspection = self._inspection(
            CommentActionInspection,
            CommentActionTarget,
            "current-member",
            "comment_composer_ready",
        )
        return inspection.model_copy(
            update={"target": inspection.target.model_copy(update={"post_ref": request.post_ref})}
        )

    async def perform_comment(self, command: CommentActionCommand) -> CommentActionPageResult:
        return self._result(
            CommentActionPageResult,
            CommentActionOutcome.VERIFIED,
            "comment_published:comment:activity:7312345678901234567:900",
        )

    async def inspect_reaction(self, request: PostReactionInput) -> ReactionActionInspection:
        inspection = self._inspection(
            ReactionActionInspection,
            ReactionActionTarget,
            "current-member",
            "reaction_ready",
        )
        return inspection.model_copy(
            update={
                "target": inspection.target.model_copy(update={"post_ref": request.post_ref}),
                "existing_reaction": ReactionState.NONE,
            }
        )

    async def perform_reaction(
        self,
        command: ReactionActionCommand,
    ) -> ReactionActionPageResult:
        return self._result(
            ReactionActionPageResult,
            ReactionActionOutcome.VERIFIED,
            f"reaction_set:{command.payload.desired_reaction.value}",
        )

    @staticmethod
    def _inspection[InspectionT, TargetT](
        inspection_type: Callable[..., InspectionT],
        target_type: Callable[..., TargetT],
        profile_slug: str,
        current_state: str,
        *,
        invitation: bool = False,
    ) -> InspectionT:
        return inspection_type(
            target=target_type(
                profile_slug=profile_slug,
                profile_url=HttpUrl(f"https://www.linkedin.com/in/{profile_slug}/"),
                display_name="Jane Doe",
                invitation_ref="invitation:" + "a" * 24 if invitation else None,
            ),
            current_state=current_state,
            source_url=HttpUrl(f"https://www.linkedin.com/in/{profile_slug}/"),
            captured_text=f"Jane Doe\n{current_state}",
            captured_at=datetime.now(UTC),
        )

    @staticmethod
    def _result[ResultT](
        result_type: Callable[..., ResultT],
        outcome: Any,
        final_state: str,
    ) -> ResultT:
        return result_type(
            outcome=outcome,
            performed=True,
            final_state=final_state,
            detail=f"Visible state: {final_state}",
            source_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
            captured_text=f"Jane Doe\n{final_state}",
            captured_at=datetime.now(UTC),
        )


def protocol_server(
    root: Path,
) -> tuple[FastMCP[None], Scheduler, LinkedInPlaywright, CursorStore]:
    settings = Settings(
        browser_auto_install=False,
        browser_profile_path=root / "profile",
        minimum_navigation_interval_seconds=0,
        runtime_lock_path=root / "runtime.lock",
    )
    playwright = empty_playwright(settings)
    network = ProtocolNetwork()
    cursor_store = CursorStore(
        ttl_seconds=settings.pagination_cursor_ttl_seconds,
        max_active_cursors=settings.pagination_max_active_cursors,
        max_seen_items_per_cursor=settings.pagination_max_seen_items_per_cursor,
    )
    worker = Worker()
    scheduler = Scheduler(worker, capacity=settings.queue_capacity)
    mcp = create_mcp_server(settings)
    attach_tool_implementations(
        mcp,
        settings=settings,
        playwright=playwright,
        scheduler=scheduler,
        cursor_store=cursor_store,
        job_search=cast(JobSearchPage, ProtocolJobSearch()),
        job_detail=cast(JobDetailPage, ProtocolJobDetail()),
        people_search=cast(PeopleSearchPage, ProtocolPeopleSearch()),
        connections_search=cast(ConnectionsSearchPage, ProtocolConnectionsSearch()),
        person_profile=cast(PersonProfilePage, ProtocolPersonProfile()),
        company_search=cast(CompanySearchPage, ProtocolCompanySearch()),
        company_profile=cast(CompanyProfilePage, ProtocolCompanyProfile()),
        post_search=cast(PostSearchPage, ProtocolPostSearch()),
        post_detail=cast(PostDetailPage, ProtocolPostDetail()),
        post_comments=cast(PostCommentsPage, ProtocolPostComments()),
        post_publishing=cast(PostPublishingPage, network),
        post_comment=cast(PostCommentPage, network),
        post_reaction=cast(PostReactionPage, network),
        invitation_list=cast(InvitationListPage, network),
        connections_list=cast(ConnectionsListPage, network),
        invitation_send=cast(SendInvitationPage, network),
        invitation_accept=cast(AcceptInvitationPage, network),
        invitation_ignore=cast(IgnoreInvitationPage, network),
        conversation_search=cast(ConversationSearchPage, network),
        conversation_read=cast(ConversationGetPage, network),
        message_send=cast(MessageSendPage, network),
    )
    return mcp, scheduler, playwright, cursor_store


@asynccontextmanager
async def protocol_session(root: Path) -> AsyncGenerator[ClientSession]:
    mcp, scheduler, browser, cursor_store = protocol_server(root)
    await scheduler.start()
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[
        SessionMessage
    ](50)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[
        SessionMessage
    ](50)

    async def run_server() -> None:
        await mcp._mcp_server.run(  # pyright: ignore[reportPrivateUsage]
            client_to_server_receive,
            server_to_client_send,
            mcp._mcp_server.create_initialization_options(),  # pyright: ignore[reportPrivateUsage]
            raise_exceptions=True,
        )

    try:
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(run_server)
            async with ClientSession(server_to_client_receive, client_to_server_send) as session:
                await session.initialize()
                yield session
            task_group.cancel_scope.cancel()
    finally:
        await scheduler.close()
        await cursor_store.close()
        await browser.close()


@pytest.mark.asyncio
async def test_mcp_exposes_current_tools_and_runs_core_read(tmp_path: Path) -> None:
    async with protocol_session(tmp_path) as session:
        initialized = await session.initialize()
        assert initialized.serverInfo.name == "linkedin-mcp-server"
        assert initialized.serverInfo.version == __version__
        assert initialized.instructions is not None
        assert "one complete LinkedIn action" in initialized.instructions

        listed = await session.list_tools()
        names = {tool.name for tool in listed.tools}
        action_names = {
            "linkedin.posts.create",
            "linkedin.posts.comment",
            "linkedin.posts.react",
            "linkedin.invitations.send",
            "linkedin.invitations.accept",
            "linkedin.invitations.ignore",
            "linkedin.messaging.send",
        }
        assert action_names.issubset(names)
        for name in action_names:
            tool = next(item for item in listed.tools if item.name == name)
            assert tool.annotations is not None
            assert tool.annotations.readOnlyHint is False
            assert tool.annotations.destructiveHint is True
            assert tool.annotations.idempotentHint is False

        result = await session.call_tool(
            "linkedin.jobs.search",
            {
                "context_id": "protocol",
                "request_id": "jobs",
                "query": "python",
                "page_size": 10,
            },
        )
        assert result.isError is False
        assert result.structuredContent is not None
        assert result.structuredContent["jobs"][0]["job_id"] == "4100000001"
        assert result.structuredContent["sources"]
        source = result.structuredContent["sources"][0]
        assert source["source_type"] == "linkedin_job_search"
        assert source["source_url"].startswith("https://www.linkedin.com/")
        assert (await session.list_resources()).resources == []
        assert (await session.list_resource_templates()).resourceTemplates == []


@pytest.mark.asyncio
async def test_every_read_and_operational_tool_round_trips_through_mcp(
    tmp_path: Path,
) -> None:
    post_ref = "activity:7312345678901234567"
    cases: tuple[tuple[str, dict[str, object], str], ...] = (
        ("linkedin.server.status", {}, "name"),
        ("linkedin.session.status", {}, "authentication_state"),
        (
            "linkedin.jobs.search",
            {"query": "python", "page_size": 10},
            "jobs",
        ),
        ("linkedin.jobs.get", {"job_id": "4100000001"}, "job"),
        ("linkedin.people.search", {"query": "Jane", "page_size": 10}, "people"),
        (
            "linkedin.people.get",
            {"profile_slug": "jane-doe", "sections": ["overview"]},
            "person",
        ),
        (
            "linkedin.companies.search",
            {"query": "Acme", "page_size": 10},
            "companies",
        ),
        ("linkedin.companies.get", {"company_slug": "acme-cloud"}, "company"),
        ("linkedin.posts.search", {"query": "python", "page_size": 10}, "posts"),
        ("linkedin.posts.get", {"post_ref": post_ref}, "post"),
        (
            "linkedin.posts.comments.list",
            {"post_ref": post_ref, "page_size": 10},
            "threads",
        ),
        (
            "linkedin.invitations.list",
            {
                "direction": "received",
                "invitation_filter": "focused",
                "page_size": 10,
            },
            "invitations",
        ),
        ("linkedin.connections.list", {"page_size": 10}, "connections"),
        (
            "linkedin.connections.search",
            {"query": "Jane", "page_size": 10},
            "people",
        ),
        (
            "linkedin.messaging.search",
            {"query": "Jane", "page_size": 10},
            "conversations",
        ),
        (
            "linkedin.messaging.conversation.get",
            {"conversation_id": "thread-123", "max_messages": 10},
            "conversation",
        ),
    )
    async with protocol_session(tmp_path) as session:
        for index, (tool_name, tool_args, expected_field) in enumerate(cases):
            arguments = dict(tool_args)
            if tool_name not in {
                "linkedin.server.status",
                "linkedin.session.status",
            }:
                arguments.update(
                    context_id="read-matrix",
                    request_id=f"read-{index}",
                )
            result = await session.call_tool(tool_name, arguments)
            assert result.isError is False, tool_name
            assert result.structuredContent is not None
            assert expected_field in result.structuredContent
            if tool_name == "linkedin.posts.search":
                assert result.structuredContent["coverage"]["unsupported_result_count"] == 1
            if tool_name == "linkedin.invitations.list":
                assert result.structuredContent["coverage"]["unadvertised_empty_views"] == []

        repeated = await session.call_tool(
            "linkedin.jobs.search",
            {
                "context_id": "read-matrix",
                "request_id": "read-3",
                "query": "python",
                "page_size": 10,
            },
        )
        assert repeated.isError is False
        assert repeated.structuredContent is not None
        assert repeated.structuredContent["jobs"][0]["job_id"] == "4100000001"
        assert "replayed" not in repeated.structuredContent


@pytest.mark.asyncio
async def test_each_action_is_one_direct_call_with_verified_evidence(tmp_path: Path) -> None:
    cases = (
        (
            "linkedin.posts.create",
            {"content": {"mode": "text", "text": "Atomic post"}},
            "post_published:",
        ),
        (
            "linkedin.posts.comment",
            {"post_ref": "activity:7312345678901234567", "text": "Thanks"},
            "comment_published:",
        ),
        (
            "linkedin.posts.react",
            {
                "post_ref": "activity:7312345678901234567",
                "desired_reaction": "like",
            },
            "reaction_set:like",
        ),
        (
            "linkedin.invitations.send",
            {"profile_slug": "jane-doe", "note": "Hello"},
            "pending_sent",
        ),
        (
            "linkedin.invitations.accept",
            {"profile_slug": "jane-doe"},
            "connected",
        ),
        (
            "linkedin.invitations.ignore",
            {"profile_slug": "jane-doe"},
            "invitation_ignored",
        ),
        (
            "linkedin.messaging.send",
            {"conversation_id": "thread-123", "message": "Hello"},
            "message_sent",
        ),
    )
    async with protocol_session(tmp_path) as session:
        for index, (tool_name, action_args, expected_state) in enumerate(cases):
            result = await session.call_tool(
                tool_name,
                {
                    "context_id": "atomic-actions",
                    "request_id": f"action-{index}",
                    **action_args,
                },
            )
            assert result.isError is False
            assert result.structuredContent is not None
            action_result = result.structuredContent["result"]
            assert action_result["outcome"] == "verified"
            assert action_result["performed"] is True
            assert str(action_result["final_state"]).startswith(expected_state)
            assert len(result.structuredContent["sources"]) == 1

        first = await session.call_tool(
            "linkedin.invitations.send",
            {
                "context_id": "repeat",
                "request_id": "same-id",
                "profile_slug": "jane-doe",
            },
        )
        second = await session.call_tool(
            "linkedin.invitations.send",
            {
                "context_id": "repeat",
                "request_id": "same-id",
                "profile_slug": "jane-doe",
            },
        )
        assert first.isError is False
        assert second.isError is False
        assert first.structuredContent is not None
        assert second.structuredContent is not None
        assert first.structuredContent["sources"] != second.structuredContent["sources"]


def test_protocol_fakes_cover_current_invitation_defaults() -> None:
    request = InvitationListInput(
        context_id="protocol",
        request_id="invitations",
        direction=InvitationDirection.RECEIVED,
        invitation_filter=InvitationFilter.ALL,
    )
    assert request.resolved_filter is InvitationFilter.ALL
