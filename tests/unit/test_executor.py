from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import HttpUrl

import linkedin_mcp.application.executor as executor_module
from linkedin_mcp.application import CapabilityExecutor
from linkedin_mcp.application.executor import safe_capability_error
from linkedin_mcp.capabilities import create_default_registry
from linkedin_mcp.config import Settings
from linkedin_mcp.domain.models import (
    CURRENT_RECEIVED_INVITATION_VIEWS,
    ActionDraft,
    ActionExecuteInput,
    ActionOutcome,
    ActionPageResult,
    ActionPreparationCapture,
    ActionStatus,
    ActionTarget,
    ActionType,
    CapabilityEffect,
    CommentCreatePayload,
    CommentObservation,
    CommentSort,
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
    ConnectionsSearchFilters,
    ConnectionsSearchInput,
    ConnectionSummary,
    ConversationCoverage,
    ConversationFilter,
    ConversationGetInput,
    ConversationObservation,
    ConversationSearchCoverage,
    ConversationSearchInput,
    ConversationSummary,
    EvidenceField,
    InvitationAcceptPrepareInput,
    InvitationAvailableAction,
    InvitationDirection,
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
    MessageFileInput,
    MessageGifInput,
    MessageObservation,
    MessagePrepareInput,
    MessageSendPayload,
    PeopleGetInput,
    PeopleSearchConnectionDegree,
    PeopleSearchCoverage,
    PeopleSearchInput,
    PersonConnectionDegree,
    PersonProfileCoverage,
    PersonProfileEvidence,
    PersonProfileObservation,
    PersonProfilePageCapture,
    PersonProfileSectionSelector,
    PersonSummary,
    PostAssetRole,
    PostAuthor,
    PostAuthorType,
    PostCollaboratorInput,
    PostCommentPrepareInput,
    PostCommentsCoverage,
    PostCommentsListInput,
    PostCreatePayload,
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
    TextPostContent,
    action_approval_preview,
)
from linkedin_mcp.errors import (
    AuthorizationDeniedError,
    IdempotencyConflictError,
    InternalServerError,
    InvalidCursorError,
    InvalidTargetError,
    ParserDriftError,
)
from linkedin_mcp.persistence import MemoryRepository


class FakeJobSearch:
    def __init__(self) -> None:
        self.calls = 0

    async def collect(
        self,
        request: JobSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[JobSummary, ...], JobSearchCoverage, str, str]:
        del result_limit
        self.calls += 1
        now = datetime.now(UTC)
        job = JobSummary(
            job_id="4100000001",
            job_url=HttpUrl("https://www.linkedin.com/jobs/view/4100000001/"),
            title="Senior Python Engineer",
            company_name="Acme Cloud",
            location="India (Remote)",
            listed_at_text="3 hours ago",
            easy_apply=True,
            visible_text="Senior Python Engineer\nAcme Cloud\nIndia (Remote)\n3 hours ago",
        )
        return (
            (job,),
            JobSearchCoverage(
                query=request.query,
                location=request.location,
                freshness_hours=request.freshness_hours,
                pages_visited=1,
                result_count=1,
                max_results=request.max_results,
                stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=now,
            ),
            job.visible_text,
            "https://www.linkedin.com/jobs/search/?keywords=python",
        )


class PaginatedFakeJobSearch(FakeJobSearch):
    def __init__(self) -> None:
        super().__init__()
        self.result_limits: list[int] = []
        self._jobs = tuple(
            JobSummary(
                job_id=f"410000000{index}",
                job_url=HttpUrl(f"https://www.linkedin.com/jobs/view/410000000{index}/"),
                title=f"Python Engineer {index}",
                company_name="Acme Cloud",
                location="India",
                visible_text=f"Python Engineer {index}\nAcme Cloud\nIndia",
            )
            for index in range(1, 6)
        )

    async def collect(
        self,
        request: JobSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[JobSummary, ...], JobSearchCoverage, str, str]:
        self.calls += 1
        limit = request.page_size if result_limit is None else result_limit
        self.result_limits.append(limit)
        jobs = self._jobs[:limit]
        return (
            jobs,
            JobSearchCoverage(
                query=request.query,
                location=request.location,
                freshness_hours=request.freshness_hours,
                pages_visited=1,
                result_count=len(jobs),
                max_results=limit,
                stop_reason=(
                    StopReason.RESULT_LIMIT
                    if limit < len(self._jobs)
                    else StopReason.VISIBLE_PAGE_COMPLETE
                ),
                captured_at=datetime.now(UTC),
            ),
            "\n".join(job.visible_text for job in jobs),
            "https://www.linkedin.com/jobs/search/?keywords=python",
        )


class FakeJobDetail:
    def __init__(self) -> None:
        self.calls = 0

    async def read(self, request: JobDetailInput) -> JobDetailObservation:
        self.calls += 1
        visible_text = "Senior Python Engineer\nAcme Cloud\nBuild reliable services."
        return JobDetailObservation(
            job_id=request.job_id,
            job_url=HttpUrl(f"https://www.linkedin.com/jobs/view/{request.job_id}/"),
            title="Senior Python Engineer",
            company_name="Acme Cloud",
            description_text="Build reliable services.",
            easy_apply=True,
            visible_text=visible_text,
            evidence=(
                EvidenceField(field="title", quote="Senior Python Engineer"),
                EvidenceField(field="company_name", quote="Acme Cloud"),
                EvidenceField(field="description_text", quote="Build reliable services."),
            ),
            captured_at=datetime.now(UTC),
        )


class FakePeopleSearch:
    def __init__(self) -> None:
        self.calls = 0

    async def collect(
        self,
        request: PeopleSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[PersonSummary, ...], PeopleSearchCoverage, str, str]:
        del result_limit
        self.calls += 1
        now = datetime.now(UTC)
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
                captured_at=now,
            ),
            visible_text,
            "https://www.linkedin.com/search/results/people/?keywords=python",
        )


class FakeNonConnectionPeopleSearch(FakePeopleSearch):
    async def collect(
        self,
        request: PeopleSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[PersonSummary, ...], PeopleSearchCoverage, str, str]:
        people, coverage, captured_text, source_url = await super().collect(
            request,
            result_limit=result_limit,
        )
        return (
            tuple(
                person.model_copy(update={"connection_degree": PersonConnectionDegree.SECOND})
                for person in people
            ),
            coverage,
            captured_text,
            source_url,
        )


class FakePersonProfile:
    def __init__(self) -> None:
        self.calls = 0

    async def read(
        self, request: PeopleGetInput
    ) -> tuple[PersonProfileObservation, tuple[PersonProfilePageCapture, ...]]:
        self.calls += 1
        now = datetime.now(UTC)
        profile_url = HttpUrl(f"https://www.linkedin.com/in/{request.profile_slug}/")
        experience_url = HttpUrl(
            f"https://www.linkedin.com/in/{request.profile_slug}/details/experience/"
        )
        profile_text = "Jane Doe\nStaff Engineer at Acme Cloud\nAbout\nBuilds reliable systems."
        experience_text = "Experience\nStaff Engineer\nAcme Cloud"
        person = PersonProfileObservation(
            profile_slug=request.profile_slug,
            profile_url=profile_url,
            name="Jane Doe",
            headline="Staff Engineer at Acme Cloud",
            about="Builds reliable systems.",
            visible_text=f"{profile_text}\n\n{experience_text}",
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
                pages_visited=2,
                detail_pages_discovered=1,
                detail_pages_visited=1,
                detail_page_limit=20,
                truncated=False,
                captured_at=now,
            ),
            captured_at=now,
        )
        return (
            person,
            (
                PersonProfilePageCapture(
                    source_url=profile_url,
                    page_kind="profile",
                    captured_text=profile_text,
                    captured_at=now,
                ),
                PersonProfilePageCapture(
                    source_url=experience_url,
                    page_kind="section",
                    section_heading="Experience",
                    captured_text=experience_text,
                    captured_at=now,
                ),
            ),
        )


