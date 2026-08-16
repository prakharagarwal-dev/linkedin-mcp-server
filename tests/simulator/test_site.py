from __future__ import annotations

from typing import cast

import pytest

import linkedin_mcp.linkedin.companies.pages as company_pages
import linkedin_mcp.linkedin.jobs.pages as job_pages
import linkedin_mcp.linkedin.messaging.pages as messaging_pages
import linkedin_mcp.linkedin.network.connections as connection_pages
import linkedin_mcp.linkedin.network.invitations as invitation_pages
import linkedin_mcp.linkedin.people.pages as people_pages
import linkedin_mcp.linkedin.posts.pages as post_pages
from linkedin_mcp.errors import AuthenticationRequiredError, BrowserUnavailableError
from linkedin_mcp.linkedin.browser import BrowserManager
from linkedin_mcp.linkedin.companies.pages import CompanyProfilePage, CompanySearchPage
from linkedin_mcp.linkedin.jobs.pages import JobDetailPage, JobSearchPage
from linkedin_mcp.linkedin.messaging.pages import ConversationPage, ConversationSearchPage
from linkedin_mcp.linkedin.models import (
    CompanyGetInput,
    CompanySearchInput,
    ConnectionsListInput,
    ConversationGetInput,
    ConversationSearchInput,
    InvitationDirection,
    InvitationFilter,
    InvitationListInput,
    JobDetailInput,
    JobSearchInput,
    PeopleGetInput,
    PeopleSearchInput,
    PersonProfileSectionSelector,
    PostCommentsListInput,
    PostGetInput,
    PostSearchInput,
    StopReason,
)
from linkedin_mcp.linkedin.network.connections import ConnectionsListPage
from linkedin_mcp.linkedin.network.invitations import InvitationListPage
from linkedin_mcp.linkedin.people.pages import PeopleSearchPage, PersonProfilePage
from linkedin_mcp.linkedin.posts.pages import PostCommentsPage, PostDetailPage, PostSearchPage
from tests.simulator import SimulatorBrowser, standard_scenario
from tests.simulator.state import SimulatorFault


