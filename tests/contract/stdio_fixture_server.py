"""Minimal production-shaped server used to verify the real stdio transport."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from pydantic import HttpUrl

from linkedin_mcp.application import (
    AccountProcessLock,
    CapabilityExecutor,
    CapabilityWorker,
    CompanyProfileProvider,
    CompanySearchProvider,
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
from linkedin_mcp.domain.models import (
    EvidenceField,
    JobDetailInput,
    JobDetailObservation,
    JobSearchCoverage,
    JobSearchInput,
    JobSummary,
    PeopleGetInput,
    PeopleSearchCoverage,
    PeopleSearchInput,
    PersonProfileCoverage,
    PersonProfileObservation,
    PersonProfilePageCapture,
    PersonSummary,
    StopReason,
)
from linkedin_mcp.persistence import MemoryRepository
from linkedin_mcp.server import create_mcp_server


class UnusedJobSearch:
    async def collect(
        self,
        request: JobSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[JobSummary, ...], JobSearchCoverage, str, str]:
        del result_limit
        return (
            (),
            JobSearchCoverage(
                query=request.query,
                location=request.location,
                freshness_hours=request.freshness_hours,
                filters=request.filters,
                pages_visited=1,
                result_count=0,
                max_results=request.max_results,
                stop_reason=StopReason.NO_NEW_RESULTS,
                captured_at=datetime.now(UTC),
            ),
            "No visible jobs",
            "https://www.linkedin.com/jobs/search/",
        )


class UnusedJobDetail:
    async def read(self, request: JobDetailInput) -> JobDetailObservation:
        return JobDetailObservation(
            job_id=request.job_id,
            job_url=HttpUrl(f"https://www.linkedin.com/jobs/view/{request.job_id}/"),
            title="Unused fixture",
            visible_text="Unused fixture",
            evidence=(EvidenceField(field="title", quote="Unused fixture"),),
            captured_at=datetime.now(UTC),
        )


class UnusedPeopleSearch:
    async def collect(
        self,
        request: PeopleSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[PersonSummary, ...], PeopleSearchCoverage, str, str]:
        del result_limit
        return (
            (),
            PeopleSearchCoverage(
                query=request.query,
                title_keywords=request.title_keywords,
                filters=request.filters,
                pages_visited=1,
                result_count=0,
                max_results=request.max_results,
                stop_reason=StopReason.NO_NEW_RESULTS,
                captured_at=datetime.now(UTC),
            ),
            "No visible people",
            "https://www.linkedin.com/search/results/people/",
        )


class UnusedPersonProfile:
    async def read(
        self, request: PeopleGetInput
    ) -> tuple[PersonProfileObservation, tuple[PersonProfilePageCapture, ...]]:
        captured_at = datetime.now(UTC)
        profile_url = HttpUrl(f"https://www.linkedin.com/in/{request.profile_slug}/")
        captured_text = "Unused fixture"
        return (
            PersonProfileObservation(
                profile_slug=request.profile_slug,
                profile_url=profile_url,
                name="Unused fixture",
                visible_text=captured_text,
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
            (
                PersonProfilePageCapture(
                    source_url=profile_url,
                    page_kind="profile",
                    captured_text=captured_text,
                    captured_at=captured_at,
                ),
            ),
        )


def main() -> None:
    settings = Settings(
        auto_login_on_start=False,
        browser_auto_install=False,
        runtime_lock_path=Path(".linkedin-mcp/stdio-fixture-runtime.lock"),
    )
    repository = MemoryRepository()
    registry = create_default_registry()
    browser = BrowserManager(settings)
    unused_extension = object()
    executor = CapabilityExecutor(
        settings=settings,
        registry=registry,
        repository=repository,
        job_search=UnusedJobSearch(),
        job_detail=UnusedJobDetail(),
        people_search=UnusedPeopleSearch(),
        person_profile=UnusedPersonProfile(),
        company_search=cast(CompanySearchProvider, unused_extension),
        company_profile=cast(CompanyProfileProvider, unused_extension),
        post_search=cast(PostSearchProvider, unused_extension),
        post_detail=cast(PostDetailProvider, unused_extension),
        post_comments=cast(PostCommentsProvider, unused_extension),
        post_publishing=cast(PostPublishingProvider, unused_extension),
        post_engagement=cast(PostEngagementProvider, unused_extension),
        invitation_list=cast(InvitationListProvider, unused_extension),
        connections_list=cast(ConnectionsListProvider, unused_extension),
        invitation_actions=cast(InvitationActionProvider, unused_extension),
        conversation_search=cast(ConversationSearchProvider, unused_extension),
        conversation=cast(ConversationProvider, unused_extension),
    )
    worker = CapabilityWorker(executor, queue_capacity=settings.queue_capacity)
    container = AppContainer(
        settings=settings,
        registry=registry,
        repository=repository,
        browser=browser,
        executor=executor,
        worker=worker,
        process_lock=AccountProcessLock(settings.runtime_lock_path),
    )
    create_mcp_server(container).run(transport="stdio")


if __name__ == "__main__":
    main()