class FakeCompanySearch:
    def __init__(self) -> None:
        self.calls = 0

    async def collect(
        self,
        request: CompanySearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[CompanySummary, ...], CompanySearchCoverage, str, str]:
        del result_limit
        self.calls += 1
        now = datetime.now(UTC)
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
                captured_at=now,
            ),
            visible_text,
            "https://www.linkedin.com/search/results/companies/?keywords=acme",
        )


class FakeCompanyProfile:
    def __init__(self) -> None:
        self.calls = 0

    async def read(
        self,
        request: CompanyGetInput,
    ) -> tuple[CompanyProfileObservation, tuple[CompanyProfilePageCapture, ...]]:
        self.calls += 1
        now = datetime.now(UTC)
        source_url = HttpUrl(f"https://www.linkedin.com/company/{request.company_slug}/")
        about_url = HttpUrl(f"https://www.linkedin.com/company/{request.company_slug}/about/")
        overview_text = "Acme Cloud\nReliable infrastructure\n8,500 followers"
        about_text = (
            "About\nCloud infrastructure for reliable teams.\nWebsite\nhttps://acme.example\n"
            "Industry\nSoftware Development\nCompany size\n1,001-5,000 employees\n"
            "Headquarters\nBengaluru, Karnataka\nType\nPrivately Held\nFounded\n2014\n"
            "Specialties\nCloud, Reliability"
        )
        captured_text = f"{overview_text}\n\n{about_text}"
        company = CompanyProfileObservation(
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
            coverage=CompanyProfileCoverage(captured_at=now),
            captured_at=now,
        )
        return (
            company,
            (
                CompanyProfilePageCapture(
                    source_url=source_url,
                    page_kind="overview",
                    captured_text=overview_text,
                    captured_at=now,
                ),
                CompanyProfilePageCapture(
                    source_url=about_url,
                    page_kind="about",
                    captured_text=about_text,
                    captured_at=now,
                ),
            ),
        )


def _post_author() -> PostAuthor:
    return PostAuthor(
        author_type=PostAuthorType.MEMBER,
        name="Jane Doe",
        profile_slug="jane-doe",
        author_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
        headline="Staff Engineer at Acme Cloud",
    )


class FakePostSearch:
    def __init__(self) -> None:
        self.calls = 0

    async def collect(
        self,
        request: PostSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[PostSummary, ...], PostSearchCoverage, str, str]:
        del result_limit
        self.calls += 1
        now = datetime.now(UTC)
        visible_text = (
            "Jane Doe\nStaff Engineer at Acme Cloud\n2h\n"
            "A practical guide to reliable Python services.\n12 reactions\n3 comments"
        )
        post = PostSummary(
            post_ref="activity:7312345678901234567",
            post_url=HttpUrl(
                "https://www.linkedin.com/feed/update/urn:li:activity:7312345678901234567/"
            ),
            author=_post_author(),
            text="A practical guide to reliable Python services.",
            posted_at_text="2h",
            reaction_count_text="12 reactions",
            comment_count_text="3 comments",
            visible_text=visible_text,
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
                captured_at=now,
            ),
            visible_text,
            "https://www.linkedin.com/search/results/content/?keywords=python",
        )


