"""Behavioral tests for tool-owned execution functions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from pydantic import HttpUrl

from linkedin_mcp.config import Settings
from linkedin_mcp.errors import (
    InternalServerError,
    InvalidCursorError,
    InvalidTargetError,
    ParserDriftError,
)
from linkedin_mcp.pagination import PaginationManager
from linkedin_mcp.tools._shared.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutcome,
    ActionOutput,
    ActionPageResult,
    ActionTarget,
    ReactionSetPayload,
    ReactionState,
)
from linkedin_mcp.tools._shared.models import (
    EvidenceField,
    StopReason,
)
from linkedin_mcp.tools._shared.tool import safe_capability_error
from linkedin_mcp.tools.companies.get import tool as company_get_tool
from linkedin_mcp.tools.companies.get.models.company_get_input import CompanyGetInput
from linkedin_mcp.tools.companies.get.models.company_get_output import CompanyGetOutput
from linkedin_mcp.tools.companies.get.models.company_profile_coverage import CompanyProfileCoverage
from linkedin_mcp.tools.companies.get.models.company_profile_evidence import CompanyProfileEvidence
from linkedin_mcp.tools.companies.get.models.company_profile_observation import (
    CompanyProfileObservation,
)
from linkedin_mcp.tools.companies.get.models.company_profile_page_capture import (
    CompanyProfilePageCapture,
)
from linkedin_mcp.tools.companies.get.page import CompanyProfilePage
from linkedin_mcp.tools.companies.search import pagination as company_search
from linkedin_mcp.tools.companies.search.models.company_search_coverage import CompanySearchCoverage
from linkedin_mcp.tools.companies.search.models.company_search_input import CompanySearchInput
from linkedin_mcp.tools.companies.search.models.company_search_output import CompanySearchOutput
from linkedin_mcp.tools.companies.search.models.company_summary import CompanySummary
from linkedin_mcp.tools.companies.search.page import CompanySearchPage
from linkedin_mcp.tools.connections.list import pagination as connections_list
from linkedin_mcp.tools.connections.list.models.connection_summary import ConnectionSummary
from linkedin_mcp.tools.connections.list.models.connections_list_coverage import (
    ConnectionsListCoverage,
)
from linkedin_mcp.tools.connections.list.models.connections_list_input import ConnectionsListInput
from linkedin_mcp.tools.connections.list.models.connections_list_output import (
    ConnectionsListOutput,
)
from linkedin_mcp.tools.connections.list.page import ConnectionsListPage
from linkedin_mcp.tools.connections.search import pagination as connections_search
from linkedin_mcp.tools.connections.search.models.connections_search_filters import (
    ConnectionsSearchFilters,
)
from linkedin_mcp.tools.connections.search.models.connections_search_input import (
    ConnectionsSearchInput,
)
from linkedin_mcp.tools.connections.search.models.connections_search_output import (
    ConnectionsSearchOutput,
)
from linkedin_mcp.tools.connections.search.page import ConnectionsSearchPage
from linkedin_mcp.tools.invitations.accept import tool as invitation_accept_tool
from linkedin_mcp.tools.invitations.accept.models.invitation_accept_input import (
    InvitationAcceptInput,
)
from linkedin_mcp.tools.invitations.accept.page import AcceptInvitationPage
from linkedin_mcp.tools.invitations.ignore import tool as invitation_ignore_tool
from linkedin_mcp.tools.invitations.ignore.models.invitation_ignore_input import (
    InvitationIgnoreInput,
)
from linkedin_mcp.tools.invitations.ignore.page import IgnoreInvitationPage
from linkedin_mcp.tools.invitations.list import pagination as invitations_list
from linkedin_mcp.tools.invitations.list.models.invitation_available_action import (
    InvitationAvailableAction,
)
from linkedin_mcp.tools.invitations.list.models.invitation_direction import InvitationDirection
from linkedin_mcp.tools.invitations.list.models.invitation_entity import InvitationEntity
from linkedin_mcp.tools.invitations.list.models.invitation_entity_type import InvitationEntityType
from linkedin_mcp.tools.invitations.list.models.invitation_evidence import InvitationEvidence
from linkedin_mcp.tools.invitations.list.models.invitation_filter import (
    CURRENT_RECEIVED_INVITATION_VIEWS,
    InvitationFilter,
)
from linkedin_mcp.tools.invitations.list.models.invitation_list_coverage import (
    InvitationListCoverage,
)
from linkedin_mcp.tools.invitations.list.models.invitation_list_input import InvitationListInput
from linkedin_mcp.tools.invitations.list.models.invitation_list_output import InvitationListOutput
from linkedin_mcp.tools.invitations.list.models.invitation_summary import InvitationSummary
from linkedin_mcp.tools.invitations.list.models.invitation_type import InvitationType
from linkedin_mcp.tools.invitations.list.page import InvitationListPage
from linkedin_mcp.tools.invitations.send import tool as invitation_send_tool
from linkedin_mcp.tools.invitations.send.models.invitation_send_input import InvitationSendInput
from linkedin_mcp.tools.invitations.send.page import SendInvitationPage
from linkedin_mcp.tools.jobs.get import tool as job_get_tool
from linkedin_mcp.tools.jobs.get.models.job_detail_input import JobDetailInput
from linkedin_mcp.tools.jobs.get.models.job_detail_observation import JobDetailObservation
from linkedin_mcp.tools.jobs.get.models.job_detail_output import JobDetailOutput
from linkedin_mcp.tools.jobs.get.page import JobDetailPage
from linkedin_mcp.tools.jobs.search import pagination as job_search
from linkedin_mcp.tools.jobs.search.models.job_search_coverage import JobSearchCoverage
from linkedin_mcp.tools.jobs.search.models.job_search_input import JobSearchInput
from linkedin_mcp.tools.jobs.search.models.job_search_output import JobSearchOutput
from linkedin_mcp.tools.jobs.search.models.job_summary import JobSummary
from linkedin_mcp.tools.jobs.search.page import JobSearchPage
from linkedin_mcp.tools.messaging.conversation.get import tool as conversation_get_tool
from linkedin_mcp.tools.messaging.conversation.get.models.conversation_coverage import (
    ConversationCoverage,
)
from linkedin_mcp.tools.messaging.conversation.get.models.conversation_get_input import (
    ConversationGetInput,
)
from linkedin_mcp.tools.messaging.conversation.get.models.conversation_get_output import (
    ConversationGetOutput,
)
from linkedin_mcp.tools.messaging.conversation.get.models.conversation_observation import (
    ConversationObservation,
)
from linkedin_mcp.tools.messaging.conversation.get.models.message_direction import MessageDirection
from linkedin_mcp.tools.messaging.conversation.get.models.message_observation import (
    MessageObservation,
)
from linkedin_mcp.tools.messaging.conversation.get.page import ConversationGetPage
from linkedin_mcp.tools.messaging.search import pagination as messaging_search
from linkedin_mcp.tools.messaging.search.models.conversation_filter import ConversationFilter
from linkedin_mcp.tools.messaging.search.models.conversation_search_coverage import (
    ConversationSearchCoverage,
)
from linkedin_mcp.tools.messaging.search.models.conversation_search_input import (
    ConversationSearchInput,
)
from linkedin_mcp.tools.messaging.search.models.conversation_search_output import (
    ConversationSearchOutput,
)
from linkedin_mcp.tools.messaging.search.models.conversation_summary import ConversationSummary
from linkedin_mcp.tools.messaging.search.page import ConversationSearchPage
from linkedin_mcp.tools.messaging.send import tool as message_send_tool
from linkedin_mcp.tools.messaging.send.models.message_send_input import MessageSendInput
from linkedin_mcp.tools.messaging.send.page import MessageSendPage
from linkedin_mcp.tools.people.get import tool as people_get_tool
from linkedin_mcp.tools.people.get.models.people_get_input import PeopleGetInput
from linkedin_mcp.tools.people.get.models.people_get_output import PeopleGetOutput
from linkedin_mcp.tools.people.get.models.person_profile_coverage import PersonProfileCoverage
from linkedin_mcp.tools.people.get.models.person_profile_evidence import PersonProfileEvidence
from linkedin_mcp.tools.people.get.models.person_profile_observation import PersonProfileObservation
from linkedin_mcp.tools.people.get.models.person_profile_page_capture import (
    PersonProfilePageCapture,
)
from linkedin_mcp.tools.people.get.models.person_profile_section_selector import (
    PersonProfileSectionSelector,
)
from linkedin_mcp.tools.people.get.page import PersonProfilePage
from linkedin_mcp.tools.people.models.person_connection_degree import PersonConnectionDegree
from linkedin_mcp.tools.people.search import pagination as people_search
from linkedin_mcp.tools.people.search.models.people_search_connection_degree import (
    PeopleSearchConnectionDegree,
)
from linkedin_mcp.tools.people.search.models.people_search_coverage import PeopleSearchCoverage
from linkedin_mcp.tools.people.search.models.people_search_input import PeopleSearchInput
from linkedin_mcp.tools.people.search.models.people_search_output import PeopleSearchOutput
from linkedin_mcp.tools.people.search.models.person_summary import PersonSummary
from linkedin_mcp.tools.people.search.page import PeopleSearchPage
from linkedin_mcp.tools.posts.comment import tool as post_comment_tool
from linkedin_mcp.tools.posts.comment.models.post_comment_input import PostCommentInput
from linkedin_mcp.tools.posts.comment.page import PostCommentPage
from linkedin_mcp.tools.posts.comments.list import pagination as post_comments_list
from linkedin_mcp.tools.posts.comments.list.models.comment_observation import CommentObservation
from linkedin_mcp.tools.posts.comments.list.models.comment_sort import CommentSort
from linkedin_mcp.tools.posts.comments.list.models.comment_thread import CommentThread
from linkedin_mcp.tools.posts.comments.list.models.post_comments_coverage import (
    PostCommentsCoverage,
)
from linkedin_mcp.tools.posts.comments.list.models.post_comments_list_input import (
    PostCommentsListInput,
)
from linkedin_mcp.tools.posts.comments.list.models.post_comments_list_output import (
    PostCommentsListOutput,
)
from linkedin_mcp.tools.posts.comments.list.page import PostCommentsPage
from linkedin_mcp.tools.posts.create import tool as post_create_tool
from linkedin_mcp.tools.posts.create.models.post_create_input import PostCreateInput
from linkedin_mcp.tools.posts.create.models.text_post_content import TextPostContent
from linkedin_mcp.tools.posts.create.page import PostPublishingPage
from linkedin_mcp.tools.posts.get import tool as post_get_tool
from linkedin_mcp.tools.posts.get.models.post_author_type import PostAuthorType
from linkedin_mcp.tools.posts.get.models.post_detail_coverage import PostDetailCoverage
from linkedin_mcp.tools.posts.get.models.post_evidence import PostEvidence
from linkedin_mcp.tools.posts.get.models.post_get_input import PostGetInput
from linkedin_mcp.tools.posts.get.models.post_get_output import PostGetOutput
from linkedin_mcp.tools.posts.get.models.post_observation import PostObservation
from linkedin_mcp.tools.posts.get.page import PostDetailPage
from linkedin_mcp.tools.posts.models.post_author import PostAuthor
from linkedin_mcp.tools.posts.react import tool as post_react_tool
from linkedin_mcp.tools.posts.react.models.post_reaction_input import PostReactionInput
from linkedin_mcp.tools.posts.react.page import PostReactionPage
from linkedin_mcp.tools.posts.search import pagination as post_search
from linkedin_mcp.tools.posts.search.models.post_search_coverage import PostSearchCoverage
from linkedin_mcp.tools.posts.search.models.post_search_input import PostSearchInput
from linkedin_mcp.tools.posts.search.models.post_search_output import PostSearchOutput
from linkedin_mcp.tools.posts.search.models.post_summary import PostSummary
from linkedin_mcp.tools.posts.search.page import PostSearchPage


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
                max_results=request.page_size,
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
        request: PeopleSearchInput | ConnectionsSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[PersonSummary, ...], PeopleSearchCoverage, str, str]:
        del result_limit
        if isinstance(request, ConnectionsSearchInput):
            request = request.as_people_search_input()
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
                filters=request.filters,
                pages_visited=1,
                result_count=1,
                max_results=request.page_size,
                stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=now,
            ),
            visible_text,
            "https://www.linkedin.com/search/results/people/?keywords=python",
        )


class FakeNonConnectionPeopleSearch(FakePeopleSearch):
    async def collect(
        self,
        request: PeopleSearchInput | ConnectionsSearchInput,
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
                max_results=request.page_size,
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
                unsupported_result_count=1,
                max_results=request.page_size,
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
                max_comments=request.page_size,
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


class ImplicitEmptyInvitationList(FakeInvitationList):
    async def collect(
        self,
        request: InvitationListInput,
        *,
        result_limit: int | None = None,
        progress: object | None = None,
    ) -> tuple[tuple[InvitationSummary, ...], InvitationListCoverage, str, str]:
        del progress
        self.calls += 1
        assert request.direction is InvitationDirection.SENT
        assert request.resolved_filter is InvitationFilter.PEOPLE
        limit = request.page_size if result_limit is None else result_limit
        captured_at = datetime.now(UTC)
        source_url = "https://www.linkedin.com/mynetwork/invitation-manager/sent/"
        return (
            (),
            InvitationListCoverage(
                direction=request.direction,
                invitation_filter=request.resolved_filter,
                advertised_count=None,
                unique_count=0,
                view_counts={InvitationFilter.PEOPLE: 0},
                unadvertised_empty_views=(InvitationFilter.PEOPLE,),
                view_source_urls={InvitationFilter.PEOPLE: HttpUrl(source_url)},
                view_membership_count=0,
                overlap_count=0,
                result_count=0,
                max_results=limit,
                scroll_rounds=0,
                collection_attempts=1,
                neighboring_recommendation_count=0,
                invitation_type_counts={},
                entity_type_counts={},
                stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=captured_at,
            ),
            "Manage invitations",
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
                max_results=request.page_size,
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
                max_results=request.page_size,
                stop_reason=StopReason.VISIBLE_PAGE_COMPLETE,
                captured_at=now,
            ),
            text,
            "https://www.linkedin.com/messaging/",
        )


class FakeInvitationActions:
    def __init__(self) -> None:
        self.invite_actions = 0
        self.accept_actions = 0
        self.ignore_actions = 0

    async def inspect_send(
        self,
        request: InvitationSendInput,
    ) -> ActionInspection:
        return _action_capture(request.profile_slug)

    async def inspect_accept(
        self,
        request: InvitationAcceptInput,
    ) -> ActionInspection:
        capture = _action_capture(request.profile_slug)
        return capture.model_copy(
            update={
                "target": capture.target.model_copy(
                    update={"invitation_ref": "invitation:" + "a" * 24}
                ),
                "current_state": "received_invitation_pending",
            }
        )

    async def inspect_ignore(
        self,
        request: InvitationIgnoreInput,
    ) -> ActionInspection:
        return await self.inspect_accept(
            InvitationAcceptInput(
                context_id=request.context_id,
                request_id=request.request_id,
                profile_slug=request.profile_slug,
            )
        )

    async def perform_send(self, command: ActionCommand) -> ActionPageResult:
        self.invite_actions += 1
        return _page_result("pending_sent")

    async def perform_accept(self, command: ActionCommand) -> ActionPageResult:
        self.accept_actions += 1
        return _page_result("connected")

    async def perform_ignore(self, command: ActionCommand) -> ActionPageResult:
        self.ignore_actions += 1
        return _page_result("invitation_ignored")


class FakePostPublishing:
    def __init__(self) -> None:
        self.post_actions = 0

    async def inspect_post(
        self,
        request: PostCreateInput,
    ) -> ActionInspection:
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

    async def perform_post(self, command: ActionCommand) -> ActionPageResult:
        del command
        self.post_actions += 1
        return _page_result("post_published:activity:7312345678901234567")


class FakePostEngagement:
    def __init__(self) -> None:
        self.comment_actions = 0
        self.reaction_actions = 0

    async def inspect_comment(
        self,
        request: PostCommentInput,
    ) -> ActionInspection:
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
                        "content_author_name": "Jane Doe",
                        "content_author_url": HttpUrl("https://www.linkedin.com/in/jane-doe/"),
                    }
                ),
                "current_state": "comment_composer_ready",
            }
        )

    async def perform_comment(self, command: ActionCommand) -> ActionPageResult:
        del command
        self.comment_actions += 1
        return _page_result("comment_published:comment:activity:7312345678901234567:900")

    async def inspect_reaction(
        self,
        request: PostReactionInput,
    ) -> ActionInspection:
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
                        "content_author_name": "Jane Doe",
                        "content_author_url": HttpUrl("https://www.linkedin.com/in/jane-doe/"),
                    }
                ),
                "current_state": "reaction_ready",
                "existing_reaction": ReactionState.NONE,
            }
        )

    async def perform_reaction(self, command: ActionCommand) -> ActionPageResult:
        assert isinstance(command.payload, ReactionSetPayload)
        self.reaction_actions += 1
        return _page_result(f"reaction_set:{command.payload.desired_reaction.value}")


class MissingReferenceActions(FakeInvitationActions):
    async def inspect_accept(
        self,
        request: InvitationAcceptInput,
    ) -> ActionInspection:
        return _action_capture(request.profile_slug)

    async def inspect_ignore(
        self,
        request: InvitationIgnoreInput,
    ) -> ActionInspection:
        return _action_capture(request.profile_slug)


class InterruptedInvitationActions(FakeInvitationActions):
    def __init__(self, *, cancelled: bool) -> None:
        super().__init__()
        self.cancelled = cancelled

    async def perform_send(self, command: ActionCommand) -> ActionPageResult:
        del command
        if self.cancelled:
            raise asyncio.CancelledError
        raise RuntimeError("browser stopped after action dispatch")


class RejectedInvitationActions(FakeInvitationActions):
    async def perform_send(self, command: ActionCommand) -> ActionPageResult:
        del command
        raise InvalidTargetError("The exact invitation target is no longer available.")


class FakeConversation:
    def __init__(self) -> None:
        self.message_actions = 0

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

    async def inspect_message(
        self,
        request: MessageSendInput,
    ) -> ActionInspection:
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

    async def perform_message(self, command: ActionCommand) -> ActionPageResult:
        self.message_actions += 1
        return _page_result("message_sent")


def _action_capture(profile_slug: str) -> ActionInspection:
    return ActionInspection(
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


def _settings() -> Settings:
    return Settings(minimum_navigation_interval_seconds=0)


class _ToolHarness:
    """Call tool-owned execution functions without MCP transport or queue wiring."""

    def __init__(
        self,
        *,
        settings: Settings,
        job_search_page: FakeJobSearch,
        job_detail_page: FakeJobDetail,
        people_search_page: FakePeopleSearch,
        person_profile_page: FakePersonProfile,
        company_search_page: FakeCompanySearch,
        company_profile_page: FakeCompanyProfile,
        post_search_page: FakePostSearch,
        post_detail_page: FakePostDetail,
        post_comments_page: FakePostComments,
        post_publishing_page: FakePostPublishing,
        post_engagement_page: FakePostEngagement,
        invitation_list_page: FakeInvitationList,
        connections_list_page: FakeConnectionsList,
        invitation_actions_page: FakeInvitationActions,
        conversation_search_page: FakeConversationSearch,
        conversation_page: FakeConversation,
    ) -> None:
        self._settings = settings
        self._pagination = PaginationManager(
            ttl_seconds=settings.pagination_cursor_ttl_seconds,
            max_active_cursors=settings.pagination_max_active_cursors,
            max_seen_items_per_cursor=settings.pagination_max_seen_items_per_cursor,
        )
        self._job_search = cast(JobSearchPage, job_search_page)
        self._job_detail = cast(JobDetailPage, job_detail_page)
        self._people_search = cast(PeopleSearchPage, people_search_page)
        self._connections_search = cast(ConnectionsSearchPage, people_search_page)
        self._person_profile = cast(PersonProfilePage, person_profile_page)
        self._company_search = cast(CompanySearchPage, company_search_page)
        self._company_profile = cast(CompanyProfilePage, company_profile_page)
        self._post_search = cast(PostSearchPage, post_search_page)
        self._post_detail = cast(PostDetailPage, post_detail_page)
        self._post_comments = cast(PostCommentsPage, post_comments_page)
        self._post_publishing = cast(PostPublishingPage, post_publishing_page)
        self._post_comment = cast(PostCommentPage, post_engagement_page)
        self._post_reaction = cast(PostReactionPage, post_engagement_page)
        self._invitation_list = cast(InvitationListPage, invitation_list_page)
        self._connections_list = cast(ConnectionsListPage, connections_list_page)
        self._invitation_send = cast(SendInvitationPage, invitation_actions_page)
        self._invitation_accept = cast(AcceptInvitationPage, invitation_actions_page)
        self._invitation_ignore = cast(IgnoreInvitationPage, invitation_actions_page)
        self._conversation_search = cast(ConversationSearchPage, conversation_search_page)
        self._conversation_read = cast(ConversationGetPage, conversation_page)
        self._message_send = cast(MessageSendPage, conversation_page)

    async def search_jobs(self, request: JobSearchInput) -> JobSearchOutput:
        return await job_search.execute(
            request,
            page=self._job_search,
            pagination=self._pagination,
            account_id=self._settings.account_id,
        )

    async def get_job(self, request: JobDetailInput) -> JobDetailOutput:
        return await job_get_tool.execute(request, self._job_detail)

    async def search_people(self, request: PeopleSearchInput) -> PeopleSearchOutput:
        return await people_search.execute(
            request,
            page=self._people_search,
            pagination=self._pagination,
            account_id=self._settings.account_id,
        )

    async def search_connections(
        self,
        request: ConnectionsSearchInput,
    ) -> ConnectionsSearchOutput:
        return await connections_search.execute(
            request,
            page=self._connections_search,
            pagination=self._pagination,
            account_id=self._settings.account_id,
        )

    async def get_person(self, request: PeopleGetInput) -> PeopleGetOutput:
        return await people_get_tool.execute(request, self._person_profile)

    async def search_companies(self, request: CompanySearchInput) -> CompanySearchOutput:
        return await company_search.execute(
            request,
            page=self._company_search,
            pagination=self._pagination,
            account_id=self._settings.account_id,
        )

    async def get_company(self, request: CompanyGetInput) -> CompanyGetOutput:
        return await company_get_tool.execute(request, self._company_profile)

    async def search_posts(self, request: PostSearchInput) -> PostSearchOutput:
        return await post_search.execute(
            request,
            page=self._post_search,
            pagination=self._pagination,
            account_id=self._settings.account_id,
        )

    async def get_post(self, request: PostGetInput) -> PostGetOutput:
        return await post_get_tool.execute(request, self._post_detail)

    async def list_post_comments(
        self,
        request: PostCommentsListInput,
    ) -> PostCommentsListOutput:
        return await post_comments_list.execute(
            request,
            page=self._post_comments,
            pagination=self._pagination,
            account_id=self._settings.account_id,
        )

    async def list_invitations(self, request: InvitationListInput) -> InvitationListOutput:
        return await invitations_list.execute(
            request,
            page=self._invitation_list,
            pagination=self._pagination,
            account_id=self._settings.account_id,
        )

    async def list_connections(self, request: ConnectionsListInput) -> ConnectionsListOutput:
        return await connections_list.execute(
            request,
            page=self._connections_list,
            pagination=self._pagination,
            account_id=self._settings.account_id,
        )

    async def search_messages(
        self,
        request: ConversationSearchInput,
    ) -> ConversationSearchOutput:
        return await messaging_search.execute(
            request,
            page=self._conversation_search,
            pagination=self._pagination,
            account_id=self._settings.account_id,
        )

    async def get_conversation(self, request: ConversationGetInput) -> ConversationGetOutput:
        return await conversation_get_tool.execute(request, self._conversation_read)

    async def create_post(self, request: PostCreateInput) -> ActionOutput:
        return await post_create_tool.execute(request, self._post_publishing)

    async def comment_on_post(self, request: PostCommentInput) -> ActionOutput:
        return await post_comment_tool.execute(request, self._post_comment)

    async def react_to_post(self, request: PostReactionInput) -> ActionOutput:
        return await post_react_tool.execute(request, self._post_reaction)

    async def send_invitation(self, request: InvitationSendInput) -> ActionOutput:
        return await invitation_send_tool.execute(request, self._invitation_send)

    async def accept_invitation(self, request: InvitationAcceptInput) -> ActionOutput:
        return await invitation_accept_tool.execute(request, self._invitation_accept)

    async def ignore_invitation(self, request: InvitationIgnoreInput) -> ActionOutput:
        return await invitation_ignore_tool.execute(request, self._invitation_ignore)

    async def send_message(self, request: MessageSendInput) -> ActionOutput:
        return await message_send_tool.execute(request, self._message_send)


def _tools(
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
) -> _ToolHarness:
    selected_people_search = people_search or FakePeopleSearch()
    selected_post_engagement = post_engagement or FakePostEngagement()
    selected_invitation_actions = invitation_actions or FakeInvitationActions()
    selected_conversation = conversation or FakeConversation()
    return _ToolHarness(
        settings=_settings(),
        job_search_page=search,
        job_detail_page=detail,
        people_search_page=selected_people_search,
        person_profile_page=person_profile or FakePersonProfile(),
        company_search_page=company_search or FakeCompanySearch(),
        company_profile_page=company_profile or FakeCompanyProfile(),
        post_search_page=post_search or FakePostSearch(),
        post_detail_page=post_detail or FakePostDetail(),
        post_comments_page=post_comments or FakePostComments(),
        post_publishing_page=post_publishing or FakePostPublishing(),
        post_engagement_page=selected_post_engagement,
        invitation_list_page=invitation_list or FakeInvitationList(),
        connections_list_page=connections_list or FakeConnectionsList(),
        invitation_actions_page=selected_invitation_actions,
        conversation_search_page=conversation_search or FakeConversationSearch(),
        conversation_page=selected_conversation,
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
        "_conversation_read",
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
    ("provider_attribute", "provider_method", "tool_method", "capability_request"),
    _READ_FAILURE_CASES,
)
@pytest.mark.parametrize("cancelled", [False, True], ids=["safe-error", "cancelled"])
@pytest.mark.asyncio
async def test_read_failures_are_not_cached_and_each_invocation_executes(
    provider_attribute: str,
    provider_method: str,
    tool_method: str,
    capability_request: object,
    cancelled: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _tools(FakeJobSearch(), FakeJobDetail())
    provider = getattr(tools, provider_attribute)
    attempts = 0

    async def fail(_request: object, **_kwargs: object) -> Any:
        nonlocal attempts
        attempts += 1
        if cancelled:
            raise asyncio.CancelledError
        raise InvalidTargetError("The visible LinkedIn target changed.")

    monkeypatch.setattr(provider, provider_method, fail)
    invoke = getattr(tools, tool_method)

    expected_error = asyncio.CancelledError if cancelled else InvalidTargetError
    for _ in range(2):
        with pytest.raises(expected_error):
            await invoke(capability_request)
    assert attempts == 2


@pytest.mark.asyncio
async def test_repeated_job_search_executes_provider_each_time() -> None:
    search = FakeJobSearch()
    tools = _tools(search, FakeJobDetail())
    request = JobSearchInput(
        context_id="context-1",
        request_id="request-1",
        query="python",
        page_size=10,
    )

    first = await tools.search_jobs(request)
    second = await tools.search_jobs(request)

    assert second.jobs == first.jobs
    assert search.calls == 2


@pytest.mark.asyncio
async def test_job_search_cursor_walks_live_prefix_without_duplicates() -> None:
    search = PaginatedFakeJobSearch()
    tools = _tools(search, FakeJobDetail())
    first_request = JobSearchInput(
        context_id="pagination-context",
        request_id="jobs-page-1",
        query="python",
        page_size=2,
    )

    first = await tools.search_jobs(first_request)
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
    second = await tools.search_jobs(second_request)
    assert tuple(job.job_id for job in second.jobs) == ("4100000003", "4100000004")
    assert second.pagination.scan_id == first.pagination.scan_id
    assert second.pagination.cumulative_count == 4
    assert second.pagination.next_cursor is not None

    with pytest.raises(InvalidCursorError, match="consumed"):
        await tools.search_jobs(
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
    third = await tools.search_jobs(third_request)
    assert tuple(job.job_id for job in third.jobs) == ("4100000005",)
    assert third.pagination.scan_id == first.pagination.scan_id
    assert third.pagination.cumulative_count == 5
    assert third.pagination.has_more is False
    assert third.pagination.next_cursor is None

    with pytest.raises(InvalidCursorError, match="consumed"):
        await tools.search_jobs(second_request)
    assert search.result_limits == [3, 5, 7]


@pytest.mark.asyncio
async def test_invitation_cursor_walks_live_prefix_without_duplicates() -> None:
    invitations = PaginatedFakeInvitationList()
    tools = _tools(
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

    first = await tools.list_invitations(first_request)
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
        await tools.list_invitations(
            first_request.model_copy(
                update={
                    "request_id": "invitation-filter-mismatch",
                    "cursor": first.pagination.next_cursor,
                    "invitation_filter": InvitationFilter.SAME_COMPANY,
                }
            )
        )
    with pytest.raises(InvalidCursorError, match="account, capability, or filter set"):
        await tools.list_invitations(
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
    second = await tools.list_invitations(second_request)
    assert [item.primary_entity.slug for item in second.invitations] == ["invitation-member-3"]
    assert second.pagination.scan_id == first.pagination.scan_id
    assert second.pagination.cumulative_count == 3
    assert second.pagination.next_cursor is not None

    with pytest.raises(InvalidCursorError, match="consumed"):
        await tools.list_invitations(
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
    third = await tools.list_invitations(third_request)
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

    with pytest.raises(InvalidCursorError, match="consumed"):
        await tools.list_invitations(second_request)
    assert invitations.calls == 3
    assert invitations.result_limits == [3, 4, 6]


@pytest.mark.asyncio
async def test_unadvertised_empty_invitation_view_survives_tools_evidence() -> None:
    invitations = ImplicitEmptyInvitationList()
    tools = _tools(
        FakeJobSearch(),
        FakeJobDetail(),
        invitation_list=invitations,
    )

    output = await tools.list_invitations(
        InvitationListInput(
            context_id="empty-sent-invitations",
            request_id="empty-sent-invitations-1",
            direction=InvitationDirection.SENT,
            page_size=10,
        )
    )

    assert output.invitations == ()
    assert output.coverage.advertised_count is None
    assert output.coverage.unadvertised_empty_views == (InvitationFilter.PEOPLE,)
    assert output.coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE
    assert output.pagination.has_more is False
    assert output.pagination.truncated is False
    assert len(output.sources) == 1


@pytest.mark.asyncio
async def test_job_detail_accepts_any_valid_job_id_without_prior_search() -> None:
    detail = FakeJobDetail()
    tools = _tools(FakeJobSearch(), detail)

    output = await tools.get_job(
        JobDetailInput(
            context_id="context-1",
            request_id="direct-detail",
            job_id="4100000001",
        )
    )

    assert output.job.job_id == "4100000001"
    assert str(output.sources[0].source_url).startswith("https://www.linkedin.com/jobs/view/")
    assert detail.calls == 1


@pytest.mark.asyncio
async def test_repeated_people_search_executes_provider_each_time() -> None:
    people_search = FakePeopleSearch()
    tools = _tools(
        FakeJobSearch(),
        FakeJobDetail(),
        people_search=people_search,
    )
    request = PeopleSearchInput(
        context_id="context-1",
        request_id="people-search-1",
        query='"distributed systems" AND Python staff engineer',
        page_size=10,
    )

    first = await tools.search_people(request)
    second = await tools.search_people(request)

    assert second.people == first.people
    assert first.people[0].profile_slug == "jane-doe"
    assert people_search.calls == 2


@pytest.mark.asyncio
async def test_repeated_connections_search_executes_provider_each_time() -> None:
    people_search = FakePeopleSearch()
    tools = _tools(
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

    first = await tools.search_connections(request)
    second = await tools.search_connections(request)

    assert second.people == first.people
    assert first.people[0].profile_slug == "jane-doe"
    assert first.coverage.filters.connection_degrees == (PeopleSearchConnectionDegree.FIRST,)
    assert people_search.calls == 2


@pytest.mark.asyncio
async def test_connections_search_rejects_non_first_degree_results() -> None:
    tools = _tools(
        FakeJobSearch(),
        FakeJobDetail(),
        people_search=FakeNonConnectionPeopleSearch(),
    )

    with pytest.raises(ParserDriftError, match="not visibly first-degree"):
        await tools.search_connections(
            ConnectionsSearchInput(
                context_id="connections-context",
                request_id="connections-search-degree-drift",
                query="Jane Doe",
            )
        )


@pytest.mark.asyncio
async def test_person_profile_returns_metadata_for_every_captured_page() -> None:
    person_profile = FakePersonProfile()
    tools = _tools(
        FakeJobSearch(),
        FakeJobDetail(),
        person_profile=person_profile,
    )

    output = await tools.get_person(
        PeopleGetInput(
            context_id="context-1",
            request_id="person-direct-1",
            profile_slug="jane-doe",
        )
    )

    assert output.person.profile_slug == "jane-doe"
    assert output.person.about == "Builds reliable systems."
    assert len(output.sources) == 2
    assert all(
        str(source.source_url).startswith("https://www.linkedin.com/in/")
        for source in output.sources
    )
    assert person_profile.calls == 1


@pytest.mark.asyncio
async def test_same_request_id_can_execute_with_different_profile_sections() -> None:
    person_profile = FakePersonProfile()
    tools = _tools(
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

    await tools.get_person(overview_request)
    await tools.get_person(
        overview_request.model_copy(update={"sections": (PersonProfileSectionSelector.SKILLS,)})
    )
    assert person_profile.calls == 2


@pytest.mark.asyncio
async def test_company_reads_execute_fresh_and_return_source_metadata() -> None:
    company_search = FakeCompanySearch()
    company_profile = FakeCompanyProfile()
    tools = _tools(
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

    search = await tools.search_companies(search_request)
    second_search = await tools.search_companies(search_request)
    profile_request = CompanyGetInput(
        context_id="company-context",
        request_id="company-get-1",
        company_slug="acme-cloud",
    )
    profile = await tools.get_company(profile_request)
    second_profile = await tools.get_company(profile_request)

    assert search.companies[0].company_slug == "acme-cloud"
    assert second_search.companies == search.companies
    assert company_search.calls == 2
    assert profile.company.company_size_range == "1,001-5,000 employees"
    assert str(profile.sources[0].source_url).startswith("https://www.linkedin.com/company/")
    assert second_profile.company.company_slug == profile.company.company_slug
    assert company_profile.calls == 2

    changed = await tools.get_company(
        profile_request.model_copy(update={"company_slug": "example-labs"})
    )
    assert changed.company.company_slug == "example-labs"
    assert company_profile.calls == 3


@pytest.mark.asyncio
async def test_post_discussion_reads_execute_fresh_with_exact_evidence() -> None:
    post_search = FakePostSearch()
    post_detail = FakePostDetail()
    post_comments = FakePostComments()
    tools = _tools(
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
    post_search_output = await tools.search_posts(search_request)
    post_detail_output = await tools.get_post(detail_request)
    comments_output = await tools.list_post_comments(comments_request)

    await tools.search_posts(search_request)
    await tools.get_post(detail_request)
    await tools.list_post_comments(comments_request)
    assert post_search_output.posts[0].post_ref == post_ref
    assert post_search_output.coverage.unsupported_result_count == 1
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
    assert (post_search.calls, post_detail.calls, post_comments.calls) == (2, 2, 2)


@pytest.mark.asyncio
async def test_connection_and_messaging_reads_execute_fresh() -> None:
    invitations = FakeInvitationList()
    tools = _tools(
        FakeJobSearch(),
        FakeJobDetail(),
        invitation_list=invitations,
    )

    invitation_request = InvitationListInput(
        context_id="connections-context",
        request_id="invitations-1",
        direction=InvitationDirection.RECEIVED,
    )
    first = await tools.list_invitations(invitation_request)
    second_invitations = await tools.list_invitations(invitation_request)
    connections_request = ConnectionsListInput(
        context_id="connections-context",
        request_id="connections-1",
    )
    connections = await tools.list_connections(connections_request)
    second_connections = await tools.list_connections(connections_request)
    inbox_request = ConversationSearchInput(
        context_id="messaging-context",
        request_id="inbox-1",
        filter=ConversationFilter.UNREAD,
    )
    inbox = await tools.search_messages(inbox_request)
    second_inbox = await tools.search_messages(inbox_request)
    conversation_request = ConversationGetInput(
        context_id="messaging-context",
        request_id="conversation-1",
        conversation_id="thread-123",
    )
    conversation = await tools.get_conversation(conversation_request)
    second_conversation = await tools.get_conversation(conversation_request)

    assert first.invitations[0].note == "Hi, let us connect."
    assert second_invitations.invitations[0].note == first.invitations[0].note
    assert invitations.calls == 2
    assert connections.connections[0].profile_slug == "jane-doe"
    assert second_connections.connections[0].profile_slug == "jane-doe"
    assert inbox.conversations[0].unread is True
    assert second_inbox.conversations[0].conversation_id == "thread-123"
    assert [message.direction for message in conversation.conversation.messages] == [
        MessageDirection.INCOMING,
        MessageDirection.OUTGOING,
    ]
    assert [message.direction for message in second_conversation.conversation.messages] == [
        MessageDirection.INCOMING,
        MessageDirection.OUTGOING,
    ]
    assert all(
        str(source.source_url).startswith("https://www.linkedin.com/")
        for output in (first, connections, inbox, conversation)
        for source in output.sources
    )


@pytest.mark.asyncio
async def test_all_seven_actions_run_directly_with_typed_evidence() -> None:
    actions = FakeInvitationActions()
    publishing = FakePostPublishing()
    engagement = FakePostEngagement()
    messaging = FakeConversation()
    tools = _tools(
        FakeJobSearch(),
        FakeJobDetail(),
        invitation_actions=actions,
        post_publishing=publishing,
        post_engagement=engagement,
        conversation=messaging,
    )
    post_ref = "activity:7312345678901234567"

    outputs = (
        await tools.create_post(
            PostCreateInput(
                context_id="actions",
                request_id="post",
                content=TextPostContent(text="An atomic post."),
            )
        ),
        await tools.comment_on_post(
            PostCommentInput(
                context_id="actions",
                request_id="comment",
                post_ref=post_ref,
                text="Thanks",
            )
        ),
        await tools.react_to_post(
            PostReactionInput(
                context_id="actions",
                request_id="reaction",
                post_ref=post_ref,
                desired_reaction=ReactionState.LIKE,
            )
        ),
        await tools.send_invitation(
            InvitationSendInput(
                context_id="actions",
                request_id="invite",
                profile_slug="jane-doe",
                note="Hello",
            )
        ),
        await tools.accept_invitation(
            InvitationAcceptInput(
                context_id="actions",
                request_id="accept",
                profile_slug="jane-doe",
            )
        ),
        await tools.ignore_invitation(
            InvitationIgnoreInput(
                context_id="actions",
                request_id="ignore",
                profile_slug="jane-doe",
            )
        ),
        await tools.send_message(
            MessageSendInput(
                context_id="actions",
                request_id="message",
                conversation_id="thread-123",
                message="Hello",
            )
        ),
    )

    assert [output.result.outcome for output in outputs] == [ActionOutcome.VERIFIED] * 7
    assert [output.result.performed for output in outputs] == [True] * 7
    assert all(
        output.sources[0].source_type.value == "linkedin_action_execution" for output in outputs
    )
    assert publishing.post_actions == 1
    assert engagement.comment_actions == 1
    assert engagement.reaction_actions == 1
    assert (actions.invite_actions, actions.accept_actions, actions.ignore_actions) == (
        1,
        1,
        1,
    )
    assert messaging.message_actions == 1


@pytest.mark.asyncio
async def test_repeated_write_request_executes_a_new_action() -> None:
    actions = FakeInvitationActions()
    tools = _tools(
        FakeJobSearch(),
        FakeJobDetail(),
        invitation_actions=actions,
    )
    request = InvitationSendInput(
        context_id="repeat-action",
        request_id="same-request-id",
        profile_slug="jane-doe",
    )

    first = await tools.send_invitation(request)
    second = await tools.send_invitation(request)

    assert actions.invite_actions == 2
    assert first.sources != second.sources
    assert first.result.final_state == second.result.final_state == "pending_sent"


@pytest.mark.asyncio
async def test_incoming_invitation_action_requires_exact_visible_reference() -> None:
    tools = _tools(
        FakeJobSearch(),
        FakeJobDetail(),
        invitation_actions=MissingReferenceActions(),
    )

    with pytest.raises(RuntimeError, match="invitation reference"):
        await tools.accept_invitation(
            InvitationAcceptInput(
                context_id="missing-reference",
                request_id="accept",
                profile_slug="jane-doe",
            )
        )


@pytest.mark.parametrize("cancelled", [False, True], ids=["uncertain", "cancelled"])
@pytest.mark.asyncio
async def test_interrupted_action_is_uncertain_but_cancellation_propagates(
    cancelled: bool,
) -> None:
    tools = _tools(
        FakeJobSearch(),
        FakeJobDetail(),
        invitation_actions=InterruptedInvitationActions(cancelled=cancelled),
    )
    request = InvitationSendInput(
        context_id="interrupted-action",
        request_id="invite",
        profile_slug="jane-doe",
    )

    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            await tools.send_invitation(request)
    else:
        output = await tools.send_invitation(request)
        assert output.result.outcome is ActionOutcome.UNCERTAIN
        assert output.result.performed is None
        assert output.result.final_state == "unknown_after_interruption"
        assert output.sources == ()


@pytest.mark.asyncio
async def test_known_precondition_error_is_not_misreported_as_uncertain() -> None:
    tools = _tools(
        FakeJobSearch(),
        FakeJobDetail(),
        invitation_actions=RejectedInvitationActions(),
    )

    with pytest.raises(InvalidTargetError, match="no longer available"):
        await tools.send_invitation(
            InvitationSendInput(
                context_id="rejected-action",
                request_id="invite",
                profile_slug="jane-doe",
            )
        )


def test_safe_capability_error_preserves_known_errors_and_hides_unknown_details() -> None:
    known = InvalidTargetError("Safe target error.")
    assert safe_capability_error(known) is known
    projected = safe_capability_error(RuntimeError("secret"))
    assert isinstance(projected, InternalServerError)
    assert "secret" not in projected.safe_message