@pytest.fixture(autouse=True)
def _use_fast_synthetic_collection_clock(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # These routes are deterministic local HTML. Keep every production polling
    # round while avoiding real-site delays that cannot reveal new fixture state.
    monkeypatch.setattr(company_pages, "_INITIAL_RESULTS_POLL_DELAY_MS", 25)
    monkeypatch.setattr(connection_pages, "_SCROLL_PROGRESS_POLL_DELAY_MS", 25)
    monkeypatch.setattr(invitation_pages, "_INVENTORY_DELAY_MS", 25)
    monkeypatch.setattr(invitation_pages, "_SETTLE_DELAY_MS", 25)
    monkeypatch.setattr(job_pages, "_SEARCH_SETTLE_DELAY_MS", 25)
    monkeypatch.setattr(messaging_pages, "_SCROLL_PROGRESS_POLL_DELAY_MS", 25)
    monkeypatch.setattr(people_pages, "_INITIAL_RESULTS_POLL_DELAY_MS", 25)
    monkeypatch.setattr(post_pages, "_COLLECTION_POLL_DELAY_MS", 25)


@pytest.mark.timeout(60)
async def test_semantic_site_drives_real_read_page_objects_across_domains() -> None:
    scenario = standard_scenario()
    browser = SimulatorBrowser(scenario)
    await browser.start()
    page_browser = cast(BrowserManager, browser)
    try:
        jobs, _, _, _ = await JobSearchPage(page_browser, max_pages=1).collect(
            JobSearchInput(
                context_id="simulator",
                request_id="jobs-search",
                query="python",
                page_size=1,
            )
        )
        job = await JobDetailPage(page_browser).read(
            JobDetailInput(
                context_id="simulator",
                request_id="job-get",
                job_id=jobs[0].job_id,
            )
        )

        people, _, _, _ = await PeopleSearchPage(page_browser, max_pages=1).collect(
            PeopleSearchInput(
                context_id="simulator",
                request_id="people-search",
                query="engineer",
                page_size=1,
            )
        )
        person, _ = await PersonProfilePage(page_browser, max_detail_pages=3).read(
            PeopleGetInput(
                context_id="simulator",
                request_id="people-get",
                profile_slug=people[0].profile_slug,
                sections=(PersonProfileSectionSelector.OVERVIEW,),
            )
        )

        companies, _, _, _ = await CompanySearchPage(page_browser, max_pages=1).collect(
            CompanySearchInput(
                context_id="simulator",
                request_id="companies-search",
                query="cloud",
                page_size=1,
            )
        )
        company, company_captures = await CompanyProfilePage(page_browser).read(
            CompanyGetInput(
                context_id="simulator",
                request_id="companies-get",
                company_slug=companies[0].company_slug,
            )
        )

        posts, _, _, _ = await PostSearchPage(page_browser, max_pages=1).collect(
            PostSearchInput(
                context_id="simulator",
                request_id="posts-search",
                query="python",
                page_size=1,
            )
        )
        post = await PostDetailPage(page_browser).read(
            PostGetInput(
                context_id="simulator",
                request_id="posts-get",
                post_ref=posts[0].post_ref,
            )
        )
    finally:
        await browser.close()

    assert job.description_text is not None and "Python" in job.description_text
    assert person.name == "Jane Doe"
    assert company.name == "Acme Cloud"
    assert tuple(capture.page_kind for capture in company_captures) == ("overview", "about")
    assert post.post_ref == "activity:7312345678901234567"
    assert len(browser.navigations) >= 8
    assert any("/jobs/search/" in url for url in browser.navigations)
    assert any("/search/results/people/" in url for url in browser.navigations)
    assert any("/search/results/companies/" in url for url in browser.navigations)
    assert any("/search/results/content/" in url for url in browser.navigations)


async def test_simulator_routes_variants_without_changing_production_code() -> None:
    scenario = standard_scenario()
    scenario.use_fixture("messaging", "messaging/latest/current.html")
    browser = SimulatorBrowser(scenario)
    await browser.start()
    try:
        async with browser.page() as page:
            await browser.navigate(page, "https://www.linkedin.com/messaging/")
            assert await page.locator("#jane-card").count() == 1
    finally:
        await browser.close()

    assert scenario.provenance.source == "synthetic"
    assert scenario.provenance.recorded_at is None


@pytest.mark.timeout(60)
async def test_semantic_site_drives_network_discussion_and_company_feed_reads() -> None:
    scenario = standard_scenario()
    browser = SimulatorBrowser(scenario)
    await browser.start()
    page_browser = cast(BrowserManager, browser)
    try:
        invitations, invitation_coverage, invitation_text, _ = await InvitationListPage(
            page_browser,
            max_scroll_rounds=13,
        ).collect(
            InvitationListInput(
                context_id="simulator",
                request_id="invitations",
                page_size=10,
            )
        )
        sent_invitations, sent_coverage, _, _ = await InvitationListPage(
            page_browser,
            max_scroll_rounds=5,
        ).collect(
            InvitationListInput(
                context_id="simulator",
                request_id="sent-invitations",
                direction=InvitationDirection.SENT,
                page_size=10,
            )
        )
        filtered_invitations: dict[InvitationFilter, tuple[str, ...]] = {}
        for invitation_filter in (
            InvitationFilter.VERIFIED,
            InvitationFilter.MUTUAL_CONNECTIONS,
            InvitationFilter.SAME_COMPANY,
            InvitationFilter.SAME_SCHOOL,
        ):
            filtered, filtered_coverage, _, _ = await InvitationListPage(
                page_browser,
                max_scroll_rounds=2,
            ).collect(
                InvitationListInput(
                    context_id="simulator",
                    request_id=f"invitations-{invitation_filter.value}",
                    invitation_filter=invitation_filter,
                    page_size=10,
                )
            )
            assert filtered_coverage.unique_count == filtered_coverage.advertised_count == 1
            filtered_invitations[invitation_filter] = tuple(
                item.primary_entity.slug or item.primary_entity.display_name for item in filtered
            )
        connections, connection_coverage, connection_text, _ = await ConnectionsListPage(
            page_browser,
            max_scroll_rounds=8,
        ).collect(
            ConnectionsListInput(
                context_id="simulator",
                request_id="connections",
                page_size=10,
            )
        )
        conversations, _, _, _ = await ConversationSearchPage(
            page_browser,
            max_scroll_rounds=1,
        ).collect(
            ConversationSearchInput(
                context_id="simulator",
                request_id="conversations",
                query="Jane",
                page_size=1,
            )
        )
        conversation = await ConversationPage(page_browser).read(
            ConversationGetInput(
                context_id="simulator",
                request_id="conversation",
                conversation_id="thread-123",
                max_messages=5,
            )
        )
        threads, _, _, _ = await PostCommentsPage(
            page_browser,
            max_expansion_rounds=1,
        ).collect(
            PostCommentsListInput(
                context_id="simulator",
                request_id="comments",
                post_ref="activity:7312345678901234567",
                page_size=1,
            )
        )
    finally:
        await browser.close()

    assert [item.primary_entity.slug for item in invitations] == [
        "alex-member-",
        "example-systems",
        "example-institute",
        "12345",
        "platform-meetup-748",
        "engineering-weekly-123",
        None,
        "filter-member-",
    ]
    assert invitation_coverage.advertised_count is None
    assert invitation_coverage.unique_count == 8
    assert invitation_coverage.view_counts == {
        InvitationFilter.FOCUSED: 4,
        InvitationFilter.OTHER: 3,
        InvitationFilter.VERIFIED: 1,
        InvitationFilter.MUTUAL_CONNECTIONS: 1,
        InvitationFilter.SAME_COMPANY: 1,
        InvitationFilter.SAME_SCHOOL: 1,
    }
    assert invitation_coverage.view_membership_count == 11
    assert invitation_coverage.overlap_count == 3
    assert invitation_coverage.scroll_rounds == 0
    assert invitation_coverage.neighboring_recommendation_count == 1
    assert invitation_coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE
    assert "Focused (4)" in invitation_text
    assert "Other (3)" in invitation_text
    assert [item.primary_entity.slug for item in sent_invitations] == [
        "jordan-sent-",
        "morgan-sent",
    ]
    assert sent_coverage.advertised_count == sent_coverage.unique_count == 2
    assert sent_coverage.invitation_filter is InvitationFilter.PEOPLE
    assert sent_coverage.view_counts == {InvitationFilter.PEOPLE: 2}
    assert filtered_invitations == {
        InvitationFilter.VERIFIED: ("filter-member-",),
        InvitationFilter.MUTUAL_CONNECTIONS: ("filter-member-",),
        InvitationFilter.SAME_COMPANY: ("filter-member-",),
        InvitationFilter.SAME_SCHOOL: ("filter-member-",),
    }
    assert [item.profile_slug for item in connections] == [
        "jordan-ng-",
        "alex-rivera",
        "casey-lee",
    ]
    assert connection_coverage.rounds_visited == 3
    assert connection_coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE
    assert "3 connections" in connection_text
    assert conversations[0].participant_name == "Jane Doe"
    assert conversation.messages[0].text == "Can we discuss the role?"
    assert threads[0].comment.author.name == "Alex Ray"


async def test_simulator_faults_are_typed_ordered_and_one_shot() -> None:
    scenario = standard_scenario()
    scenario.state.queue_fault("jobs.get", SimulatorFault.NAVIGATION_TIMEOUT)
    scenario.state.queue_fault("jobs.get", SimulatorFault.AUTHENTICATION_EXPIRED)
    browser = SimulatorBrowser(scenario)
    await browser.start()
    try:
        async with browser.page() as page:
            with pytest.raises(BrowserUnavailableError, match="timed out"):
                await browser.navigate(
                    page,
                    "https://www.linkedin.com/jobs/view/4100000001/",
                )
            with pytest.raises(AuthenticationRequiredError, match="expired"):
                await browser.navigate(
                    page,
                    "https://www.linkedin.com/jobs/view/4100000001/",
                )
    finally:
        await browser.close()

    assert scenario.state.authenticated is False
    assert scenario.state.take_fault("jobs.get") is None