class FakePostDetail:
    def __init__(self) -> None:
        self.calls = 0

    async def read(self, request: PostGetInput) -> PostObservation:
        self.calls += 1
        post_url = HttpUrl(f"https://www.linkedin.com/feed/update/urn:li:{request.post_ref}/")
        captured_at = datetime.now(UTC)
        visible_text = (
            "Jane Doe\nStaff Engineer at Acme Cloud\n2h\n"
            "A practical guide to reliable Python services.\n12 reactions\n3 comments"
        )
        return PostObservation(
            post_ref=request.post_ref,
            displayed_post_ref=request.post_ref,
            post_url=post_url,
            author=_post_author(),
            text="A practical guide to reliable Python services.",
            posted_at_text="2h",
            reaction_count_text="12 reactions",
            comment_count_text="3 comments",
            visible_text=visible_text,
            evidence=(
                PostEvidence(
                    field="author.name",
                    quote="Jane Doe",
                    source_url=post_url,
                    captured_at=captured_at,
                ),
                PostEvidence(
                    field="text",
                    quote="A practical guide to reliable Python services.",
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


class FakePostComments:
    def __init__(self) -> None:
        self.calls = 0

    async def collect(
        self,
        request: PostCommentsListInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[CommentThread, ...], PostCommentsCoverage, str, str]:
        del result_limit
        self.calls += 1
        top_text = "Alex Ray\nHelpful breakdown.\n1h\n2 reactions\n1 reply"
        reply_text = "Jane Doe\nThank you!\n45m"
        top_ref = f"comment:{request.post_ref}:111"
        top = CommentObservation(
            comment_ref=top_ref,
            post_ref=request.post_ref,
            author=PostAuthor(
                author_type=PostAuthorType.MEMBER,
                name="Alex Ray",
                profile_slug="alex-ray",
                author_url=HttpUrl("https://www.linkedin.com/in/alex-ray/"),
            ),
            text="Helpful breakdown.",
            posted_at_text="1h",
            reaction_count_text="2 reactions",
            reply_count_text="1 reply",
            visible_text=top_text,
        )
        reply = CommentObservation(
            comment_ref=f"comment:{request.post_ref}:112",
            post_ref=request.post_ref,
            parent_comment_ref=top_ref,
            author=_post_author(),
            text="Thank you!",
            posted_at_text="45m",
            visible_text=reply_text,
        )
        now = datetime.now(UTC)
        return (
            (CommentThread(comment=top, replies=(reply,)),),
            PostCommentsCoverage(
                post_ref=request.post_ref,
                discussion_post_ref=request.post_ref,
                sort_by=request.sort_by,
                expansion_rounds=1,
                top_level_visible=1,
                top_level_returned=1,
                replies_visible=1,
                replies_returned=1,
                max_comments=request.max_comments,
                max_replies_per_comment=request.max_replies_per_comment,
                truncated=False,
                captured_at=now,
            ),
            f"{top_text}\n{reply_text}",
            f"https://www.linkedin.com/feed/update/urn:li:{request.post_ref}/",
        )


class FakeInvitationList:
    def __init__(self) -> None:
        self.calls = 0

    async def collect(
        self,
        request: InvitationListInput,
        *,
        result_limit: int | None = None,
        progress: object | None = None,
    ) -> tuple[tuple[InvitationSummary, ...], InvitationListCoverage, str, str]:
        del progress
        self.calls += 1
        limit = request.page_size if result_limit is None else result_limit
        now = datetime.now(UTC)
        source_url = "https://www.linkedin.com/mynetwork/invitation-manager/"
        text = "Jane Doe\nStaff Engineer\nHi, let us connect.\nAccept"
        invitation = InvitationSummary(
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
                    captured_at=now,
                ),
            ),
        )
        return (
            (invitation,),
            InvitationListCoverage(
                direction=request.direction,
                invitation_filter=request.resolved_filter,
                advertised_count=(None if request.resolved_filter is InvitationFilter.ALL else 1),
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
                result_count=1,
                max_results=limit,
                scroll_rounds=1,
                collection_attempts=1,
                neighboring_recommendation_count=0,
                invitation_type_counts={InvitationType.CONNECTION_REQUEST: 1},
                entity_type_counts={InvitationEntityType.PERSON: 1},
                stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=now,
            ),
            text,
            source_url,
        )


class PaginatedFakeInvitationList(FakeInvitationList):
    def __init__(self) -> None:
        super().__init__()
        self.result_limits: list[int] = []

    async def collect(
        self,
        request: InvitationListInput,
        *,
        result_limit: int | None = None,
        progress: object | None = None,
    ) -> tuple[tuple[InvitationSummary, ...], InvitationListCoverage, str, str]:
        del progress
        self.calls += 1
        limit = request.page_size if result_limit is None else result_limit
        self.result_limits.append(limit)
        captured_at = datetime.now(UTC)
        source_url = "https://www.linkedin.com/mynetwork/invitation-manager/"
        all_items = tuple(
            InvitationSummary(
                invitation_ref=f"invitation:{index:024d}",
                direction=request.direction,
                invitation_type=InvitationType.CONNECTION_REQUEST,
                primary_entity=InvitationEntity(
                    entity_ref=f"person:invitation-member-{index}",
                    entity_type=InvitationEntityType.PERSON,
                    entity_url=HttpUrl(f"https://www.linkedin.com/in/invitation-member-{index}/"),
                    display_name=f"Invitation Member {index}",
                    slug=f"invitation-member-{index}",
                ),
                headline="Engineer at Example Systems",
                available_actions=(
                    InvitationAvailableAction.IGNORE,
                    InvitationAvailableAction.ACCEPT,
                ),
                visible_text=(f"Invitation Member {index}\nEngineer at Example Systems\nAccept"),
                evidence=(
                    InvitationEvidence(
                        field="primary_entity.display_name",
                        quote=f"Invitation Member {index}",
                        source_url=HttpUrl(source_url),
                        captured_at=captured_at,
                    ),
                ),
            )
            for index in range(1, 6)
        )
        visible_items = all_items[:limit]
        text = "\n\n".join(item.visible_text for item in visible_items)
        return (
            visible_items,
            InvitationListCoverage(
                direction=request.direction,
                invitation_filter=request.resolved_filter,
                advertised_count=(
                    None if request.resolved_filter is InvitationFilter.ALL else len(all_items)
                ),
                unique_count=len(visible_items),
                view_counts=(
                    {
                        invitation_filter: (
                            len(all_items) if invitation_filter is InvitationFilter.FOCUSED else 0
                        )
                        for invitation_filter in CURRENT_RECEIVED_INVITATION_VIEWS
                    }
                    if request.resolved_filter is InvitationFilter.ALL
                    else {request.resolved_filter: len(all_items)}
                ),
                view_source_urls=(
                    {
                        invitation_filter: HttpUrl(source_url)
                        for invitation_filter in CURRENT_RECEIVED_INVITATION_VIEWS
                    }
                    if request.resolved_filter is InvitationFilter.ALL
                    else {request.resolved_filter: HttpUrl(source_url)}
                ),
                view_membership_count=len(all_items),
                overlap_count=0,
                result_count=len(visible_items),
                max_results=limit,
                scroll_rounds=5,
                collection_attempts=1,
                neighboring_recommendation_count=0,
                invitation_type_counts={InvitationType.CONNECTION_REQUEST: len(visible_items)},
                entity_type_counts={InvitationEntityType.PERSON: len(visible_items)},
                stop_reason=(
                    StopReason.VISIBLE_PAGE_COMPLETE
                    if len(visible_items) == len(all_items)
                    else StopReason.RESULT_LIMIT
                ),
                captured_at=captured_at,
            ),
            text,
            source_url,
        )


class FakeConnectionsList:
    async def collect(
        self,
        request: ConnectionsListInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[ConnectionSummary, ...], ConnectionsListCoverage, str, str]:
        del result_limit
        now = datetime.now(UTC)
        text = "Jane Doe\nStaff Engineer\nBengaluru\nMessage"
        connection = ConnectionSummary(
            profile_slug="jane-doe",
            profile_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
            name="Jane Doe",
            headline="Staff Engineer",
            location="Bengaluru",
            visible_text=text,
        )
        return (
            (connection,),
            ConnectionsListCoverage(
                sort_by=request.sort_by,
                rounds_visited=1,
                result_count=1,
                max_results=request.max_results,
                stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=now,
            ),
            text,
            "https://www.linkedin.com/mynetwork/invite-connect/connections/",
        )


class FakeConversationSearch:
    async def collect(
        self,
        request: ConversationSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[ConversationSummary, ...], ConversationSearchCoverage, str, str]:
        del result_limit
        now = datetime.now(UTC)
        text = "Jane Doe\nCan we chat?\n10:30 AM"
        conversation = ConversationSummary(
            conversation_ref="conversation:" + "c" * 24,
            conversation_id="thread-123",
            participant_profile_slug="jane-doe",
            participant_profile_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
            participant_name="Jane Doe",
            last_message_text="Can we chat?",
            unread=True,
            visible_text=text,
        )
        return (
            (conversation,),
            ConversationSearchCoverage(
                query=request.query,
                category=request.resolved_category,
                filter=request.filter,
                rounds_visited=1,
                result_count=1,
                max_results=request.max_results,
                stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=now,
            ),
            text,
            "https://www.linkedin.com/messaging/",
        )


class FakeInvitationActions:
    def __init__(self) -> None:
        self.invite_executions = 0
        self.accept_executions = 0
        self.ignore_executions = 0

    async def prepare_send(
        self,
        request: InvitationSendPrepareInput,
    ) -> ActionPreparationCapture:
        return _action_capture(request.profile_slug)

    async def prepare_accept(
        self,
        request: InvitationAcceptPrepareInput,
    ) -> ActionPreparationCapture:
        capture = _action_capture(request.profile_slug)
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
        return await self.prepare_accept(
            InvitationAcceptPrepareInput(
                context_id=request.context_id,
                request_id=request.request_id,
                profile_slug=request.profile_slug,
            )
        )

    async def execute_send(self, draft: ActionDraft) -> ActionPageResult:
        self.invite_executions += 1
        return _page_result("pending_sent")

    async def execute_accept(self, draft: ActionDraft) -> ActionPageResult:
        self.accept_executions += 1
        return _page_result("connected")

    async def execute_ignore(self, draft: ActionDraft) -> ActionPageResult:
        self.ignore_executions += 1
        return _page_result("invitation_ignored")


class FakePostPublishing:
    def __init__(self) -> None:
        self.asset_preparations = 0
        self.executions = 0

    async def prepare_assets(
        self,
        request: PostCreatePrepareInput,
    ) -> tuple[PreparedPostAsset, ...]:
        del request
        self.asset_preparations += 1
        return ()

    async def prepare_post(
        self,
        request: PostCreatePrepareInput,
    ) -> ActionPreparationCapture:
        del request
        capture = _action_capture("current-member")
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
        self.executions += 1
        return _page_result("post_published:activity:7312345678901234567")


class FakePostEngagement:
    def __init__(self) -> None:
        self.asset_preparations = 0
        self.comment_executions = 0
        self.reaction_executions = 0

    async def prepare_comment_assets(
        self,
        request: PostCommentPrepareInput,
    ) -> tuple[PreparedPostAsset, ...]:
        del request
        self.asset_preparations += 1
        return ()

    async def prepare_comment(
        self,
        request: PostCommentPrepareInput,
    ) -> ActionPreparationCapture:
        capture = _action_capture("current-member")
        return capture.model_copy(
            update={
                "target": capture.target.model_copy(
                    update={
                        "actor_profile_slug": "current-member",
                        "actor_profile_url": HttpUrl("https://www.linkedin.com/in/current-member/"),
                        "actor_display_name": "Current Member",
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
            }
        )

    async def execute_comment(self, draft: ActionDraft) -> ActionPageResult:
        del draft
        self.comment_executions += 1
        return _page_result("comment_published:comment:activity:7312345678901234567:900")

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
                text="typed preparation placeholder",
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
        self.reaction_executions += 1
        return _page_result(f"reaction_set:{draft.payload.desired_reaction.value}")


class MissingReferenceActions(FakeInvitationActions):
    async def prepare_accept(
        self,
        request: InvitationAcceptPrepareInput,
    ) -> ActionPreparationCapture:
        return _action_capture(request.profile_slug)

    async def prepare_ignore(
        self,
        request: InvitationIgnorePrepareInput,
    ) -> ActionPreparationCapture:
        return _action_capture(request.profile_slug)


class InterruptedInvitationActions(FakeInvitationActions):
    def __init__(self, *, cancelled: bool) -> None:
        super().__init__()
        self.cancelled = cancelled

    async def execute_send(self, draft: ActionDraft) -> ActionPageResult:
        del draft
        if self.cancelled:
            raise asyncio.CancelledError
        raise RuntimeError("browser stopped after execution reservation")


class FakeConversation:
    def __init__(self) -> None:
        self.message_executions = 0

    async def read(self, request: ConversationGetInput) -> ConversationObservation:
        now = datetime.now(UTC)
        text = "Jane Doe\nJane Doe\nCan we chat?\nYou\nYes."
        messages = (
            MessageObservation(
                message_ref="message:" + "a" * 24,
                direction=MessageDirection.INCOMING,
                sender_name="Jane Doe",
                text="Can we chat?",
                visible_text="Jane Doe\nCan we chat?",
            ),
            MessageObservation(
                message_ref="message:" + "b" * 24,
                direction=MessageDirection.OUTGOING,
                sender_name="You",
                text="Yes.",
                visible_text="You\nYes.",
            ),
        )
        return ConversationObservation(
            conversation_id=request.conversation_id or "thread-123",
            participant_profile_slug=request.profile_slug or "jane-doe",
            participant_profile_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
            participant_name="Jane Doe",
            messages=messages,
            visible_text=text,
            coverage=ConversationCoverage(
                messages_observed=2,
                messages_returned=2,
                max_messages=request.max_messages,
                rounds_visited=1,
                stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
                history_complete=True,
                truncated=False,
                captured_at=now,
            ),
            captured_at=now,
        )

    async def prepare_message(
        self,
        request: MessagePrepareInput,
    ) -> ActionPreparationCapture:
        return _action_capture(request.profile_slug or "jane-doe").model_copy(
            update={
                "target": ActionTarget(
                    profile_slug=request.profile_slug or "jane-doe",
                    profile_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
                    display_name="Jane Doe",
                    conversation_id=request.conversation_id or "thread-123",
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
        self.message_executions += 1
        return _page_result("message_sent")


class FailureRecordingRepository(MemoryRepository):
    async def fail_call(
        self,
        *,
        call_id: str,
        error_code: str,
        error_message: str,
    ) -> None:
        del call_id, error_code, error_message
        raise RuntimeError("runtime store unavailable")


def _action_capture(profile_slug: str) -> ActionPreparationCapture:
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


def _page_result(final_state: str) -> ActionPageResult:
    return ActionPageResult(
        outcome=ActionOutcome.VERIFIED,
        performed=True,
        final_state=final_state,
        detail=f"LinkedIn visibly confirmed {final_state}.",
        source_url=HttpUrl("https://www.linkedin.com/in/jane-doe/"),
        captured_text=f"Jane Doe\n{final_state}",
        captured_at=datetime.now(UTC),
    )


def _execute_request(
    draft: ActionDraft,
    *,
    context_id: str,
    request_id: str,
    idempotency_key: str,
) -> ActionExecuteInput:
    return ActionExecuteInput(
        context_id=context_id,
        request_id=request_id,
        action_id=draft.action_id,
        payload_hash=draft.payload_hash,
        approval_preview=action_approval_preview(draft),
        idempotency_key=idempotency_key,
    )


def _settings() -> Settings:
    return Settings(
        minimum_navigation_interval_seconds=0,
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


def _executor(
    repository: MemoryRepository,
    search: FakeJobSearch,
    detail: FakeJobDetail,
    people_search: FakePeopleSearch | None = None,
    person_profile: FakePersonProfile | None = None,
    company_search: FakeCompanySearch | None = None,
    company_profile: FakeCompanyProfile | None = None,
    post_search: FakePostSearch | None = None,
    post_detail: FakePostDetail | None = None,
    post_comments: FakePostComments | None = None,
    post_publishing: FakePostPublishing | None = None,
    post_engagement: FakePostEngagement | None = None,
    invitation_list: FakeInvitationList | None = None,
    connections_list: FakeConnectionsList | None = None,
    invitation_actions: FakeInvitationActions | None = None,
    conversation_search: FakeConversationSearch | None = None,
    conversation: FakeConversation | None = None,
) -> CapabilityExecutor:
    return CapabilityExecutor(
        settings=_settings(),
        registry=create_default_registry(),
        repository=repository,
        job_search=search,
        job_detail=detail,
        people_search=people_search or FakePeopleSearch(),
        person_profile=person_profile or FakePersonProfile(),
        company_search=company_search or FakeCompanySearch(),
        company_profile=company_profile or FakeCompanyProfile(),
        post_search=post_search or FakePostSearch(),
        post_detail=post_detail or FakePostDetail(),
        post_comments=post_comments or FakePostComments(),
        post_publishing=post_publishing or FakePostPublishing(),
        post_engagement=post_engagement or FakePostEngagement(),
        invitation_list=invitation_list or FakeInvitationList(),
        connections_list=connections_list or FakeConnectionsList(),
        invitation_actions=invitation_actions or FakeInvitationActions(),
        conversation_search=conversation_search or FakeConversationSearch(),
        conversation=conversation or FakeConversation(),
    )


_READ_FAILURE_CASES: tuple[tuple[str, str, str, object], ...] = (
    (
        "_job_search",
        "collect",
        "search_jobs",
        JobSearchInput(
            context_id="failure-context",
            request_id="job-search-failure",
            query="python",
        ),
    ),
    (
        "_job_detail",
        "read",
        "get_job",
        JobDetailInput(
            context_id="failure-context",
            request_id="job-detail-failure",
            job_id="4100000001",
        ),
    ),
    (
        "_people_search",
        "collect",
        "search_people",
        PeopleSearchInput(
            context_id="failure-context",
            request_id="people-search-failure",
            query="python",
        ),
    ),
    (
        "_people_search",
        "collect",
        "search_connections",
        ConnectionsSearchInput(
            context_id="failure-context",
            request_id="connections-search-failure",
            filters=ConnectionsSearchFilters(title="Staff Engineer"),
        ),
    ),
    (
        "_person_profile",
        "read",
        "get_person",
        PeopleGetInput(
            context_id="failure-context",
            request_id="person-get-failure",
            profile_slug="jane-doe",
        ),
    ),
    (
        "_company_search",
        "collect",
        "search_companies",
        CompanySearchInput(
            context_id="failure-context",
            request_id="company-search-failure",
            query="cloud",
        ),
    ),
    (
        "_company_profile",
        "read",
        "get_company",
        CompanyGetInput(
            context_id="failure-context",
            request_id="company-get-failure",
            company_slug="acme-cloud",
        ),
    ),
    (
        "_post_search",
        "collect",
        "search_posts",
        PostSearchInput(
            context_id="failure-context",
            request_id="post-search-failure",
            query="python",
        ),
    ),
    (
        "_post_detail",
        "read",
        "get_post",
        PostGetInput(
            context_id="failure-context",
            request_id="post-get-failure",
            post_ref="activity:7312345678901234567",
        ),
    ),
    (
        "_post_comments",
        "collect",
        "list_post_comments",
        PostCommentsListInput(
            context_id="failure-context",
            request_id="post-comments-failure",
            post_ref="activity:7312345678901234567",
        ),
    ),
    (
        "_invitation_list",
        "collect",
        "list_invitations",
        InvitationListInput(
            context_id="failure-context",
            request_id="invitation-list-failure",
        ),
    ),
    (
        "_connections_list",
        "collect",
        "list_connections",
        ConnectionsListInput(
            context_id="failure-context",
            request_id="connections-list-failure",
        ),
    ),
    (
        "_conversation_search",
        "collect",
        "search_messages",
        ConversationSearchInput(
            context_id="failure-context",
            request_id="conversation-list-failure",
            query="failure",
        ),
    ),
    (
        "_conversation",
        "read",
        "get_conversation",
        ConversationGetInput(
            context_id="failure-context",
            request_id="conversation-get-failure",
            conversation_id="thread-123",
        ),
    ),
)


@pytest.mark.parametrize(
    ("provider_attribute", "provider_method", "executor_method", "capability_request"),
    _READ_FAILURE_CASES,
)
@pytest.mark.parametrize("cancelled", [False, True], ids=["safe-error", "cancelled"])
@pytest.mark.asyncio
async def test_read_failures_are_recorded_and_never_silently_retried(
    provider_attribute: str,
    provider_method: str,
    executor_method: str,
    capability_request: object,
    cancelled: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MemoryRepository()
    executor = _executor(repository, FakeJobSearch(), FakeJobDetail())
    provider = getattr(executor, provider_attribute)

    async def fail(_request: object, **_kwargs: object) -> Any:
        if cancelled:
            raise asyncio.CancelledError
        raise InvalidTargetError("The visible LinkedIn target changed.")

    monkeypatch.setattr(provider, provider_method, fail)
    execute = getattr(executor, executor_method)

    expected_error = asyncio.CancelledError if cancelled else InvalidTargetError
    with pytest.raises(expected_error):
        await execute(capability_request)
    with pytest.raises(IdempotencyConflictError, match="failed attempt"):
        await execute(capability_request)


@pytest.mark.asyncio
async def test_job_search_is_persisted_and_replayed_without_provider_call() -> None:
    repository = MemoryRepository()
    search = FakeJobSearch()
    executor = _executor(repository, search, FakeJobDetail())
    request = JobSearchInput(
        context_id="context-1",
        request_id="request-1",
        query="python",
        page_size=10,
    )

    first = await executor.search_jobs(request)
    replay = await executor.search_jobs(request)

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.jobs == first.jobs
    assert search.calls == 1


@pytest.mark.asyncio
async def test_job_search_cursor_walks_live_prefix_without_duplicates_and_replays_pages() -> None:
    repository = MemoryRepository()
    search = PaginatedFakeJobSearch()
    executor = _executor(repository, search, FakeJobDetail())
    first_request = JobSearchInput(
        context_id="pagination-context",
        request_id="jobs-page-1",
        query="python",
        page_size=2,
    )

    first = await executor.search_jobs(first_request)
    assert tuple(job.job_id for job in first.jobs) == ("4100000001", "4100000002")
    assert first.pagination.returned_count == 2
    assert first.pagination.cumulative_count == 2
    assert first.pagination.has_more is True
    assert first.pagination.next_cursor is not None

    second_request = first_request.model_copy(
        update={
            "request_id": "jobs-page-2",
            "cursor": first.pagination.next_cursor,
        }
    )
    second = await executor.search_jobs(second_request)
    assert tuple(job.job_id for job in second.jobs) == ("4100000003", "4100000004")
    assert second.pagination.scan_id == first.pagination.scan_id
    assert second.pagination.cumulative_count == 4
    assert second.pagination.next_cursor is not None

    with pytest.raises(InvalidCursorError, match="consumed"):
        await executor.search_jobs(
            first_request.model_copy(
                update={
                    "request_id": "jobs-page-1-cursor-replay",
                    "cursor": first.pagination.next_cursor,
                }
            )
        )

    third_request = first_request.model_copy(
        update={
            "request_id": "jobs-page-3",
            "cursor": second.pagination.next_cursor,
        }
    )
    third = await executor.search_jobs(third_request)
    assert tuple(job.job_id for job in third.jobs) == ("4100000005",)
    assert third.pagination.scan_id == first.pagination.scan_id
    assert third.pagination.cumulative_count == 5
    assert third.pagination.has_more is False
    assert third.pagination.next_cursor is None

    replay = await executor.search_jobs(second_request)
    assert replay.replayed is True
    assert replay.jobs == second.jobs
    assert replay.pagination == second.pagination
    assert search.result_limits == [3, 5, 7]


@pytest.mark.asyncio
async def test_invitation_cursor_walks_live_prefix_without_duplicates() -> None:
    repository = MemoryRepository()
    invitations = PaginatedFakeInvitationList()
    executor = _executor(
        repository,
        FakeJobSearch(),
        FakeJobDetail(),
        invitation_list=invitations,
    )
    first_request = InvitationListInput(
        context_id="invitation-pagination",
        request_id="invitation-page-1",
        invitation_filter=InvitationFilter.VERIFIED,
        page_size=2,
    )

    first = await executor.list_invitations(first_request)
    assert [item.primary_entity.slug for item in first.invitations] == [
        "invitation-member-1",
        "invitation-member-2",
    ]
    assert first.coverage.advertised_count == 5
    assert first.coverage.unique_count == 3
    assert first.coverage.result_count == 2
    assert first.coverage.stop_reason is StopReason.RESULT_LIMIT
    assert first.pagination.consistency == "live_deduplicated"
    assert first.pagination.cumulative_count == 2
    assert first.pagination.next_cursor is not None

    with pytest.raises(InvalidCursorError, match="account, capability, or filter set"):
        await executor.list_invitations(
            first_request.model_copy(
                update={
                    "request_id": "invitation-filter-mismatch",
                    "cursor": first.pagination.next_cursor,
                    "invitation_filter": InvitationFilter.SAME_COMPANY,
                }
            )
        )
    with pytest.raises(InvalidCursorError, match="account, capability, or filter set"):
        await executor.list_invitations(
            first_request.model_copy(
                update={
                    "request_id": "invitation-direction-mismatch",
                    "cursor": first.pagination.next_cursor,
                    "direction": InvitationDirection.SENT,
                    "invitation_filter": InvitationFilter.ALL,
                }
            )
        )

    second_request = first_request.model_copy(
        update={
            "request_id": "invitation-page-2",
            "cursor": first.pagination.next_cursor,
            "page_size": 1,
        }
    )
    second = await executor.list_invitations(second_request)
    assert [item.primary_entity.slug for item in second.invitations] == ["invitation-member-3"]
    assert second.pagination.scan_id == first.pagination.scan_id
    assert second.pagination.cumulative_count == 3
    assert second.pagination.next_cursor is not None

    with pytest.raises(InvalidCursorError, match="consumed"):
        await executor.list_invitations(
            first_request.model_copy(
                update={
                    "request_id": "invitation-consumed-cursor",
                    "cursor": first.pagination.next_cursor,
                }
            )
        )

    third_request = first_request.model_copy(
        update={
            "request_id": "invitation-page-3",
            "cursor": second.pagination.next_cursor,
            "page_size": 2,
        }
    )
    third = await executor.list_invitations(third_request)
    assert [item.primary_entity.slug for item in third.invitations] == [
        "invitation-member-4",
        "invitation-member-5",
    ]
    assert third.pagination.scan_id == first.pagination.scan_id
    assert third.pagination.cumulative_count == 5
    assert third.pagination.has_more is False
    assert third.pagination.truncated is False
    assert third.coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE
    assert third.coverage.result_count == 2

    replay = await executor.list_invitations(second_request)
    assert replay.replayed is True
    assert replay.invitations == second.invitations
    assert replay.pagination == second.pagination
    assert invitations.calls == 3
    assert invitations.result_limits == [3, 4, 6]


@pytest.mark.asyncio
async def test_job_detail_accepts_any_valid_job_id_without_prior_search() -> None:
    repository = MemoryRepository()
    detail = FakeJobDetail()
    executor = _executor(repository, FakeJobSearch(), detail)

    output = await executor.get_job(
        JobDetailInput(
            context_id="context-1",
            request_id="direct-detail",
            job_id="4100000001",
        )
    )

    assert output.job.job_id == "4100000001"
    assert output.sources[0].resource_uri.startswith("linkedin://sources/")
    assert detail.calls == 1


@pytest.mark.asyncio
async def test_people_search_is_persisted_and_replayed_without_provider_call() -> None:
    repository = MemoryRepository()
    people_search = FakePeopleSearch()
    executor = _executor(
        repository,
        FakeJobSearch(),
        FakeJobDetail(),
        people_search=people_search,
    )
    request = PeopleSearchInput(
        context_id="context-1",
        request_id="people-search-1",
        query='"distributed systems" AND Python',
        title_keywords="staff engineer",
        page_size=10,
    )

    first = await executor.search_people(request)
    replay = await executor.search_people(request)

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.people == first.people
    assert first.people[0].profile_slug == "jane-doe"
    assert people_search.calls == 1


@pytest.mark.asyncio
async def test_connections_search_has_independent_replay_identity() -> None:
    repository = MemoryRepository()
    people_search = FakePeopleSearch()
    executor = _executor(
        repository,
        FakeJobSearch(),
        FakeJobDetail(),
        people_search=people_search,
    )
    request = ConnectionsSearchInput(
        context_id="connections-context",
        request_id="connections-search-1",
        filters=ConnectionsSearchFilters(
            title="Staff Engineer",
        ),
        page_size=10,
    )

    first = await executor.search_connections(request)
    replay = await executor.search_connections(request)

    assert first.replayed is False
    assert replay.replayed is True
    assert first.people[0].profile_slug == "jane-doe"
    assert first.coverage.filters.connection_degrees == (PeopleSearchConnectionDegree.FIRST,)
    assert people_search.calls == 1


@pytest.mark.asyncio
async def test_connections_search_rejects_non_first_degree_results() -> None:
    executor = _executor(
        MemoryRepository(),
        FakeJobSearch(),
        FakeJobDetail(),
        people_search=FakeNonConnectionPeopleSearch(),
    )

    with pytest.raises(ParserDriftError, match="not visibly first-degree"):
        await executor.search_connections(
            ConnectionsSearchInput(
                context_id="connections-context",
                request_id="connections-search-degree-drift",
                query="Jane Doe",
            )
        )


@pytest.mark.asyncio
async def test_person_profile_is_direct_and_persists_every_captured_page() -> None:
    repository = MemoryRepository()
    person_profile = FakePersonProfile()
    executor = _executor(
        repository,
        FakeJobSearch(),
        FakeJobDetail(),
        person_profile=person_profile,
    )

    output = await executor.get_person(
        PeopleGetInput(
            context_id="context-1",
            request_id="person-direct-1",
            profile_slug="jane-doe",
        )
    )

    assert output.person.profile_slug == "jane-doe"
    assert output.person.about == "Builds reliable systems."
    assert len(output.sources) == 2
    assert all(source.resource_uri.startswith("linkedin://sources/") for source in output.sources)
    assert person_profile.calls == 1


@pytest.mark.asyncio
async def test_person_profile_section_selection_is_part_of_idempotency_fingerprint() -> None:
    repository = MemoryRepository()
    person_profile = FakePersonProfile()
    executor = _executor(
        repository,
        FakeJobSearch(),
        FakeJobDetail(),
        person_profile=person_profile,
    )
    overview_request = PeopleGetInput(
        context_id="context-1",
        request_id="person-selective-1",
        profile_slug="jane-doe",
        sections=(PersonProfileSectionSelector.OVERVIEW,),
    )

    await executor.get_person(overview_request)

    with pytest.raises(IdempotencyConflictError, match="different arguments"):
        await executor.get_person(
            overview_request.model_copy(update={"sections": (PersonProfileSectionSelector.SKILLS,)})
        )
    assert person_profile.calls == 1


@pytest.mark.asyncio
async def test_company_reads_persist_evidence_replay_and_idempotency() -> None:
    repository = MemoryRepository()
    company_search = FakeCompanySearch()
    company_profile = FakeCompanyProfile()
    executor = _executor(
        repository,
        FakeJobSearch(),
        FakeJobDetail(),
        company_search=company_search,
        company_profile=company_profile,
    )
    search_request = CompanySearchInput(
        context_id="company-context",
        request_id="company-search-1",
        query="cloud",
    )

    search = await executor.search_companies(search_request)
    search_replay = await executor.search_companies(search_request)
    profile_request = CompanyGetInput(
        context_id="company-context",
        request_id="company-get-1",
        company_slug="acme-cloud",
    )
    profile = await executor.get_company(profile_request)
    profile_replay = await executor.get_company(profile_request)

    assert search.companies[0].company_slug == "acme-cloud"
    assert search_replay.replayed is True
    assert company_search.calls == 1
    assert profile.company.company_size_range == "1,001-5,000 employees"
    assert profile.sources[0].resource_uri.startswith("linkedin://sources/")
    assert profile_replay.replayed is True
    assert company_profile.calls == 1

    with pytest.raises(IdempotencyConflictError, match="different arguments"):
        await executor.get_company(
            profile_request.model_copy(update={"company_slug": "example-labs"})
        )


@pytest.mark.asyncio
async def test_post_discussion_reads_persist_exact_evidence_and_replay() -> None:
    repository = MemoryRepository()
    post_search = FakePostSearch()
    post_detail = FakePostDetail()
    post_comments = FakePostComments()
    executor = _executor(
        repository,
        FakeJobSearch(),
        FakeJobDetail(),
        post_search=post_search,
        post_detail=post_detail,
        post_comments=post_comments,
    )
    post_ref = "activity:7312345678901234567"
    search_request = PostSearchInput(
        context_id="post-context",
        request_id="post-search-1",
        query="python",
    )
    detail_request = PostGetInput(
        context_id="post-context",
        request_id="post-get-1",
        post_ref=post_ref,
    )
    comments_request = PostCommentsListInput(
        context_id="post-context",
        request_id="post-comments-1",
        post_ref=post_ref,
        sort_by=CommentSort.MOST_RECENT,
    )
    post_search_output = await executor.search_posts(search_request)
    post_detail_output = await executor.get_post(detail_request)
    comments_output = await executor.list_post_comments(comments_request)

    assert (await executor.search_posts(search_request)).replayed is True
    assert (await executor.get_post(detail_request)).replayed is True
    assert (await executor.list_post_comments(comments_request)).replayed is True
    assert post_search_output.posts[0].post_ref == post_ref
    assert post_detail_output.post.evidence[1].quote in post_detail_output.post.visible_text
    assert comments_output.threads[0].replies[0].parent_comment_ref == (
        comments_output.threads[0].comment.comment_ref
    )
    assert {
        post_search_output.sources[0].source_type.value,
        post_detail_output.sources[0].source_type.value,
        comments_output.sources[0].source_type.value,
    } == {
        "linkedin_post_search",
        "linkedin_post",
        "linkedin_post_comments",
    }
    assert (post_search.calls, post_detail.calls, post_comments.calls) == (1, 1, 1)


@pytest.mark.asyncio
async def test_connection_and_messaging_reads_are_persisted_and_replayed() -> None:
    repository = MemoryRepository()
    invitations = FakeInvitationList()
    executor = _executor(
        repository,
        FakeJobSearch(),
        FakeJobDetail(),
        invitation_list=invitations,
    )

    invitation_request = InvitationListInput(
        context_id="connections-context",
        request_id="invitations-1",
        direction=InvitationDirection.RECEIVED,
    )
    first = await executor.list_invitations(invitation_request)
    replay = await executor.list_invitations(invitation_request)
    connections_request = ConnectionsListInput(
        context_id="connections-context",
        request_id="connections-1",
    )
    connections = await executor.list_connections(connections_request)
    connections_replay = await executor.list_connections(connections_request)
    inbox_request = ConversationSearchInput(
        context_id="messaging-context",
        request_id="inbox-1",
        filter=ConversationFilter.UNREAD,
    )
    inbox = await executor.search_messages(inbox_request)
    inbox_replay = await executor.search_messages(inbox_request)
    conversation_request = ConversationGetInput(
        context_id="messaging-context",
        request_id="conversation-1",
        conversation_id="thread-123",
    )
    conversation = await executor.get_conversation(conversation_request)
    conversation_replay = await executor.get_conversation(conversation_request)

    assert first.invitations[0].note == "Hi, let us connect."
    assert replay.replayed is True
    assert invitations.calls == 1
    assert connections.connections[0].profile_slug == "jane-doe"
    assert connections_replay.replayed is True
    assert inbox.conversations[0].unread is True
    assert inbox_replay.replayed is True
    assert [message.direction for message in conversation.conversation.messages] == [
        MessageDirection.INCOMING,
        MessageDirection.OUTGOING,
    ]
    assert conversation_replay.replayed is True
    assert all(
        source.resource_uri.startswith("linkedin://sources/")
        for output in (first, connections, inbox, conversation)
        for source in output.sources
    )


@pytest.mark.asyncio
async def test_invitation_prepare_confirm_execute_and_attempt_replay() -> None:
    repository = MemoryRepository()
    actions = FakeInvitationActions()
    executor = _executor(
        repository,
        FakeJobSearch(),
        FakeJobDetail(),
        invitation_actions=actions,
    )
    prepare_request = InvitationSendPrepareInput(
        context_id="connections-context",
        request_id="invite-prepare-1",
        profile_slug="jane-doe",
        note="Hello Jane",
    )
    prepared = await executor.prepare_invitation_send(prepare_request)
    prepared_replay = await executor.prepare_invitation_send(prepare_request)
    assert prepared.status == "ready_for_confirmation"
    assert prepared.draft.status is ActionStatus.READY_FOR_CONFIRMATION
    assert prepared.approval_preview == action_approval_preview(prepared.draft)
    assert prepared.approval_preview.summary == (
        "Send a LinkedIn connection invitation to Jane Doe."
    )
    assert prepared_replay.replayed is True
    assert prepared_replay.draft == prepared.draft

    altered_preview = prepared.approval_preview.model_copy(
        update={"summary": "Send a different invitation."}
    )
    with pytest.raises(AuthorizationDeniedError, match="preview"):
        await executor.execute_invitation_send(
            ActionExecuteInput(
                context_id="connections-context",
                request_id="invite-altered-preview-1",
                action_id=prepared.draft.action_id,
                payload_hash=prepared.draft.payload_hash,
                approval_preview=altered_preview,
                idempotency_key="invite-action-1",
            )
        )

    first = await executor.execute_invitation_send(
        _execute_request(
            prepared.draft,
            context_id="connections-context",
            request_id="invite-execute-1",
            idempotency_key="invite-action-1",
        )
    )
    replay = await executor.execute_invitation_send(
        _execute_request(
            prepared.draft,
            context_id="connections-context",
            request_id="invite-execute-2",
            idempotency_key="invite-action-1",
        )
    )

    assert first.result.outcome is ActionOutcome.VERIFIED
    assert first.result.final_state == "pending_sent"
    assert replay.replayed is True
    assert replay.result == first.result
    assert actions.invite_executions == 1


@pytest.mark.asyncio
async def test_personal_post_prepare_confirmation_and_execution_are_hash_locked() -> None:
    repository = MemoryRepository()
    publishing = FakePostPublishing()
    executor = _executor(
        repository,
        FakeJobSearch(),
        FakeJobDetail(),
        post_publishing=publishing,
    )
    request = PostCreatePrepareInput(
        context_id="post-write-context",
        request_id="post-prepare-1",
        content=TextPostContent(text="Exact confirmed post"),
        brand_partnership=True,
        collaborators=(
            PostCollaboratorInput(
                profile_slug="alex-ray",
                display_name="Alex Ray",
            ),
        ),
    )

    prepared = await executor.prepare_post_create(request)
    replayed_prepare = await executor.prepare_post_create(request)

    assert prepared.draft.action_type is ActionType.POST_CREATE
    assert isinstance(prepared.draft.payload, PostCreatePayload)
    assert prepared.draft.payload.content == request.content
    assert prepared.draft.payload.brand_partnership is True
    assert prepared.draft.payload.collaborators == request.collaborators
    assert "brand partnership" in prepared.approval_preview.external_effect
    assert "Alex Ray" in prepared.approval_preview.external_effect
    assert prepared.draft.target.actor_profile_slug == "current-member"
    assert prepared.sources[0].source_type.value == "linkedin_action_preparation"
    assert replayed_prepare.replayed is True
    assert replayed_prepare.draft == prepared.draft
    assert publishing.asset_preparations == 1

    execute_request = _execute_request(
        prepared.draft,
        context_id="post-write-context",
        request_id="post-execute-1",
        idempotency_key="post-global-action-1",
    )
    altered_preview = prepared.approval_preview.model_copy(update={"payload_hash": "b" * 64})
    with pytest.raises(AuthorizationDeniedError, match="hash"):
        await executor.execute_post_create(
            execute_request.model_copy(
                update={
                    "request_id": "post-execute-altered-hash",
                    "payload_hash": "b" * 64,
                    "approval_preview": altered_preview,
                }
            )
        )

    first = await executor.execute_post_create(execute_request)
    replay = await executor.execute_post_create(
        execute_request.model_copy(update={"request_id": "post-execute-2"})
    )

    assert first.result.outcome is ActionOutcome.VERIFIED
    assert first.result.final_state == "post_published:activity:7312345678901234567"
    assert first.sources[0].source_type.value == "linkedin_action_execution"
    assert replay.replayed is True
    assert replay.result == first.result
    assert publishing.executions == 1

    with pytest.raises(IdempotencyConflictError, match="different arguments"):
        await executor.prepare_post_create(
            request.model_copy(update={"content": TextPostContent(text="Different post")})
        )


@pytest.mark.asyncio
async def test_comment_reply_and_reaction_actions_use_typed_confirmation_lifecycle() -> None:
    repository = MemoryRepository()
    engagement = FakePostEngagement()
    executor = _executor(
        repository,
        FakeJobSearch(),
        FakeJobDetail(),
        post_engagement=engagement,
    )
    comment_request = PostCommentPrepareInput(
        context_id="engagement-context",
        request_id="comment-prepare-1",
        post_ref="activity:7312345678901234567",
        parent_comment_ref="comment:activity:7312345678901234567:111",
        text="Exact confirmed reply.",
    )
    reaction_request = PostReactionPrepareInput(
        context_id="engagement-context",
        request_id="reaction-prepare-1",
        post_ref="activity:7312345678901234567",
        comment_ref="comment:activity:7312345678901234567:111",
        desired_reaction=ReactionState.LOVE,
    )

    comment = await executor.prepare_post_comment(comment_request)
    reaction = await executor.prepare_post_reaction(reaction_request)

    assert comment.draft.action_type is ActionType.COMMENT_CREATE
    assert isinstance(comment.draft.payload, CommentCreatePayload)
    assert comment.draft.payload.parent_comment_ref == comment_request.parent_comment_ref
    assert comment.draft.target.comment_ref == comment_request.parent_comment_ref
    assert comment.draft.target.content_author_name == "Alex Ray"
    assert reaction.draft.action_type is ActionType.REACTION_SET
    assert isinstance(reaction.draft.payload, ReactionSetPayload)
    assert reaction.draft.payload.existing_reaction is ReactionState.LIKE
    assert reaction.draft.payload.desired_reaction is ReactionState.LOVE
    assert comment.draft.payload_hash != reaction.draft.payload_hash
    assert engagement.asset_preparations == 1

    comment_execute = _execute_request(
        comment.draft,
        context_id="engagement-context",
        request_id="comment-execute-1",
        idempotency_key="comment-global-action-1",
    )
    reaction_execute = _execute_request(
        reaction.draft,
        context_id="engagement-context",
        request_id="reaction-execute-1",
        idempotency_key="reaction-global-action-1",
    )
    comment_result = await executor.execute_post_comment(comment_execute)
    reaction_result = await executor.execute_post_reaction(reaction_execute)
    comment_replay = await executor.execute_post_comment(
        comment_execute.model_copy(update={"request_id": "comment-execute-2"})
    )
    reaction_replay = await executor.execute_post_reaction(
        reaction_execute.model_copy(update={"request_id": "reaction-execute-2"})
    )

    assert comment_result.result.outcome is ActionOutcome.VERIFIED
    assert comment_result.result.final_state.startswith("comment_published:")
    assert reaction_result.result.outcome is ActionOutcome.VERIFIED
    assert reaction_result.result.final_state == "reaction_set:love"
    assert comment_replay.replayed is True
    assert reaction_replay.replayed is True
    assert engagement.comment_executions == 1
    assert engagement.reaction_executions == 1


@pytest.mark.asyncio
async def test_accept_ignore_and_message_actions_use_separate_typed_adapters() -> None:
    repository = MemoryRepository()
    actions = FakeInvitationActions()
    conversation = FakeConversation()
    executor = _executor(
        repository,
        FakeJobSearch(),
        FakeJobDetail(),
        invitation_actions=actions,
        conversation=conversation,
    )

    acceptance = await executor.prepare_invitation_accept(
        InvitationAcceptPrepareInput(
            context_id="connections-context",
            request_id="accept-prepare-1",
            profile_slug="jane-doe",
        )
    )
    ignore = await executor.prepare_invitation_ignore(
        InvitationIgnorePrepareInput(
            context_id="connections-context",
            request_id="ignore-prepare-1",
            profile_slug="jane-doe",
        )
    )
    message = await executor.prepare_message(
        MessagePrepareInput(
            context_id="messaging-context",
            request_id="message-prepare-1",
            conversation_id="thread-123",
            message="Thanks for getting in touch.",
        )
    )
    attachment_message = await executor.prepare_message(
        MessagePrepareInput(
            context_id="messaging-context",
            request_id="message-attachment-prepare-1",
            conversation_id="thread-123",
            message="The brief is attached.",
            attachments=(MessageFileInput(asset_ref="brief.pdf"),),
        )
    )
    gif_message = await executor.prepare_message(
        MessagePrepareInput(
            context_id="messaging-context",
            request_id="message-gif-prepare-1",
            conversation_id="thread-123",
            gif=MessageGifInput(
                search_query="dancing robot",
                result_title="Dancing robot GIF",
            ),
        )
    )
    accepted = await executor.execute_invitation_accept(
        _execute_request(
            acceptance.draft,
            context_id="connections-context",
            request_id="accept-execute-1",
            idempotency_key="accept-action-1",
        )
    )
    ignored = await executor.execute_invitation_ignore(
        _execute_request(
            ignore.draft,
            context_id="connections-context",
            request_id="ignore-execute-1",
            idempotency_key="ignore-action-1",
        )
    )
    sent = await executor.execute_message(
        _execute_request(
            message.draft,
            context_id="messaging-context",
            request_id="message-execute-1",
            idempotency_key="message-action-1",
        )
    )
    attachment_sent = await executor.execute_message(
        _execute_request(
            attachment_message.draft,
            context_id="messaging-context",
            request_id="message-attachment-execute-1",
            idempotency_key="message-attachment-action-1",
        )
    )
    gif_sent = await executor.execute_message(
        _execute_request(
            gif_message.draft,
            context_id="messaging-context",
            request_id="message-gif-execute-1",
            idempotency_key="message-gif-action-1",
        )
    )

    assert accepted.result.final_state == "connected"
    assert ignored.result.final_state == "invitation_ignored"
    assert ignore.draft.action_type is ActionType.INVITATION_IGNORE
    assert ignore.approval_preview.summary == ("Ignore Jane Doe's LinkedIn connection invitation.")
    assert "without creating a connection" in ignore.approval_preview.external_effect
    assert sent.result.final_state == "message_sent"
    assert attachment_sent.result.final_state == "message_sent"
    assert gif_sent.result.final_state == "message_sent"
    assert isinstance(attachment_message.draft.payload, MessageSendPayload)
    assert isinstance(gif_message.draft.payload, MessageSendPayload)
    assert attachment_message.draft.payload.attachment_refs == ("brief.pdf",)
    assert attachment_message.draft.payload.assets[0].role is PostAssetRole.MESSAGE_ATTACHMENT
    assert gif_message.draft.payload.gif is not None
    assert actions.accept_executions == 1
    assert actions.ignore_executions == 1
    assert conversation.message_executions == 3


@pytest.mark.asyncio
async def test_incoming_action_preparation_requires_an_exact_invitation_reference() -> None:
    executor = _executor(
        MemoryRepository(),
        FakeJobSearch(),
        FakeJobDetail(),
        invitation_actions=MissingReferenceActions(),
    )

    with pytest.raises(RuntimeError, match="invitation reference"):
        await executor.prepare_invitation_accept(
            InvitationAcceptPrepareInput(
                context_id="connections-context",
                request_id="missing-invitation-reference",
                profile_slug="jane-doe",
            )
        )
    with pytest.raises(RuntimeError, match="invitation reference"):
        await executor.prepare_invitation_ignore(
            InvitationIgnorePrepareInput(
                context_id="connections-context",
                request_id="missing-ignore-invitation-reference",
                profile_slug="jane-doe",
            )
        )


@pytest.mark.parametrize("cancelled", [False, True], ids=["exception", "cancellation"])
@pytest.mark.asyncio
async def test_reserved_action_failures_become_durable_uncertain_outcomes(
    cancelled: bool,
) -> None:
    repository = MemoryRepository()
    executor = _executor(
        repository,
        FakeJobSearch(),
        FakeJobDetail(),
        invitation_actions=InterruptedInvitationActions(cancelled=cancelled),
    )
    prepared = await executor.prepare_invitation_send(
        InvitationSendPrepareInput(
            context_id="connections-context",
            request_id=f"interrupted-prepare-{cancelled}",
            profile_slug="jane-doe",
        )
    )
    request = _execute_request(
        prepared.draft,
        context_id="connections-context",
        request_id=f"interrupted-execute-{cancelled}",
        idempotency_key=f"interrupted-action-{cancelled}",
    )

    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            await executor.execute_invitation_send(request)
        stored = await repository.get_action(
            account_id="personal",
            action_id=prepared.draft.action_id,
        )
        assert stored is not None
        assert stored.status is ActionStatus.UNCERTAIN
    else:
        output = await executor.execute_invitation_send(request)
        replay = await executor.execute_invitation_send(request)
        assert output.result.outcome is ActionOutcome.UNCERTAIN
        assert output.result.performed is None
        assert replay.replayed is True
        assert replay.result == output.result


@pytest.mark.asyncio
async def test_failure_recording_never_replaces_the_original_capability_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = FailureRecordingRepository()
    search = FakeJobSearch()
    executor = _executor(repository, search, FakeJobDetail())

    async def unexpected(
        _request: JobSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[
        tuple[JobSummary, ...],
        JobSearchCoverage,
        str,
        str,
    ]:
        del result_limit
        raise RuntimeError("sensitive implementation detail")

    def discard_log(_: str, **values: object) -> None:
        del values

    monkeypatch.setattr(search, "collect", unexpected)
    monkeypatch.setattr(executor_module.logger, "error", discard_log)

    with pytest.raises(RuntimeError, match="sensitive implementation detail"):
        await executor.search_jobs(
            JobSearchInput(
                context_id="failure-context",
                request_id="failure-recording",
                query="python",
            )
        )


def test_safe_capability_error_preserves_known_errors_and_hides_unknown_details() -> None:
    known = InvalidTargetError("Safe target error.")

    assert safe_capability_error(known) is known
    projected = safe_capability_error(RuntimeError("secret"))
    assert isinstance(projected, InternalServerError)
    assert "secret" not in projected.safe_message
