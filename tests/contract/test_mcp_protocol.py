from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import anyio
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.message import SessionMessage
from mcp.types import TextContent, TextResourceContents
from pydantic import AnyUrl, HttpUrl, TypeAdapter

from linkedin_mcp.application import (
    AccountProcessLock,
    CapabilityExecutor,
    CapabilityWorker,
    ConnectionsListProvider,
    ConversationProvider,
    ConversationSearchProvider,
    InvitationActionProvider,
    InvitationListProvider,
    PostCommentsProvider,
    PostDetailProvider,
    PostEngagementProvider,
    PostPublishingProvider,
    PostSearchProvider,
)
from linkedin_mcp.browser import BrowserManager
from linkedin_mcp.capabilities import create_default_registry
from linkedin_mcp.config import Settings
from linkedin_mcp.container import AppContainer
from linkedin_mcp.domain.identifiers import PROFILE_SLUG_PATTERN
from linkedin_mcp.domain.models import (
    CURRENT_RECEIVED_INVITATION_VIEWS,
    ActionDraft,
    ActionOutcome,
    ActionPageResult,
    ActionPreparationCapture,
    ActionTarget,
    CapabilityEffect,
    CommentAttachmentObservation,
    CommentAttachmentType,
    CommentObservation,
    CommentThread,
    CompanyGetInput,
    CompanyProfileCoverage,
    CompanyProfileEvidence,
    CompanyProfileObservation,
    CompanyProfilePageCapture,
    CompanySearchCoverage,
    CompanySearchInput,
    CompanySummary,
    ConnectionsListCoverage,
    ConnectionsListInput,
    ConnectionSummary,
    ConversationCoverage,
    ConversationGetInput,
    ConversationObservation,
    ConversationSearchCoverage,
    ConversationSearchInput,
    ConversationSummary,
    EvidenceField,
    InvitationAcceptPrepareInput,
    InvitationAvailableAction,
    InvitationEntity,
    InvitationEntityType,
    InvitationEvidence,
    InvitationFilter,
    InvitationIgnorePrepareInput,
    InvitationListCoverage,
    InvitationListInput,
    InvitationSendPrepareInput,
    InvitationSummary,
    InvitationType,
    JobDetailInput,
    JobDetailObservation,
    JobSearchCoverage,
    JobSearchInput,
    JobSummary,
    LinkedInSurface,
    MessageDirection,
    MessageObservation,
    MessagePrepareInput,
    PeopleGetInput,
    PeopleSearchCoverage,
    PeopleSearchInput,
    PersonConnectionDegree,
    PersonProfileCoverage,
    PersonProfileEvidence,
    PersonProfileObservation,
    PersonProfilePageCapture,
    PersonSummary,
    PostAssetRole,
    PostAuthor,
    PostAuthorType,
    PostCommentPrepareInput,
    PostCommentsCoverage,
    PostCommentsListInput,
    PostCreatePrepareInput,
    PostDetailCoverage,
    PostEvidence,
    PostGetInput,
    PostObservation,
    PostReactionPrepareInput,
    PostSearchCoverage,
    PostSearchInput,
    PostSummary,
    PreparedPostAsset,
    ReactionSetPayload,
    ReactionState,
    StopReason,
)
from linkedin_mcp.persistence import MemoryRepository
from linkedin_mcp.server import create_mcp_server

ROOT = Path(__file__).parents[2]


class ProtocolJobSearch:
    async def collect(
        self,
        request: JobSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[JobSummary, ...], JobSearchCoverage, str, str]:
        del result_limit
        captured_at = datetime.now(UTC)
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
                max_results=request.max_results,
                stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=captured_at,
            ),
            job.visible_text,
            "https://www.linkedin.com/jobs/search/?keywords=python",
        )


class ProtocolJobDetail:
    async def read(self, request: JobDetailInput) -> JobDetailObservation:
        visible_text = "Senior Python Engineer\nBuild reliable services."
        return JobDetailObservation(
            job_id=request.job_id,
            job_url=HttpUrl(f"https://www.linkedin.com/jobs/view/{request.job_id}/"),
            title="Senior Python Engineer",
            description_text="Build reliable services.",
            visible_text=visible_text,
            evidence=(
                EvidenceField(field="title", quote="Senior Python Engineer"),
                EvidenceField(field="description_text", quote="Build reliable services."),
            ),
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
        captured_at = datetime.now(UTC)
        visible_text = "Jane Doe\nStaff Engineer at Acme Cloud\nBengaluru, Karnataka"
        person = PersonSummary(
            profile_slug="jane-doe",
            profile_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
            name="Jane Doe",
            headline="Staff Engineer at Acme Cloud",
            location="Bengaluru, Karnataka",
            connection_degree=PersonConnectionDegree.FIRST,
            visible_text=visible_text,
        )
        return (
            (person,),
            PeopleSearchCoverage(
                query=request.query,
                title_keywords=request.title_keywords,
                filters=request.filters,
                pages_visited=1,
                result_count=1,
                max_results=request.max_results,
                stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=captured_at,
            ),
            visible_text,
            "https://www.linkedin.com/search/results/people/?keywords=python",
        )


class ProtocolPersonProfile:
    async def read(
        self, request: PeopleGetInput
    ) -> tuple[PersonProfileObservation, tuple[PersonProfilePageCapture, ...]]:
        captured_at = datetime.now(UTC)
        profile_url = HttpUrl(f"https://www.linkedin.com/in/{request.profile_slug}/")
        captured_text = "Jane Doe\nStaff Engineer at Acme Cloud\nBuilds reliable systems."
        return (
            PersonProfileObservation(
                profile_slug=request.profile_slug,
                profile_url=profile_url,
                name="Jane Doe",
                headline="Staff Engineer at Acme Cloud",
                about="Builds reliable systems.",
                visible_text=captured_text,
                evidence=(
                    PersonProfileEvidence(
                        field="name",
                        quote="Jane Doe",
                        source_url=profile_url,
                    ),
                    PersonProfileEvidence(
                        field="about",
                        quote="Builds reliable systems.",
                        source_url=profile_url,
                    ),
                ),
                coverage=PersonProfileCoverage(
                    pages_visited=1,
                    detail_pages_discovered=0,
                    detail_pages_visited=0,
                    detail_page_limit=20,
                    truncated=False,
                    captured_at=captured_at,
                    requested_sections=request.sections,
                    returned_sections=("overview",),
                ),
                captured_at=captured_at,
            ),
            (
                PersonProfilePageCapture(
                    source_url=profile_url,
                    page_kind="profile",
                    captured_text=captured_text,
                    captured_at=captured_at,
                ),
            ),
        )


class ProtocolCompanySearch:
    async def collect(
        self,
        request: CompanySearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[CompanySummary, ...], CompanySearchCoverage, str, str]:
        del result_limit
        captured_at = datetime.now(UTC)
        visible_text = "Acme Cloud\nReliable infrastructure\nBengaluru, Karnataka"
        company = CompanySummary(
            company_slug="acme-cloud",
            company_url=HttpUrl("https://www.linkedin.com/company/acme-cloud/"),
            name="Acme Cloud",
            tagline="Reliable infrastructure",
            location="Bengaluru, Karnataka",
            visible_text=visible_text,
        )
        return (
            (company,),
            CompanySearchCoverage(
                query=request.query,
                filters=request.filters,
                pages_visited=1,
                result_count=1,
                max_results=request.max_results,
                stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
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
        source_url = HttpUrl(f"https://www.linkedin.com/company/{request.company_slug}/")
        about_url = HttpUrl(f"https://www.linkedin.com/company/{request.company_slug}/about/")
        overview_text = "Acme Cloud\nReliable infrastructure\n8,500 followers"
        about_text = (
            "About\nCloud infrastructure for reliable teams.\n"
            "Website\nhttps://acme.example\nIndustry\nSoftware Development\n"
            "Company size\n1,001-5,000 employees\nHeadquarters\nBengaluru, Karnataka\n"
            "Type\nPrivately Held\nFounded\n2014\nSpecialties\nCloud, Reliability"
        )
        captured_text = f"{overview_text}\n\n{about_text}"
        return (
            CompanyProfileObservation(
                company_slug=request.company_slug,
                company_url=source_url,
                name="Acme Cloud",
                tagline="Reliable infrastructure",
                description="Cloud infrastructure for reliable teams.",
                website_url=HttpUrl("https://acme.example/"),
                industry="Software Development",
                company_size_range="1,001-5,000 employees",
                follower_count_text="8,500 followers",
                headquarters="Bengaluru, Karnataka",
                organization_type="Privately Held",
                founded_text="2014",
                specialties=("Cloud", "Reliability"),
                visible_text=captured_text,
                evidence=(
                    CompanyProfileEvidence(
                        field="name",
                        quote="Acme Cloud",
                        source_url=source_url,
                    ),
                    CompanyProfileEvidence(
                        field="company_size_range",
                        quote="1,001-5,000 employees",
                        source_url=about_url,
                    ),
                ),
                coverage=CompanyProfileCoverage(captured_at=captured_at),
                captured_at=captured_at,
            ),
            (
                CompanyProfilePageCapture(
                    source_url=source_url,
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
            ),
        )


def _protocol_post_author() -> PostAuthor:
    return PostAuthor(
        author_type=PostAuthorType.MEMBER,
        name="Jane Doe",
        profile_slug="jane-doe",
        author_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
        headline="Staff Engineer at Acme Cloud",
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
        text = "Jane Doe\n2h\nA practical Python post.\n12 reactions\n3 comments"
        post = PostSummary(
            post_ref="activity:7312345678901234567",
            post_url=HttpUrl(
                "https://www.linkedin.com/feed/update/urn:li:activity:7312345678901234567/"
            ),
            author=_protocol_post_author(),
            text="A practical Python post.",
            posted_at_text="2h",
            reaction_count_text="12 reactions",
            comment_count_text="3 comments",
            visible_text=text,
        )
        return (
            (post,),
            PostSearchCoverage(
                query=request.query,
                filters=request.filters,
                pages_visited=1,
                result_count=1,
                max_results=request.max_results,
                stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=captured_at,
            ),
            text,
            "https://www.linkedin.com/search/results/content/?keywords=python",
        )


class ProtocolPostDetail:
    async def read(self, request: PostGetInput) -> PostObservation:
        post_url = HttpUrl(f"https://www.linkedin.com/feed/update/urn:li:{request.post_ref}/")
        text = "Jane Doe\n2h\nA practical Python post.\n12 reactions\n3 comments"
        captured_at = datetime.now(UTC)
        return PostObservation(
            post_ref=request.post_ref,
            displayed_post_ref=request.post_ref,
            post_url=post_url,
            author=_protocol_post_author(),
            text="A practical Python post.",
            posted_at_text="2h",
            reaction_count_text="12 reactions",
            comment_count_text="3 comments",
            visible_text=text,
            evidence=(
                PostEvidence(
                    field="author.name",
                    quote="Jane Doe",
                    source_url=post_url,
                    captured_at=captured_at,
                ),
                PostEvidence(
                    field="text",
                    quote="A practical Python post.",
                    source_url=post_url,
                    captured_at=captured_at,
                ),
            ),
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
        top_text = "Alex Ray\nHelpful breakdown.\n1h\n1 reply"
        reply_text = "Jane Doe\nThank you!\n45m"
        media_text = "Sam Kim\nPhoto shared in comment\n30m"
        parent_ref = f"comment:{request.post_ref}:111"
        top = CommentObservation(
            comment_ref=parent_ref,
            post_ref=request.post_ref,
            author=PostAuthor(
                author_type=PostAuthorType.MEMBER,
                name="Alex Ray",
                profile_slug="alex-ray",
            ),
            text="Helpful breakdown.",
            posted_at_text="1h",
            reply_count_text="1 reply",
            visible_text=top_text,
        )
        reply = CommentObservation(
            comment_ref=f"comment:{request.post_ref}:112",
            post_ref=request.post_ref,
            parent_comment_ref=parent_ref,
            author=_protocol_post_author(),
            text="Thank you!",
            posted_at_text="45m",
            visible_text=reply_text,
        )
        media = CommentObservation(
            comment_ref=f"comment:{request.post_ref}:113",
            post_ref=request.post_ref,
            author=PostAuthor(
                author_type=PostAuthorType.MEMBER,
                name="Sam Kim",
                profile_slug="sam-kim",
            ),
            attachments=(
                CommentAttachmentObservation(
                    attachment_type=CommentAttachmentType.PHOTO,
                    accessible_label="Photo shared in comment",
                    resource_url=HttpUrl("https://media.example.com/comment-photo.png"),
                    visible_text="Photo shared in comment",
                ),
            ),
            posted_at_text="30m",
            visible_text=media_text,
        )
        captured_at = datetime.now(UTC)
        return (
            (
                CommentThread(comment=top, replies=(reply,)),
                CommentThread(comment=media),
            ),
            PostCommentsCoverage(
                post_ref=request.post_ref,
                discussion_post_ref=request.post_ref,
                sort_by=request.sort_by,
                expansion_rounds=1,
                top_level_visible=2,
                top_level_returned=2,
                replies_visible=1,
                replies_returned=1,
                max_comments=request.max_comments,
                max_replies_per_comment=request.max_replies_per_comment,
                truncated=False,
                captured_at=captured_at,
            ),
            f"{top_text}\n{reply_text}\n{media_text}",
            f"https://www.linkedin.com/feed/update/urn:li:{request.post_ref}/",
        )


class ProtocolNetwork:
    async def collect(
        self,
        request: InvitationListInput | ConnectionsListInput | ConversationSearchInput,
        *,
        result_limit: int | None = None,
        progress: object | None = None,
    ) -> (
        tuple[tuple[InvitationSummary, ...], InvitationListCoverage, str, str]
        | tuple[tuple[ConnectionSummary, ...], ConnectionsListCoverage, str, str]
        | tuple[tuple[ConversationSummary, ...], ConversationSearchCoverage, str, str]
    ):
        del result_limit, progress
        captured_at = datetime.now(UTC)
        if isinstance(request, InvitationListInput):
            source_url = "https://www.linkedin.com/mynetwork/invitation-manager/"
            text = "Jane Doe\nStaff Engineer\nHi, let us connect.\nAccept"
            item = InvitationSummary(
                invitation_ref="invitation:" + "a" * 24,
                direction=request.direction,
                invitation_type=InvitationType.CONNECTION_REQUEST,
                primary_entity=InvitationEntity(
                    entity_ref="person:jane-doe",
                    entity_type=InvitationEntityType.PERSON,
                    entity_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
                    display_name="Jane Doe",
                    slug="jane-doe",
                ),
                headline="Staff Engineer",
                note="Hi, let us connect.",
                available_actions=(
                    InvitationAvailableAction.IGNORE,
                    InvitationAvailableAction.ACCEPT,
                ),
                visible_text=text,
                evidence=(
                    InvitationEvidence(
                        field="primary_entity.display_name",
                        quote="Jane Doe",
                        source_url=HttpUrl(source_url),
                        captured_at=captured_at,
                    ),
                ),
            )
            return (
                (item,),
                InvitationListCoverage(
                    direction=request.direction,
                    invitation_filter=request.resolved_filter,
                    advertised_count=(
                        None if request.resolved_filter is InvitationFilter.ALL else 1
                    ),
                    unique_count=1,
                    view_counts=(
                        {
                            invitation_filter: (
                                1 if invitation_filter is InvitationFilter.FOCUSED else 0
                            )
                            for invitation_filter in CURRENT_RECEIVED_INVITATION_VIEWS
                        }
                        if request.resolved_filter is InvitationFilter.ALL
                        else {request.resolved_filter: 1}
                    ),
                    view_source_urls=(
                        {
                            invitation_filter: HttpUrl(source_url)
                            for invitation_filter in CURRENT_RECEIVED_INVITATION_VIEWS
                        }
                        if request.resolved_filter is InvitationFilter.ALL
                        else {request.resolved_filter: HttpUrl(source_url)}
                    ),
                    view_membership_count=1,
                    overlap_count=0,
                    snapshot_count=1,
                    returned_count=1,
                    scroll_rounds=1,
                    collection_attempts=1,
                    neighboring_recommendation_count=0,
                    invitation_type_counts={InvitationType.CONNECTION_REQUEST: 1},
                    entity_type_counts={InvitationEntityType.PERSON: 1},
                    completion_reason=(
                        "visible_view_union_reconciled"
                        if request.resolved_filter is InvitationFilter.ALL
                        else "advertised_count_reconciled"
                    ),
                    captured_at=captured_at,
                ),
                text,
                source_url,
            )
        if isinstance(request, ConnectionsListInput):
            text = "Jane Doe\nStaff Engineer\nMessage"
            item = ConnectionSummary(
                profile_slug="jane-doe",
                profile_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
                name="Jane Doe",
                headline="Staff Engineer",
                visible_text=text,
            )
            return (
                (item,),
                ConnectionsListCoverage(
                    sort_by=request.sort_by,
                    rounds_visited=1,
                    result_count=1,
                    max_results=request.max_results,
                    stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
                    captured_at=captured_at,
                ),
                text,
                "https://www.linkedin.com/mynetwork/invite-connect/connections/",
            )
        text = "Jane Doe\nCan we discuss the role?"
        item = ConversationSummary(
            conversation_ref="conversation:" + "c" * 24,
            conversation_id="thread-123",
            participant_profile_slug="jane-doe",
            participant_profile_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
            participant_name="Jane Doe",
            last_message_text="Can we discuss the role?",
            unread=True,
            visible_text=text,
        )
        return (
            (item,),
            ConversationSearchCoverage(
                query=request.query,
                category=request.resolved_category,
                filter=request.filter,
                rounds_visited=1,
                result_count=1,
                max_results=request.max_results,
                stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=captured_at,
            ),
            text,
            "https://www.linkedin.com/messaging/",
        )

    async def prepare_send(
        self,
        request: InvitationSendPrepareInput,
    ) -> ActionPreparationCapture:
        return self._capture(request.profile_slug)

    async def prepare_accept(
        self,
        request: InvitationAcceptPrepareInput,
    ) -> ActionPreparationCapture:
        capture = self._capture(request.profile_slug)
        return capture.model_copy(
            update={
                "target": capture.target.model_copy(
                    update={"invitation_ref": "invitation:" + "a" * 24}
                ),
                "current_state": "received_invitation_pending",
            }
        )

    async def prepare_ignore(
        self,
        request: InvitationIgnorePrepareInput,
    ) -> ActionPreparationCapture:
        capture = self._capture(request.profile_slug)
        return capture.model_copy(
            update={
                "target": capture.target.model_copy(
                    update={"invitation_ref": "invitation:" + "a" * 24}
                ),
                "current_state": "received_invitation_pending",
            }
        )

    async def execute_send(self, draft: ActionDraft) -> ActionPageResult:
        return self._result("pending_sent")

    async def execute_accept(self, draft: ActionDraft) -> ActionPageResult:
        return self._result("connected")

    async def execute_ignore(self, draft: ActionDraft) -> ActionPageResult:
        return self._result("invitation_ignored")

    async def read(self, request: ConversationGetInput) -> ConversationObservation:
        captured_at = datetime.now(UTC)
        text = "Jane Doe\nCan we discuss the role?"
        message = MessageObservation(
            message_ref="message:" + "a" * 24,
            direction=MessageDirection.INCOMING,
            sender_name="Jane Doe",
            text="Can we discuss the role?",
            visible_text=text,
        )
        return ConversationObservation(
            conversation_ref=request.conversation_ref,
            conversation_id=request.conversation_id or "thread-123",
            participant_profile_slug=request.profile_slug or "jane-doe",
            participant_profile_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
            participant_name="Jane Doe",
            messages=(message,),
            visible_text=text,
            coverage=ConversationCoverage(
                messages_observed=1,
                messages_returned=1,
                max_messages=request.max_messages,
                rounds_visited=1,
                stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
                history_complete=True,
                truncated=False,
                captured_at=captured_at,
            ),
            captured_at=captured_at,
        )

    async def prepare_message(
        self,
        request: MessagePrepareInput,
    ) -> ActionPreparationCapture:
        capture = self._capture(request.profile_slug or "jane-doe")
        return capture.model_copy(
            update={
                "target": capture.target.model_copy(
                    update={"conversation_id": request.conversation_id or "thread-123"}
                ),
                "current_state": "message_composer_available",
                "source_url": HttpUrl("https://www.linkedin.com/messaging/thread/thread-123/"),
            }
        )

    async def prepare_message_assets(
        self,
        request: MessagePrepareInput,
    ) -> tuple[PreparedPostAsset, ...]:
        return tuple(
            PreparedPostAsset(
                asset_ref=attachment.asset_ref,
                role=PostAssetRole.MESSAGE_ATTACHMENT,
                sha256="e" * 64,
                size_bytes=128,
                media_type="application/pdf",
            )
            for attachment in request.attachments
        )

    async def execute_message(self, draft: ActionDraft) -> ActionPageResult:
        return self._result("message_sent")

    async def prepare_assets(
        self,
        request: PostCreatePrepareInput,
    ) -> tuple[PreparedPostAsset, ...]:
        del request
        return ()

    async def prepare_post(
        self,
        request: PostCreatePrepareInput,
    ) -> ActionPreparationCapture:
        del request
        capture = self._capture("current-member")
        return capture.model_copy(
            update={
                "target": capture.target.model_copy(
                    update={
                        "actor_profile_slug": "current-member",
                        "actor_profile_url": HttpUrl("https://www.linkedin.com/in/current-member/"),
                        "actor_display_name": "Jane Doe",
                    }
                ),
                "current_state": "personal_post_composer_ready:text:anyone:anyone:immediate",
                "source_url": HttpUrl("https://www.linkedin.com/feed/"),
            }
        )

    async def execute_post(self, draft: ActionDraft) -> ActionPageResult:
        del draft
        return self._result("post_published:activity:7312345678901234567")

    async def prepare_comment_assets(
        self,
        request: PostCommentPrepareInput,
    ) -> tuple[PreparedPostAsset, ...]:
        del request
        return ()

    async def prepare_comment(
        self,
        request: PostCommentPrepareInput,
    ) -> ActionPreparationCapture:
        capture = self._capture("current-member")
        return capture.model_copy(
            update={
                "target": capture.target.model_copy(
                    update={
                        "actor_profile_slug": "current-member",
                        "actor_profile_url": HttpUrl("https://www.linkedin.com/in/current-member/"),
                        "actor_display_name": "Jane Doe",
                        "post_ref": request.post_ref,
                        "post_url": HttpUrl(
                            "https://www.linkedin.com/feed/update/"
                            "urn:li:activity:7312345678901234567/"
                        ),
                        "comment_ref": request.parent_comment_ref,
                        "content_author_name": (
                            "Alex Ray" if request.parent_comment_ref else "Jane Doe"
                        ),
                        "content_author_url": HttpUrl(
                            "https://www.linkedin.com/in/"
                            f"{'alex-ray' if request.parent_comment_ref else 'jane-doe'}/"
                        ),
                    }
                ),
                "current_state": (
                    "reply_composer_ready"
                    if request.parent_comment_ref
                    else "comment_composer_ready"
                ),
                "source_url": HttpUrl(
                    "https://www.linkedin.com/feed/update/urn:li:activity:7312345678901234567/"
                ),
            }
        )

    async def execute_comment(self, draft: ActionDraft) -> ActionPageResult:
        del draft
        return self._result("reply_published:comment:activity:7312345678901234567:900")

    async def prepare_reaction(
        self,
        request: PostReactionPrepareInput,
    ) -> ActionPreparationCapture:
        capture = await self.prepare_comment(
            PostCommentPrepareInput(
                context_id=request.context_id,
                request_id=request.request_id,
                post_ref=request.post_ref,
                parent_comment_ref=request.comment_ref,
                text="typed protocol preparation",
            )
        )
        return capture.model_copy(
            update={
                "current_state": "reaction_ready",
                "existing_reaction": (
                    ReactionState.LIKE if request.comment_ref else ReactionState.NONE
                ),
            }
        )

    async def execute_reaction(self, draft: ActionDraft) -> ActionPageResult:
        assert isinstance(draft.payload, ReactionSetPayload)
        return self._result(f"reaction_set:{draft.payload.desired_reaction.value}")

    @staticmethod
    def _capture(profile_slug: str) -> ActionPreparationCapture:
        return ActionPreparationCapture(
            target=ActionTarget(
                profile_slug=profile_slug,
                profile_url=HttpUrl(f"https://www.linkedin.com/in/{profile_slug}/"),
                display_name="Jane Doe",
            ),
            current_state="connect_available",
            source_url=HttpUrl(f"https://www.linkedin.com/in/{profile_slug}/"),
            captured_text="Jane Doe\nStaff Engineer\nConnect",
            captured_at=datetime.now(UTC),
        )

    @staticmethod
    def _result(state: str) -> ActionPageResult:
        return ActionPageResult(
            outcome=ActionOutcome.VERIFIED,
            performed=True,
            final_state=state,
            detail=f"Visible state: {state}",
            source_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
            captured_text=f"Jane Doe\n{state}",
            captured_at=datetime.now(UTC),
        )


def _container() -> AppContainer:
    settings = Settings(
        live_enabled=True,
        auto_login_on_start=False,
        browser_auto_install=False,
        browser_profile_path=ROOT / ".pytest_cache" / f"profile-{uuid.uuid4().hex}",
        minimum_navigation_interval_seconds=0,
        runtime_lock_path=ROOT / ".pytest_cache" / f"runtime-{uuid.uuid4().hex}.lock",
        allowed_surfaces=frozenset(LinkedInSurface),
        allowed_scopes=frozenset(
            {
                "linkedin.jobs.search",
                "linkedin.jobs.read",
                "linkedin.people.search",
                "linkedin.people.read",
                "linkedin.companies.search",
                "linkedin.companies.read",
                "linkedin.posts.search",
                "linkedin.posts.read",
                "linkedin.posts.comments.read",
                "linkedin.posts.comments.create",
                "linkedin.posts.reactions.set",
                "linkedin.posts.create",
                "linkedin.connections.read",
                "linkedin.invitations.read",
                "linkedin.invitations.send",
                "linkedin.invitations.accept",
                "linkedin.invitations.ignore",
                "linkedin.messaging.read",
                "linkedin.messaging.send",
            }
        ),
        allowed_effects=frozenset(CapabilityEffect),
    )
    repository = MemoryRepository()
    registry = create_default_registry()
    browser = BrowserManager(settings)
    network = ProtocolNetwork()
    executor = CapabilityExecutor(
        settings=settings,
        registry=registry,
        repository=repository,
        job_search=ProtocolJobSearch(),
        job_detail=ProtocolJobDetail(),
        people_search=ProtocolPeopleSearch(),
        person_profile=ProtocolPersonProfile(),
        company_search=ProtocolCompanySearch(),
        company_profile=ProtocolCompanyProfile(),
        post_search=cast(PostSearchProvider, ProtocolPostSearch()),
        post_detail=cast(PostDetailProvider, ProtocolPostDetail()),
        post_comments=cast(PostCommentsProvider, ProtocolPostComments()),
        post_publishing=cast(PostPublishingProvider, network),
        post_engagement=cast(PostEngagementProvider, network),
        invitation_list=cast(InvitationListProvider, network),
        connections_list=cast(ConnectionsListProvider, network),
        invitation_actions=cast(InvitationActionProvider, network),
        conversation_search=cast(ConversationSearchProvider, network),
        conversation=cast(ConversationProvider, network),
    )
    worker = CapabilityWorker(executor, queue_capacity=settings.queue_capacity)
    return AppContainer(
        settings=settings,
        registry=registry,
        repository=repository,
        browser=browser,
        executor=executor,
        worker=worker,
        process_lock=AccountProcessLock(settings.runtime_lock_path),
    )


@pytest.mark.asyncio
async def test_mcp_client_discovers_calls_and_reads_evidence() -> None:
    container = _container()
    mcp = create_mcp_server(container)
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[
        SessionMessage
    ](20)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[
        SessionMessage
    ](20)

    async def run_server() -> None:
        await mcp._mcp_server.run(  # pyright: ignore[reportPrivateUsage]
            client_to_server_receive,
            server_to_client_send,
            mcp._mcp_server.create_initialization_options(),  # pyright: ignore[reportPrivateUsage]
            raise_exceptions=True,
        )

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(run_server)
        async with ClientSession(server_to_client_receive, client_to_server_send) as session:
            initialized = await session.initialize()
            assert initialized.serverInfo.name == "linkedin-mcp-server"

            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {
                "linkedin.server.status",
                "linkedin.capabilities.list",
                "linkedin.session.status",
                "linkedin.jobs.search",
                "linkedin.jobs.get",
                "linkedin.people.search",
                "linkedin.people.get",
                "linkedin.companies.search",
                "linkedin.companies.get",
                "linkedin.posts.search",
                "linkedin.posts.get",
                "linkedin.posts.comments.list",
                "linkedin.posts.create.prepare",
                "linkedin.posts.create.execute",
                "linkedin.posts.comment.prepare",
                "linkedin.posts.comment.execute",
                "linkedin.posts.reaction.prepare",
                "linkedin.posts.reaction.execute",
                "linkedin.invitations.list",
                "linkedin.connections.list",
                "linkedin.connections.search",
                "linkedin.invitations.send.prepare",
                "linkedin.invitations.send.execute",
                "linkedin.invitations.accept.prepare",
                "linkedin.invitations.accept.execute",
                "linkedin.invitations.ignore.prepare",
                "linkedin.invitations.ignore.execute",
                "linkedin.messaging.search",
                "linkedin.messaging.conversation.get",
                "linkedin.messaging.message.prepare",
                "linkedin.messaging.message.execute",
            }.issubset(names)
            paginated_tool_names = (
                "linkedin.jobs.search",
                "linkedin.people.search",
                "linkedin.companies.search",
                "linkedin.posts.search",
                "linkedin.posts.comments.list",
                "linkedin.invitations.list",
                "linkedin.connections.list",
                "linkedin.connections.search",
                "linkedin.messaging.search",
            )
            for paginated_tool_name in paginated_tool_names:
                paginated_tool = next(
                    tool for tool in tools.tools if tool.name == paginated_tool_name
                )
                input_properties = paginated_tool.inputSchema["properties"]
                assert {"page_size", "cursor"}.issubset(input_properties)
                assert "page_limit" not in input_properties
                assert input_properties["page_size"]["minimum"] == 1
                assert input_properties["page_size"]["maximum"] == 100
                assert paginated_tool.outputSchema is not None
                assert "pagination" in paginated_tool.outputSchema["properties"]
                assert {
                    "scan_id",
                    "page_size",
                    "returned_count",
                    "cumulative_count",
                    "has_more",
                    "next_cursor",
                    "cursor_expires_at",
                    "truncated",
                    "consistency",
                } == set(paginated_tool.outputSchema["$defs"]["PaginationMetadata"]["properties"])
            invite_execute_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.invitations.send.execute"
            )
            assert invite_execute_tool.annotations is not None
            assert invite_execute_tool.annotations.readOnlyHint is False
            assert invite_execute_tool.annotations.destructiveHint is True
            assert invite_execute_tool.annotations.idempotentHint is True
            execute_fields = {
                "context_id",
                "request_id",
                "action_id",
                "payload_hash",
                "approval_preview",
                "idempotency_key",
            }
            assert execute_fields == set(invite_execute_tool.inputSchema["properties"])
            post_prepare_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.posts.create.prepare"
            )
            post_execute_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.posts.create.execute"
            )
            assert post_prepare_tool.annotations is not None
            assert post_prepare_tool.annotations.destructiveHint is False
            assert post_execute_tool.annotations is not None
            assert post_execute_tool.annotations.destructiveHint is True
            assert {
                "context_id",
                "request_id",
                "content",
                "audience",
                "group_target",
                "comment_control",
                "brand_partnership",
                "collaborators",
                "scheduled_at",
            } == set(post_prepare_tool.inputSchema["properties"])
            content_schema = post_prepare_tool.inputSchema["properties"]["content"]
            assert "oneOf" in content_schema
            assert len(content_schema["oneOf"]) == 9
            assert execute_fields == set(post_execute_tool.inputSchema["properties"])
            comment_prepare_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.posts.comment.prepare"
            )
            comment_execute_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.posts.comment.execute"
            )
            reaction_prepare_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.posts.reaction.prepare"
            )
            reaction_execute_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.posts.reaction.execute"
            )
            assert comment_prepare_tool.annotations is not None
            assert comment_prepare_tool.annotations.destructiveHint is False
            assert comment_execute_tool.annotations is not None
            assert comment_execute_tool.annotations.destructiveHint is True
            assert reaction_prepare_tool.annotations is not None
            assert reaction_prepare_tool.annotations.destructiveHint is False
            assert reaction_execute_tool.annotations is not None
            assert reaction_execute_tool.annotations.destructiveHint is True
            assert {
                "context_id",
                "request_id",
                "post_ref",
                "parent_comment_ref",
                "text",
                "mentions",
                "attachment",
            } == set(comment_prepare_tool.inputSchema["properties"])
            assert {
                "context_id",
                "request_id",
                "post_ref",
                "desired_reaction",
                "comment_ref",
            } == set(reaction_prepare_tool.inputSchema["properties"])
            reaction_values = reaction_prepare_tool.inputSchema["$defs"]["ReactionState"]["enum"]
            assert {
                "none",
                "like",
                "celebrate",
                "support",
                "love",
                "insightful",
                "funny",
            } == set(reaction_values)
            assert execute_fields == set(comment_execute_tool.inputSchema["properties"])
            assert execute_fields == set(reaction_execute_tool.inputSchema["properties"])
            execute_tools = tuple(
                tool
                for tool in tools.tools
                if tool.name
                in {
                    "linkedin.posts.create.execute",
                    "linkedin.posts.comment.execute",
                    "linkedin.posts.reaction.execute",
                    "linkedin.invitations.send.execute",
                    "linkedin.invitations.accept.execute",
                    "linkedin.invitations.ignore.execute",
                    "linkedin.messaging.message.execute",
                }
            )
            assert len(execute_tools) == 7
            for execute_tool in execute_tools:
                assert execute_tool.annotations is not None
                assert execute_tool.annotations.readOnlyHint is False
                assert execute_tool.annotations.destructiveHint is True
                assert execute_tool.annotations.idempotentHint is True
                assert execute_fields == set(execute_tool.inputSchema["properties"])
            conversation_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.messaging.conversation.get"
            )
            invitations_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.invitations.list"
            )
            inbox_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.messaging.search"
            )
            message_prepare_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.messaging.message.prepare"
            )
            assert "invitation_filter" in invitations_tool.inputSchema["properties"]
            assert {
                "all",
                "focused",
                "other",
                "verified",
                "same_company",
                "same_school",
                "mutual_connections",
                "people",
            } == set(invitations_tool.inputSchema["$defs"]["InvitationFilter"]["enum"])
            assert invitations_tool.outputSchema is not None
            invitation_output_schema = cast(
                dict[str, object],
                invitations_tool.outputSchema,
            )
            invitation_output_defs = cast(
                dict[str, dict[str, object]],
                invitation_output_schema["$defs"],
            )
            invitation_coverage_properties = cast(
                dict[str, object],
                invitation_output_defs["InvitationListCoverage"]["properties"],
            )
            assert {
                "advertised_count",
                "unique_count",
                "view_counts",
                "view_source_urls",
                "view_membership_count",
                "overlap_count",
                "snapshot_count",
                "returned_count",
                "scroll_rounds",
                "collection_attempts",
                "neighboring_recommendation_count",
                "invitation_type_counts",
                "entity_type_counts",
                "completion_reason",
            }.issubset(invitation_coverage_properties)
            invitation_summary_properties = cast(
                dict[str, object],
                invitation_output_defs["InvitationSummary"]["properties"],
            )
            assert {
                "invitation_type",
                "primary_entity",
                "inviter",
                "available_actions",
                "evidence",
            }.issubset(invitation_summary_properties)
            assert "inventory" not in invitation_coverage_properties
            assert {"query", "category", "filter"}.issubset(inbox_tool.inputSchema["properties"])
            assert "filters" not in inbox_tool.inputSchema["properties"]
            assert "unread_only" not in inbox_tool.inputSchema["properties"]
            assert "linkedin.messaging.conversations.list" not in names
            assert {
                "jobs",
                "unread",
                "connections",
                "starred",
                "inmail",
            } == set(inbox_tool.inputSchema["$defs"]["ConversationFilter"]["enum"])
            assert "conversation_ref" in conversation_tool.inputSchema["properties"]
            assert "conversation_ref" in message_prepare_tool.inputSchema["properties"]
            assert {"message", "attachments", "gif", "reply_to_message_ref"}.issubset(
                message_prepare_tool.inputSchema["properties"]
            )
            search_tool = next(tool for tool in tools.tools if tool.name == "linkedin.jobs.search")
            assert search_tool.annotations is not None
            assert search_tool.annotations.readOnlyHint is True
            assert search_tool.outputSchema is not None
            assert "page_limit" not in search_tool.inputSchema["properties"]
            assert "filters" in search_tool.inputSchema["properties"]
            assert "query" not in search_tool.inputSchema.get("required", [])
            filter_properties = search_tool.inputSchema["$defs"]["JobSearchFilters"]["properties"]
            assert {
                "sort_by",
                "location_geo_id",
                "distance_miles",
                "workplace_types",
                "experience_levels",
                "employment_types",
                "location_ids",
                "location_names",
                "company_ids",
                "company_names",
                "industry_ids",
                "industry_names",
                "job_function_ids",
                "job_function_names",
                "job_title_ids",
                "job_title_names",
                "benefits",
                "commitments",
                "easy_apply_only",
                "has_verifications",
                "under_10_applicants",
                "in_your_network",
                "fair_chance_employer",
            } == set(filter_properties)
            search_output_defs = cast(
                dict[str, dict[str, object]],
                search_tool.outputSchema["$defs"],
            )
            job_summary_properties = cast(
                dict[str, object],
                search_output_defs["JobSummary"]["properties"],
            )
            assert {
                "workplace_type",
                "easy_apply",
                "verified",
                "promoted",
                "insights",
                "evidence",
            }.issubset(job_summary_properties)
            search_coverage_properties = cast(
                dict[str, object],
                search_output_defs["JobSearchCoverage"]["properties"],
            )
            assert {
                "advertised_result_count",
                "advertised_result_count_is_lower_bound",
            }.issubset(search_coverage_properties)

            job_detail_tool = next(tool for tool in tools.tools if tool.name == "linkedin.jobs.get")
            assert job_detail_tool.outputSchema is not None
            detail_output_defs = cast(
                dict[str, dict[str, object]],
                job_detail_tool.outputSchema["$defs"],
            )
            job_detail_properties = cast(
                dict[str, object],
                detail_output_defs["JobDetailObservation"]["properties"],
            )
            assert {
                "workplace_type",
                "apply_method",
                "promoted",
                "insights",
                "hiring_team",
                "description_text",
                "evidence",
            }.issubset(job_detail_properties)

            people_search_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.people.search"
            )
            assert people_search_tool.annotations is not None
            assert people_search_tool.annotations.readOnlyHint is True
            assert people_search_tool.outputSchema is not None
            assert "page_limit" not in people_search_tool.inputSchema["properties"]
            assert "filters" in people_search_tool.inputSchema["properties"]
            people_filter_properties = people_search_tool.inputSchema["$defs"][
                "PeopleSearchFilters"
            ]["properties"]
            assert {
                "connection_degrees",
                "actively_hiring",
                "actively_hiring_job_title_ids",
                "actively_hiring_job_title_names",
                "location_ids",
                "location_names",
                "current_company_ids",
                "current_company_names",
                "connections_of_ids",
                "connections_of_names",
                "followers_of_ids",
                "followers_of_names",
                "past_company_ids",
                "past_company_names",
                "school_ids",
                "school_names",
                "industry_ids",
                "industry_names",
                "profile_language_ids",
                "profile_language_names",
                "service_category_ids",
                "service_category_names",
                "first_name",
                "last_name",
                "title",
                "company",
                "school",
            } == set(people_filter_properties)
            connections_search_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.connections.search"
            )
            connections_list_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.connections.list"
            )
            assert connections_search_tool.annotations is not None
            assert connections_search_tool.annotations.readOnlyHint is True
            connection_filter_properties = connections_search_tool.inputSchema["$defs"][
                "ConnectionsSearchFilters"
            ]["properties"]
            assert set(connection_filter_properties) == set(people_filter_properties) - {
                "connection_degrees"
            }
            assert "query" not in connections_list_tool.inputSchema["properties"]
            assert "filters" not in connections_list_tool.inputSchema["properties"]
            assert "sort_by" in connections_list_tool.inputSchema["properties"]
            assert connections_search_tool.outputSchema is not None
            assert "people" in connections_search_tool.outputSchema["properties"]
            assert "connections" not in connections_search_tool.outputSchema["properties"]
            people_get_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.people.get"
            )
            assert (
                people_get_tool.inputSchema["properties"]["profile_slug"]["pattern"]
                == PROFILE_SLUG_PATTERN
            )
            for profile_target_tool_name in (
                "linkedin.invitations.send.prepare",
                "linkedin.invitations.accept.prepare",
                "linkedin.invitations.ignore.prepare",
                "linkedin.messaging.conversation.get",
                "linkedin.messaging.message.prepare",
            ):
                profile_target_tool = next(
                    tool for tool in tools.tools if tool.name == profile_target_tool_name
                )
                profile_slug_schema = profile_target_tool.inputSchema["properties"]["profile_slug"]
                if "anyOf" in profile_slug_schema:
                    profile_slug_schema = profile_slug_schema["anyOf"][0]
                assert profile_slug_schema["pattern"] == PROFILE_SLUG_PATTERN
            assert "sections" in people_get_tool.inputSchema["properties"]
            section_values = people_get_tool.inputSchema["$defs"]["PersonProfileSectionSelector"][
                "enum"
            ]
            assert {
                "all",
                "overview",
                "about",
                "experience",
                "education",
                "licenses-certifications",
                "projects",
                "volunteering",
                "skills",
                "interests",
                "featured",
                "courses",
                "honors-awards",
                "languages",
                "organizations",
                "publications",
                "patents",
                "recommendations",
                "test-scores",
            } == set(section_values)

            company_search_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.companies.search"
            )
            assert company_search_tool.annotations is not None
            assert company_search_tool.annotations.readOnlyHint is True
            company_filter_properties = company_search_tool.inputSchema["$defs"][
                "CompanySearchFilters"
            ]["properties"]
            assert {
                "location_ids",
                "location_names",
                "industry_ids",
                "industry_names",
                "company_sizes",
                "has_job_listings",
                "has_first_degree_connections",
            } == set(company_filter_properties)
            company_get_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.companies.get"
            )
            assert "sections" not in company_get_tool.inputSchema["properties"]
            assert company_get_tool.outputSchema is not None
            company_profile_coverage = company_get_tool.outputSchema["$defs"][
                "CompanyProfileCoverage"
            ]["properties"]
            assert company_profile_coverage["pages_visited"]["const"] == 2

            post_search_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.posts.search"
            )
            assert post_search_tool.annotations is not None
            assert post_search_tool.annotations.readOnlyHint is True
            assert "page_limit" not in post_search_tool.inputSchema["properties"]
            post_filter_properties = post_search_tool.inputSchema["$defs"]["PostSearchFilters"][
                "properties"
            ]
            assert {
                "sort_by",
                "date_posted",
                "content_type",
                "from_member_ids",
                "from_member_names",
                "from_company_ids",
                "from_company_names",
                "posted_by",
                "mentioning_member_ids",
                "mentioning_member_names",
                "mentioning_company_ids",
                "mentioning_company_names",
                "author_industry_ids",
                "author_industry_names",
                "author_company_ids",
                "author_company_names",
                "author_keywords",
            } == set(post_filter_properties)
            assert post_search_tool.inputSchema["$defs"]["PostSearchContentType"]["enum"] == [
                "videos",
                "images",
                "job_posts",
                "live_videos",
                "documents",
            ]
            assert post_search_tool.inputSchema["$defs"]["PostSearchPostedBy"]["enum"] == [
                "me",
                "first_connections",
                "people_you_follow",
            ]
            post_comments_tool = next(
                tool for tool in tools.tools if tool.name == "linkedin.posts.comments.list"
            )
            assert post_comments_tool.outputSchema is not None
            comment_output_defs = post_comments_tool.outputSchema["$defs"]
            comment_properties = comment_output_defs["CommentObservation"]["properties"]
            assert {"text", "attachments", "visible_text"}.issubset(comment_properties)
            assert {
                "attachment_type",
                "accessible_label",
                "resource_url",
                "visible_text",
            } == set(comment_output_defs["CommentAttachmentObservation"]["properties"])
            assert {"photo", "gif"} == set(comment_output_defs["CommentAttachmentType"]["enum"])
            for read_tool_name in (
                "linkedin.posts.get",
                "linkedin.posts.comments.list",
            ):
                read_tool = next(tool for tool in tools.tools if tool.name == read_tool_name)
                assert read_tool.annotations is not None
                assert read_tool.annotations.readOnlyHint is True

            session_status = await session.call_tool("linkedin.session.status", {})
            assert session_status.isError is False
            assert session_status.structuredContent is not None
            assert session_status.structuredContent["authentication_state"] == "login_required"
            assert session_status.structuredContent["automatic_login_enabled"] is False
            assert session_status.structuredContent["login_browser_open"] is False

            direct_detail = await session.call_tool(
                "linkedin.jobs.get",
                {
                    "context_id": "direct-context",
                    "request_id": "direct-detail-request",
                    "job_id": "4100000001",
                },
            )
            assert direct_detail.isError is False
            assert direct_detail.structuredContent is not None
            assert direct_detail.structuredContent["job"]["job_id"] == "4100000001"

            search_result = await session.call_tool(
                "linkedin.jobs.search",
                {
                    "context_id": "context-1",
                    "request_id": "request-1",
                    "query": "python",
                    "filters": {
                        "sort_by": "most_recent",
                        "workplace_types": ["remote", "hybrid"],
                        "experience_levels": ["entry_level", "associate"],
                        "employment_types": ["full_time", "contract"],
                        "easy_apply_only": True,
                        "under_10_applicants": True,
                    },
                    "max_results": 10,
                },
            )
            assert search_result.isError is False
            assert search_result.structuredContent is not None
            structured = TypeAdapter(dict[str, object]).validate_python(
                search_result.structuredContent
            )
            coverage = TypeAdapter(dict[str, object]).validate_python(structured["coverage"])
            filters = TypeAdapter(dict[str, object]).validate_python(coverage["filters"])
            assert filters["sort_by"] == "most_recent"
            assert filters["workplace_types"] == ["remote", "hybrid"]
            assert filters["easy_apply_only"] is True
            assert filters["under_10_applicants"] is True
            sources = TypeAdapter(list[dict[str, object]]).validate_python(structured["sources"])
            source_id = sources[0]["source_id"]
            assert isinstance(source_id, str)

            resource = await session.read_resource(AnyUrl(f"linkedin://sources/{source_id}"))
            assert len(resource.contents) == 1
            assert isinstance(resource.contents[0], TextResourceContents)
            source = json.loads(resource.contents[0].text)
            assert source["source_id"] == source_id
            assert "Senior Python Engineer" in source["captured_text"]

            people_result = await session.call_tool(
                "linkedin.people.search",
                {
                    "context_id": "people-context",
                    "request_id": "people-search-request",
                    "query": '"distributed systems" AND Python',
                    "title_keywords": "staff engineer",
                    "filters": {
                        "connection_degrees": ["second"],
                        "location_ids": ["102713980"],
                        "current_company_ids": ["1441"],
                        "school_names": ["Stanford University"],
                        "industry_ids": ["4"],
                    },
                    "max_results": 10,
                },
            )
            assert people_result.isError is False
            assert people_result.structuredContent is not None
            assert people_result.structuredContent["people"][0]["profile_slug"] == "jane-doe"
            people_coverage = TypeAdapter(dict[str, object]).validate_python(
                people_result.structuredContent["coverage"]
            )
            people_filters = TypeAdapter(dict[str, object]).validate_python(
                people_coverage["filters"]
            )
            assert people_filters["connection_degrees"] == ["second"]
            assert people_filters["current_company_ids"] == ["1441"]
            assert people_filters["school_names"] == ["Stanford University"]

            profile_result = await session.call_tool(
                "linkedin.people.get",
                {
                    "context_id": "people-context",
                    "request_id": "person-get-request",
                    "profile_slug": "jane-doe",
                    "sections": ["overview", "skills"],
                },
            )
            assert profile_result.isError is False
            assert profile_result.structuredContent is not None
            assert profile_result.structuredContent["person"]["name"] == "Jane Doe"
            assert profile_result.structuredContent["person"]["coverage"]["requested_sections"] == [
                "overview",
                "skills",
            ]
            profile_sources = TypeAdapter(list[dict[str, object]]).validate_python(
                profile_result.structuredContent["sources"]
            )
            profile_source_id = profile_sources[0]["source_id"]
            assert isinstance(profile_source_id, str)
            profile_resource = await session.read_resource(
                AnyUrl(f"linkedin://sources/{profile_source_id}")
            )
            assert isinstance(profile_resource.contents[0], TextResourceContents)
            assert "Builds reliable systems." in profile_resource.contents[0].text

            company_search_result = await session.call_tool(
                "linkedin.companies.search",
                {
                    "context_id": "company-context",
                    "request_id": "company-search-request",
                    "query": "cloud infrastructure",
                    "filters": {
                        "location_ids": ["102713980"],
                        "industry_names": ["Software Development"],
                        "company_sizes": ["1001-5000"],
                    },
                    "max_results": 10,
                },
            )
            assert company_search_result.isError is False
            assert company_search_result.structuredContent is not None
            assert (
                company_search_result.structuredContent["companies"][0]["company_slug"]
                == "acme-cloud"
            )
            assert company_search_result.structuredContent["coverage"]["filters"][
                "company_sizes"
            ] == ["1001-5000"]

            company_result = await session.call_tool(
                "linkedin.companies.get",
                {
                    "context_id": "company-context",
                    "request_id": "company-get-request",
                    "company_slug": "acme-cloud",
                },
            )
            assert company_result.isError is False
            assert company_result.structuredContent is not None
            assert company_result.structuredContent["company"]["name"] == "Acme Cloud"
            assert company_result.structuredContent["company"]["company_size_range"] == (
                "1,001-5,000 employees"
            )
            assert company_result.structuredContent["company"]["coverage"]["returned_sections"] == [
                "overview",
                "about",
            ]

            post_search_result = await session.call_tool(
                "linkedin.posts.search",
                {
                    "context_id": "post-context",
                    "request_id": "post-search-request",
                    "query": "python reliability",
                    "filters": {
                        "sort_by": "latest",
                        "date_posted": "past_week",
                        "content_type": "documents",
                        "from_company_ids": ["12345"],
                        "posted_by": ["first_connections"],
                        "mentioning_member_names": ["Jane Doe"],
                        "author_industry_ids": ["4"],
                        "author_keywords": "Staff Engineer",
                    },
                    "max_results": 10,
                },
            )
            assert post_search_result.isError is False
            assert post_search_result.structuredContent is not None
            post_ref = post_search_result.structuredContent["posts"][0]["post_ref"]
            assert post_ref == "activity:7312345678901234567"
            assert post_search_result.structuredContent["coverage"]["filters"]["sort_by"] == (
                "latest"
            )

            post_detail_result = await session.call_tool(
                "linkedin.posts.get",
                {
                    "context_id": "post-context",
                    "request_id": "post-get-request",
                    "post_ref": post_ref,
                },
            )
            post_comments_result = await session.call_tool(
                "linkedin.posts.comments.list",
                {
                    "context_id": "post-context",
                    "request_id": "post-comments-request",
                    "post_ref": post_ref,
                    "sort_by": "most_recent",
                    "max_comments": 10,
                    "max_replies_per_comment": 5,
                },
            )
            assert post_detail_result.isError is False
            assert post_comments_result.isError is False
            assert post_detail_result.structuredContent is not None
            assert post_comments_result.structuredContent is not None
            assert post_detail_result.structuredContent["post"]["text"] == (
                "A practical Python post."
            )
            assert (
                post_comments_result.structuredContent["threads"][0]["replies"][0][
                    "parent_comment_ref"
                ]
                == post_comments_result.structuredContent["threads"][0]["comment"]["comment_ref"]
            )
            assert post_comments_result.structuredContent["threads"][1]["comment"]["text"] is None
            assert (
                post_comments_result.structuredContent["threads"][1]["comment"]["attachments"][0][
                    "attachment_type"
                ]
                == "photo"
            )
            invitations = await session.call_tool(
                "linkedin.invitations.list",
                {
                    "context_id": "connections-context",
                    "request_id": "invitations-request",
                    "direction": "received",
                    "invitation_filter": "mutual_connections",
                },
            )
            connections = await session.call_tool(
                "linkedin.connections.list",
                {
                    "context_id": "connections-context",
                    "request_id": "connections-request",
                },
            )
            network_search = await session.call_tool(
                "linkedin.connections.search",
                {
                    "context_id": "connections-context",
                    "request_id": "connections-search-request",
                    "filters": {
                        "title": "Staff Engineer",
                        "current_company_names": ["Example Cloud"],
                    },
                    "page_size": 10,
                },
            )
            inbox = await session.call_tool(
                "linkedin.messaging.search",
                {
                    "context_id": "messaging-context",
                    "request_id": "inbox-request",
                    "category": "other",
                    "filter": "jobs",
                },
            )
            conversation = await session.call_tool(
                "linkedin.messaging.conversation.get",
                {
                    "context_id": "messaging-context",
                    "request_id": "conversation-request",
                    "conversation_id": "thread-123",
                },
            )
            assert invitations.isError is False
            assert connections.isError is False
            assert network_search.isError is False
            assert network_search.structuredContent is not None
            assert network_search.structuredContent["coverage"]["filters"][
                "connection_degrees"
            ] == ["first"]
            assert network_search.structuredContent is not None
            assert network_search.structuredContent["people"][0]["profile_slug"] == "jane-doe"
            assert inbox.isError is False
            assert conversation.isError is False
            assert invitations.structuredContent is not None
            assert connections.structuredContent is not None
            assert inbox.structuredContent is not None
            assert conversation.structuredContent is not None
            assert (
                invitations.structuredContent["invitations"][0]["primary_entity"]["slug"]
                == "jane-doe"
            )
            assert (
                invitations.structuredContent["invitations"][0]["invitation_type"]
                == "connection_request"
            )
            assert (
                invitations.structuredContent["coverage"]["invitation_filter"]
                == "mutual_connections"
            )
            assert invitations.structuredContent["coverage"]["advertised_count"] == 1
            assert invitations.structuredContent["coverage"]["view_counts"] == {
                "mutual_connections": 1
            }
            assert invitations.structuredContent["coverage"]["view_membership_count"] == 1
            assert invitations.structuredContent["coverage"]["overlap_count"] == 0
            assert invitations.structuredContent["coverage"]["snapshot_count"] == 1
            assert (
                invitations.structuredContent["coverage"]["completion_reason"]
                == "advertised_count_reconciled"
            )
            assert invitations.structuredContent["pagination"]["has_more"] is False
            assert inbox.structuredContent["coverage"]["category"] == "other"
            assert inbox.structuredContent["coverage"]["filter"] == "jobs"
            assert connections.structuredContent["connections"][0]["name"] == "Jane Doe"
            assert inbox.structuredContent["conversations"][0]["unread"] is True
            assert (
                conversation.structuredContent["conversation"]["messages"][0]["direction"]
                == "incoming"
            )

            post_prepared = await session.call_tool(
                "linkedin.posts.create.prepare",
                {
                    "context_id": "post-write-context",
                    "request_id": "post-prepare-request",
                    "content": {
                        "mode": "text",
                        "text": "Exact protocol post",
                        "mentions": [],
                        "link_url": None,
                        "show_link_preview": True,
                    },
                    "audience": "connections_only",
                    "comment_control": "no_one",
                },
            )
            assert post_prepared.isError is False
            assert post_prepared.structuredContent is not None
            post_draft = TypeAdapter(dict[str, object]).validate_python(
                post_prepared.structuredContent["draft"]
            )
            post_action_id = post_draft["action_id"]
            post_payload_hash = post_draft["payload_hash"]
            assert isinstance(post_action_id, str)
            assert isinstance(post_payload_hash, str)
            post_approval_preview = TypeAdapter(dict[str, object]).validate_python(
                post_prepared.structuredContent["approval_preview"]
            )
            assert post_approval_preview["summary"] == (
                "Publish the prepared personal LinkedIn text post."
            )
            post_executed = await session.call_tool(
                "linkedin.posts.create.execute",
                {
                    "context_id": "post-write-context",
                    "request_id": "post-execute-request",
                    "action_id": post_action_id,
                    "payload_hash": post_payload_hash,
                    "approval_preview": post_approval_preview,
                    "idempotency_key": "protocol-post-action-1",
                },
            )
            assert post_executed.isError is False
            assert post_executed.structuredContent is not None
            assert post_executed.structuredContent["result"]["final_state"] == (
                "post_published:activity:7312345678901234567"
            )

            comment_prepared = await session.call_tool(
                "linkedin.posts.comment.prepare",
                {
                    "context_id": "post-write-context",
                    "request_id": "comment-prepare-request",
                    "post_ref": "activity:7312345678901234567",
                    "parent_comment_ref": ("comment:activity:7312345678901234567:111"),
                    "text": "Exact protocol reply.",
                },
            )
            assert comment_prepared.isError is False
            assert comment_prepared.structuredContent is not None
            comment_draft = TypeAdapter(dict[str, object]).validate_python(
                comment_prepared.structuredContent["draft"]
            )
            comment_action_id = comment_draft["action_id"]
            comment_payload_hash = comment_draft["payload_hash"]
            assert isinstance(comment_action_id, str)
            assert isinstance(comment_payload_hash, str)
            assert (
                TypeAdapter(dict[str, object]).validate_python(comment_draft["payload"])[
                    "parent_comment_ref"
                ]
                == "comment:activity:7312345678901234567:111"
            )
            comment_approval_preview = TypeAdapter(dict[str, object]).validate_python(
                comment_prepared.structuredContent["approval_preview"]
            )
            comment_executed = await session.call_tool(
                "linkedin.posts.comment.execute",
                {
                    "context_id": "post-write-context",
                    "request_id": "comment-execute-request",
                    "action_id": comment_action_id,
                    "payload_hash": comment_payload_hash,
                    "approval_preview": comment_approval_preview,
                    "idempotency_key": "protocol-comment-action-1",
                },
            )
            assert comment_executed.isError is False
            assert comment_executed.structuredContent is not None
            assert comment_executed.structuredContent["result"]["final_state"].startswith(
                "reply_published:"
            )

            reaction_prepared = await session.call_tool(
                "linkedin.posts.reaction.prepare",
                {
                    "context_id": "post-write-context",
                    "request_id": "reaction-prepare-request",
                    "post_ref": "activity:7312345678901234567",
                    "comment_ref": "comment:activity:7312345678901234567:111",
                    "desired_reaction": "funny",
                },
            )
            assert reaction_prepared.isError is False
            assert reaction_prepared.structuredContent is not None
            reaction_draft = TypeAdapter(dict[str, object]).validate_python(
                reaction_prepared.structuredContent["draft"]
            )
            reaction_action_id = reaction_draft["action_id"]
            reaction_payload_hash = reaction_draft["payload_hash"]
            assert isinstance(reaction_action_id, str)
            assert isinstance(reaction_payload_hash, str)
            reaction_payload = TypeAdapter(dict[str, object]).validate_python(
                reaction_draft["payload"]
            )
            assert reaction_payload["existing_reaction"] == "like"
            assert reaction_payload["desired_reaction"] == "funny"
            reaction_approval_preview = TypeAdapter(dict[str, object]).validate_python(
                reaction_prepared.structuredContent["approval_preview"]
            )
            reaction_executed = await session.call_tool(
                "linkedin.posts.reaction.execute",
                {
                    "context_id": "post-write-context",
                    "request_id": "reaction-execute-request",
                    "action_id": reaction_action_id,
                    "payload_hash": reaction_payload_hash,
                    "approval_preview": reaction_approval_preview,
                    "idempotency_key": "protocol-reaction-action-1",
                },
            )
            assert reaction_executed.isError is False
            assert reaction_executed.structuredContent is not None
            assert (
                reaction_executed.structuredContent["result"]["final_state"] == "reaction_set:funny"
            )

            invite_prepared = await session.call_tool(
                "linkedin.invitations.send.prepare",
                {
                    "context_id": "connections-context",
                    "request_id": "invite-prepare-request",
                    "profile_slug": "jane-doe",
                    "note": "Hello Jane",
                },
            )
            assert invite_prepared.isError is False
            assert invite_prepared.structuredContent is not None
            invite_draft = TypeAdapter(dict[str, object]).validate_python(
                invite_prepared.structuredContent["draft"]
            )
            invite_action_id = invite_draft["action_id"]
            invite_payload_hash = invite_draft["payload_hash"]
            assert isinstance(invite_action_id, str)
            assert isinstance(invite_payload_hash, str)
            invite_approval_preview = TypeAdapter(dict[str, object]).validate_python(
                invite_prepared.structuredContent["approval_preview"]
            )
            altered_invite_preview = dict(invite_approval_preview)
            altered_invite_preview["summary"] = "Send a different invitation."
            altered_invite = await session.call_tool(
                "linkedin.invitations.send.execute",
                {
                    "context_id": "connections-context",
                    "request_id": "invite-altered-preview-request",
                    "action_id": invite_action_id,
                    "payload_hash": invite_payload_hash,
                    "approval_preview": altered_invite_preview,
                    "idempotency_key": "protocol-invite-altered-preview",
                },
            )
            assert altered_invite.isError is True
            assert altered_invite.content
            assert isinstance(altered_invite.content[0], TextContent)
            assert "approval preview" in altered_invite.content[0].text.lower()
            invite_executed = await session.call_tool(
                "linkedin.invitations.send.execute",
                {
                    "context_id": "connections-context",
                    "request_id": "invite-execute-request",
                    "action_id": invite_action_id,
                    "payload_hash": invite_payload_hash,
                    "approval_preview": invite_approval_preview,
                    "idempotency_key": "protocol-invite-action-1",
                },
            )
            assert invite_executed.isError is False
            assert invite_executed.structuredContent is not None
            assert invite_executed.structuredContent["result"]["final_state"] == "pending_sent"

            accept_prepared = await session.call_tool(
                "linkedin.invitations.accept.prepare",
                {
                    "context_id": "connections-context",
                    "request_id": "accept-prepare-request",
                    "profile_slug": "jane-doe",
                },
            )
            assert accept_prepared.isError is False
            assert accept_prepared.structuredContent is not None
            accept_draft = TypeAdapter(dict[str, object]).validate_python(
                accept_prepared.structuredContent["draft"]
            )
            accept_action_id = accept_draft["action_id"]
            accept_payload_hash = accept_draft["payload_hash"]
            assert isinstance(accept_action_id, str)
            assert isinstance(accept_payload_hash, str)
            accept_approval_preview = TypeAdapter(dict[str, object]).validate_python(
                accept_prepared.structuredContent["approval_preview"]
            )
            accept_executed = await session.call_tool(
                "linkedin.invitations.accept.execute",
                {
                    "context_id": "connections-context",
                    "request_id": "accept-execute-request",
                    "action_id": accept_action_id,
                    "payload_hash": accept_payload_hash,
                    "approval_preview": accept_approval_preview,
                    "idempotency_key": "protocol-accept-action-1",
                },
            )
            assert accept_executed.isError is False
            assert accept_executed.structuredContent is not None
            assert accept_executed.structuredContent["result"]["final_state"] == "connected"

            ignore_prepared = await session.call_tool(
                "linkedin.invitations.ignore.prepare",
                {
                    "context_id": "connections-context",
                    "request_id": "ignore-prepare-request",
                    "profile_slug": "jane-doe",
                },
            )
            assert ignore_prepared.isError is False
            assert ignore_prepared.structuredContent is not None
            ignore_draft = TypeAdapter(dict[str, object]).validate_python(
                ignore_prepared.structuredContent["draft"]
            )
            ignore_action_id = ignore_draft["action_id"]
            ignore_payload_hash = ignore_draft["payload_hash"]
            assert isinstance(ignore_action_id, str)
            assert isinstance(ignore_payload_hash, str)
            ignore_approval_preview = TypeAdapter(dict[str, object]).validate_python(
                ignore_prepared.structuredContent["approval_preview"]
            )
            assert ignore_approval_preview["action_type"] == "invitation_ignore"
            ignore_executed = await session.call_tool(
                "linkedin.invitations.ignore.execute",
                {
                    "context_id": "connections-context",
                    "request_id": "ignore-execute-request",
                    "action_id": ignore_action_id,
                    "payload_hash": ignore_payload_hash,
                    "approval_preview": ignore_approval_preview,
                    "idempotency_key": "protocol-ignore-action-1",
                },
            )
            assert ignore_executed.isError is False
            assert ignore_executed.structuredContent is not None
            assert (
                ignore_executed.structuredContent["result"]["final_state"] == "invitation_ignored"
            )

            attachment_prepared = await session.call_tool(
                "linkedin.messaging.message.prepare",
                {
                    "context_id": "messaging-context",
                    "request_id": "message-attachment-prepare-request",
                    "conversation_id": "thread-123",
                    "message": "Please review the attached brief.",
                    "attachments": [{"asset_ref": "brief.pdf"}],
                },
            )
            assert attachment_prepared.isError is False
            assert attachment_prepared.structuredContent is not None
            attachment_payload = attachment_prepared.structuredContent["draft"]["payload"]
            assert attachment_payload["attachment_refs"] == ["brief.pdf"]
            assert attachment_payload["assets"][0]["role"] == "message_attachment"
            assert attachment_payload["assets"][0]["sha256"] == "e" * 64

            gif_prepared = await session.call_tool(
                "linkedin.messaging.message.prepare",
                {
                    "context_id": "messaging-context",
                    "request_id": "message-gif-prepare-request",
                    "conversation_id": "thread-123",
                    "gif": {
                        "search_query": "dancing robot",
                        "result_title": "Dancing robot GIF",
                    },
                },
            )
            assert gif_prepared.isError is False
            assert gif_prepared.structuredContent is not None
            assert gif_prepared.structuredContent["draft"]["payload"]["gif"] == {
                "search_query": "dancing robot",
                "result_title": "Dancing robot GIF",
            }

            prepared = await session.call_tool(
                "linkedin.messaging.message.prepare",
                {
                    "context_id": "messaging-context",
                    "request_id": "message-prepare-request",
                    "conversation_id": "thread-123",
                    "message": "Thanks for reaching out.",
                },
            )
            assert prepared.isError is False
            assert prepared.structuredContent is not None
            draft = TypeAdapter(dict[str, object]).validate_python(
                prepared.structuredContent["draft"]
            )
            action_id = draft["action_id"]
            payload_hash = draft["payload_hash"]
            assert isinstance(action_id, str)
            assert isinstance(payload_hash, str)
            approval_preview = TypeAdapter(dict[str, object]).validate_python(
                prepared.structuredContent["approval_preview"]
            )
            executed = await session.call_tool(
                "linkedin.messaging.message.execute",
                {
                    "context_id": "messaging-context",
                    "request_id": "message-execute-request",
                    "action_id": action_id,
                    "payload_hash": payload_hash,
                    "approval_preview": approval_preview,
                    "idempotency_key": "protocol-message-action-1",
                },
            )
            assert executed.isError is False
            assert executed.structuredContent is not None
            assert executed.structuredContent["result"]["outcome"] == "verified"
            assert executed.structuredContent["result"]["final_state"] == "message_sent"

        task_group.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_stdio_transport_runs_as_a_real_child_process() -> None:
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).with_name("stdio_fixture_server.py"))],
        cwd=ROOT,
    )
    async with (
        stdio_client(parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        initialized = await session.initialize()
        result = await session.call_tool("linkedin.server.status", {})

    assert initialized.serverInfo.name == "linkedin-mcp-server"
    assert result.isError is False
    assert result.structuredContent is not None
    assert result.structuredContent["transport"] == "stdio"


@pytest.mark.asyncio
async def test_streamable_http_transport_runs_on_loopback(unused_tcp_port: int) -> None:
    mcp = create_mcp_server(_container())
    server = uvicorn.Server(
        uvicorn.Config(
            mcp.streamable_http_app(),
            host="127.0.0.1",
            port=unused_tcp_port,
            log_level="critical",
        )
    )
    server_task = anyio.create_task_group()

    async with server_task as task_group:
        task_group.start_soon(server.serve)
        for _ in range(200):
            if server.started:
                break
            await anyio.sleep(0.01)
        else:
            raise AssertionError("Streamable HTTP server did not start")

        try:
            async with (
                streamable_http_client(f"http://127.0.0.1:{unused_tcp_port}/mcp") as (
                    read_stream,
                    write_stream,
                    _,
                ),
                ClientSession(read_stream, write_stream) as session,
            ):
                initialized = await session.initialize()
                result = await session.call_tool("linkedin.server.status", {})
        finally:
            server.should_exit = True

        assert initialized.serverInfo.name == "linkedin-mcp-server"
        assert result.isError is False
        assert result.structuredContent is not None
        assert result.structuredContent["transport"] == "stdio"
