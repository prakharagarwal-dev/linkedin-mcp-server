from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.async_api import Locator, Page, async_playwright
from pydantic import ValidationError

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools._shared.browser import BrowserManager
from linkedin_mcp.tools._shared.models import StopReason
from linkedin_mcp.tools.connections.search.models import (
    ConnectionsSearchFilters,
    ConnectionsSearchInput,
    PersonConnectionDegree,
)
from linkedin_mcp.tools.people.get.models.people_get_input import PeopleGetInput
from linkedin_mcp.tools.people.get.models.person_profile_section_selector import (
    PersonProfileSectionSelector,
)
from linkedin_mcp.tools.people.get.page import PersonProfilePage
from linkedin_mcp.tools.people.search.models.people_search_connection_degree import (
    PeopleSearchConnectionDegree,
)
from linkedin_mcp.tools.people.search.models.people_search_filters import PeopleSearchFilters
from linkedin_mcp.tools.people.search.models.people_search_input import PeopleSearchInput
from linkedin_mcp.tools.people.search.page import PeopleSearchPage

FIXTURES = Path(__file__).parents[1] / "fixtures" / "linkedin"


class PeopleFixtureBrowser:
    def __init__(self, page: Page, *, search_html: str | None = None) -> None:
        self._page = page
        self._search_html = search_html
        self.navigations: list[str] = []

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        yield self._page

    async def navigate(self, page: Page, url: str) -> None:
        self.navigations.append(url)
        path = urlsplit(url).path
        if path.startswith("/search/results/people"):
            if self._search_html is not None:
                await page.set_content(self._search_html)
                return
            await page.set_content(
                (FIXTURES / "people" / "latest" / "search.html").read_text(encoding="utf-8")
            )
            await page.evaluate(
                "(target) => window.initializePeopleSearchFixture(target)",
                url,
            )
            return
        elif path.endswith("/details/experience/"):
            fixture = "experience.html"
        elif path.endswith("/details/education/"):
            fixture = "education.html"
        elif path.endswith("/details/skills/"):
            fixture = "skills.html"
        else:
            fixture = "overview-complete.html"
        await page.set_content(
            (FIXTURES / "people" / "latest" / fixture).read_text(encoding="utf-8")
        )


class StaticProfileBrowser:
    def __init__(self, page: Page, html: str) -> None:
        self._page = page
        self._html = html

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        yield self._page

    async def navigate(self, page: Page, url: str) -> None:
        del url
        await page.set_content(self._html)


class CurrentPeopleSearchFixtureBrowser:
    def __init__(
        self,
        page: Page,
        *,
        submitted_url: str | None = None,
        submitted_urls: tuple[str, ...] = (),
    ) -> None:
        self._page = page
        self._submitted_url = submitted_url
        self._submitted_urls = list(submitted_urls)
        self.navigations: list[str] = []
        self.visible_control_navigations: list[str] = []

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        yield self._page

    async def navigate(self, page: Page, url: str) -> None:
        self.navigations.append(url)
        await page.set_content(
            (FIXTURES / "people" / "latest" / "search.html").read_text(encoding="utf-8")
        )
        await page.evaluate(
            "(target) => window.initializePeopleSearchFixture(target)",
            url,
        )

    async def navigate_via_visible_control(self, page: Page, control: Locator) -> str:
        del page
        target = await control.get_attribute("href")
        assert target is not None
        target = (
            self._submitted_urls.pop(0) if self._submitted_urls else self._submitted_url or target
        )
        self.visible_control_navigations.append(target)
        return target


class CurrentProfileFixtureBrowser:
    def __init__(self, page: Page) -> None:
        self._page = page
        self.navigations: list[str] = []

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        yield self._page

    async def navigate(self, page: Page, url: str) -> None:
        self.navigations.append(url)
        path = urlsplit(url).path
        if path.endswith("/details/experience/"):
            fixture = "experience.html"
        elif path.endswith("/details/education/"):
            fixture = "education.html"
        else:
            fixture = "overview.html"
        await page.set_content(
            (FIXTURES / "people" / "latest" / fixture).read_text(encoding="utf-8")
        )


class SelfProfileFixtureBrowser:
    def __init__(self, page: Page) -> None:
        self._page = page
        self.navigations: list[str] = []

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        yield self._page

    async def navigate(self, page: Page, url: str) -> None:
        self.navigations.append(url)
        await page.set_content(
            (FIXTURES / "people/latest/self-overview.html").read_text(encoding="utf-8")
        )


class CurrentRolelessDetailFixtureBrowser:
    def __init__(self, page: Page) -> None:
        self._page = page
        self.navigations: list[str] = []

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        yield self._page

    async def navigate(self, page: Page, url: str) -> None:
        self.navigations.append(url)
        fixture = (
            "honors.html"
            if urlsplit(url).path.endswith("/details/honors/")
            else "roleless-overview.html"
        )
        await page.set_content(
            (FIXTURES / "people" / "latest" / fixture).read_text(encoding="utf-8")
        )


class CurrentPeoplePaginationFixtureBrowser:
    def __init__(self, page: Page) -> None:
        self._page = page
        self.navigations: list[str] = []

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        yield self._page

    async def navigate(self, page: Page, url: str) -> None:
        self.navigations.append(url)
        page_number = parse_qs(urlsplit(url).query).get("page", ["1"])[0]
        fixture = "search-unidentifiable.html" if page_number == "2" else "search.html"
        await page.set_content(
            (FIXTURES / "people" / "latest" / fixture).read_text(encoding="utf-8")
        )
        if fixture == "search.html":
            await page.evaluate(
                "(target) => window.initializePeopleSearchFixture(target)",
                url,
            )


def _decoded_values(query: dict[str, list[str]], key: str) -> list[str]:
    return cast(list[str], json.loads(query[key][0]))


def test_people_fixture_manifest_locks_every_current_visible_filter() -> None:
    manifest = cast(
        dict[str, object],
        json.loads((FIXTURES / "people/latest/manifest.json").read_text(encoding="utf-8")),
    )

    assert manifest["provenance"] == "mock_verified"
    assert manifest["verified_at"] == "2026-08-05"
    assert manifest["contains_live_data"] is False
    assert manifest["filter_sections"] == [
        "Connections",
        "Actively hiring",
        "Locations",
        "Current companies",
        "Connections of",
        "Followers of",
        "Past companies",
        "Schools",
        "Industries",
        "Profile Languages",
        "Service categories",
        "Keywords",
    ]
    assert manifest["connection_choices"] == ["1st", "2nd", "3rd+"]
    assert manifest["keyword_fields"] == [
        "First name",
        "Last name",
        "Title",
        "Company",
        "School",
    ]


def test_people_get_section_selection_is_strict_and_defaults_to_all() -> None:
    request = PeopleGetInput(
        context_id="context-1",
        request_id="profile-default-sections",
        profile_slug="jane-doe",
    )

    assert request.sections == (PersonProfileSectionSelector.ALL,)
    assert (
        PeopleGetInput(
            context_id="context-1",
            request_id="profile-trailing-hyphen",
            profile_slug="riley-quinn--",
        ).profile_slug
        == "riley-quinn--"
    )

    with pytest.raises(ValidationError, match="must not contain duplicates"):
        PeopleGetInput(
            context_id="context-1",
            request_id="profile-duplicate-sections",
            profile_slug="jane-doe",
            sections=(
                PersonProfileSectionSelector.SKILLS,
                PersonProfileSectionSelector.SKILLS,
            ),
        )

    with pytest.raises(ValidationError, match="'all' cannot be combined"):
        PeopleGetInput(
            context_id="context-1",
            request_id="profile-all-and-skills",
            profile_slug="jane-doe",
            sections=(
                PersonProfileSectionSelector.ALL,
                PersonProfileSectionSelector.SKILLS,
            ),
        )


def test_people_search_url_encodes_every_exact_filter_category() -> None:
    request = PeopleSearchInput(
        context_id="context-1",
        request_id="people-all-filters",
        query="distributed systems staff software engineer",
        filters=PeopleSearchFilters(
            connection_degrees=tuple(PeopleSearchConnectionDegree),
            actively_hiring_job_title_ids=("101",),
            location_ids=("102713980",),
            current_company_ids=("11130470",),
            connections_of_ids=("ACoAlex",),
            followers_of_ids=("ACoPriya",),
            past_company_ids=("1035",),
            school_ids=("17939",),
            industry_ids=("4",),
            profile_language_ids=("en",),
            service_category_ids=("123",),
            first_name="Jordan",
            last_name="Result",
            title="Staff Engineer",
            company="Example Cloud",
            school="Fixture University",
        ),
        page_size=50,
    )

    query = parse_qs(urlsplit(PeopleSearchPage.build_url(request, page_index=1)).query)

    assert query["origin"] == ["FACETED_SEARCH"]
    assert query["keywords"] == ["distributed systems staff software engineer"]
    assert query["page"] == ["2"]
    assert _decoded_values(query, "network") == ["F", "S", "O"]
    assert _decoded_values(query, "activelyHiringForJobTitles") == ["101"]
    assert _decoded_values(query, "geoUrn") == ["102713980"]
    assert _decoded_values(query, "currentCompany") == ["11130470"]
    assert _decoded_values(query, "connectionOf") == ["ACoAlex"]
    assert _decoded_values(query, "followerOf") == ["ACoPriya"]
    assert _decoded_values(query, "pastCompany") == ["1035"]
    assert _decoded_values(query, "schoolFilter") == ["17939"]
    assert _decoded_values(query, "industry") == ["4"]
    assert _decoded_values(query, "profileLanguage") == ["en"]
    assert _decoded_values(query, "serviceCategory") == ["123"]
    assert query["firstName"] == ["Jordan"]
    assert query["lastName"] == ["Result"]
    assert query["title"] == ["Staff Engineer"]
    assert query["company"] == ["Example Cloud"]
    assert query["schoolFreetext"] == ["Fixture University"]


def test_connections_search_contract_forces_first_degree_and_hides_degree_input() -> None:
    request = ConnectionsSearchInput(
        context_id="context-1",
        request_id="connections-first-degree",
        query="distributed systems",
        filters=ConnectionsSearchFilters(
            title="Staff Engineer",
            current_company_ids=("11130470",),
        ),
    )

    people_request = request.as_people_search_input()
    query = parse_qs(urlsplit(PeopleSearchPage.build_url(people_request)).query)

    assert people_request.filters.connection_degrees == (PeopleSearchConnectionDegree.FIRST,)
    assert _decoded_values(query, "network") == ["F"]
    assert query["title"] == ["Staff Engineer"]
    assert _decoded_values(query, "currentCompany") == ["11130470"]
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ConnectionsSearchFilters.model_validate({"connection_degrees": ["second"]})


def test_people_search_contract_rejects_duplicates_bounds_and_unscoped_searches() -> None:
    with pytest.raises(ValidationError, match="requires query"):
        PeopleSearchInput(
            context_id="context-1",
            request_id="empty-search",
        )

    with pytest.raises(ValidationError, match="current_company_names cannot contain duplicate"):
        PeopleSearchFilters(current_company_names=("OpenAI", " openai "))

    with pytest.raises(ValidationError, match="at most ten combined"):
        PeopleSearchFilters(
            school_ids=tuple(str(index) for index in range(5)),
            school_names=tuple(f"School {index}" for index in range(6)),
        )

    with pytest.raises(ValidationError, match="cannot be combined"):
        PeopleSearchFilters(
            actively_hiring=True,
            actively_hiring_job_title_ids=("101",),
        )


@pytest.mark.timeout(30)
async def test_people_search_resolves_all_visible_named_and_toggle_filters() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = CurrentPeopleSearchFixtureBrowser(page)
        collector = PeopleSearchPage(cast(BrowserManager, fixture_browser), max_pages=2)
        request = PeopleSearchInput(
            context_id="context-1",
            request_id="named-people-search",
            query="AI leaders staff engineer",
            filters=PeopleSearchFilters(
                connection_degrees=(
                    PeopleSearchConnectionDegree.SECOND,
                    PeopleSearchConnectionDegree.THIRD_OR_MORE,
                ),
                actively_hiring_job_title_names=("Fixture Engineer",),
                location_names=("Fixture City",),
                current_company_names=("Fixture Current Company",),
                connections_of_names=("Fixture Connector",),
                followers_of_names=("Fixture Creator",),
                past_company_names=("Fixture Past Company",),
                school_names=("Fixture University",),
                industry_names=("Fixture Industry",),
                profile_language_names=("English",),
                service_category_names=("Fixture Service",),
                first_name="Jordan",
                last_name="Result",
                title="Staff Engineer",
                company="Example Cloud",
                school="Fixture University",
            ),
            page_size=1,
        )
        try:
            people, coverage, captured_text, first_url = await collector.collect(request)
        finally:
            await browser.close()

    assert len(people) == 1
    assert people[0].profile_slug == "jordan-result-"
    assert people[0].name == "Jordan Result"
    assert people[0].headline == "Staff Software Engineer at Example Cloud"
    assert people[0].location == "Bengaluru, Karnataka, India"
    assert people[0].connection_degree is PersonConnectionDegree.SECOND
    assert people[0].mutual_connections_text is not None
    assert "Jordan Result" in captured_text
    assert coverage.filters == request.filters
    assert coverage.pages_visited == 1
    assert coverage.stop_reason is StopReason.RESULT_LIMIT
    assert len(fixture_browser.navigations) == 2
    assert first_url == fixture_browser.navigations[1]

    query = parse_qs(urlsplit(first_url).query)
    assert _decoded_values(query, "network") == ["S", "O"]
    assert _decoded_values(query, "activelyHiringForJobTitles") == ["101"]
    assert _decoded_values(query, "geoUrn") == ["102713980"]
    assert _decoded_values(query, "currentCompany") == ["11130470"]
    assert _decoded_values(query, "connectionOf") == ["ACoFixtureConnector"]
    assert _decoded_values(query, "followerOf") == ["ACoFixtureCreator"]
    assert _decoded_values(query, "pastCompany") == ["1035"]
    assert _decoded_values(query, "schoolFilter") == ["17939"]
    assert _decoded_values(query, "industry") == ["4"]
    assert _decoded_values(query, "profileLanguage") == ["en"]
    assert _decoded_values(query, "serviceCategory") == ["123"]
    assert query["firstName"] == ["Jordan"]
    assert query["lastName"] == ["Result"]
    assert query["title"] == ["Staff Engineer"]
    assert query["company"] == ["Example Cloud"]
    assert query["schoolFreetext"] == ["Fixture University"]


@pytest.mark.timeout(20)
async def test_people_search_waits_for_async_trailing_hyphen_result() -> None:
    html = """
    <!doctype html>
    <html><body><main>
      <h1>People results</h1>
      <ul id="results"></ul>
      <template id="late-result">
        <li role="listitem">
          <a href="/in/late-person-/">Late Person</a>
          <p>2nd degree connection</p>
          <p>Principal Engineer at Example Systems</p>
          <p>Hyderabad, India</p>
          <button type="button">Message</button>
        </li>
      </template>
    </main>
    <script>
      setTimeout(() => {
        document.querySelector("#results").append(
          document.querySelector("#late-result").content.cloneNode(true)
        );
      }, 600);
    </script></body></html>
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        collector = PeopleSearchPage(
            cast(
                BrowserManager,
                PeopleFixtureBrowser(page, search_html=html),
            ),
            max_pages=1,
        )
        try:
            people, coverage, _, _ = await collector.collect(
                PeopleSearchInput(
                    context_id="context-1",
                    request_id="async-people-results",
                    query="reliability",
                    page_size=1,
                )
            )
        finally:
            await browser.close()

    assert [person.profile_slug for person in people] == ["late-person-"]
    assert coverage.stop_reason is StopReason.RESULT_LIMIT


@pytest.mark.timeout(20)
async def test_people_search_only_completes_empty_on_visible_end_state() -> None:
    html = (
        "<html><body><main><h1>People</h1>"
        "<p>We couldn&#8217;t find any results.</p></main></body></html>"
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        collector = PeopleSearchPage(
            cast(
                BrowserManager,
                PeopleFixtureBrowser(page, search_html=html),
            ),
            max_pages=1,
        )
        try:
            people, coverage, _, _ = await collector.collect(
                PeopleSearchInput(
                    context_id="context-1",
                    request_id="empty-people-results",
                    query="impossible",
                )
            )
        finally:
            await browser.close()

    assert people == ()
    assert coverage.stop_reason is StopReason.NO_NEW_RESULTS


@pytest.mark.timeout(20)
async def test_people_search_stops_cleanly_at_live_anonymous_result_boundary() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = CurrentPeoplePaginationFixtureBrowser(page)
        collector = PeopleSearchPage(cast(BrowserManager, fixture_browser), max_pages=5)
        try:
            people, coverage, captured_text, _ = await collector.collect(
                PeopleSearchInput(
                    context_id="context-1",
                    request_id="anonymous-people-boundary",
                    filters=PeopleSearchFilters(
                        connection_degrees=(PeopleSearchConnectionDegree.SECOND,),
                    ),
                    page_size=25,
                )
            )
        finally:
            await browser.close()

    assert [person.profile_slug for person in people] == [
        "jordan-result-",
        "alex-result",
    ]
    assert coverage.pages_visited == 2
    assert coverage.result_count == 2
    assert coverage.unidentifiable_result_count == 10
    assert coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE
    assert "LinkedIn Member" in captured_text
    assert len(fixture_browser.navigations) == 2


@pytest.mark.timeout(20)
async def test_people_search_name_resolution_fails_closed_when_choice_is_missing() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = CurrentPeopleSearchFixtureBrowser(page)
        collector = PeopleSearchPage(cast(BrowserManager, fixture_browser), max_pages=1)
        try:
            with pytest.raises(ParserDriftError, match="use profile_language_ids instead"):
                await collector.collect(
                    PeopleSearchInput(
                        context_id="context-1",
                        request_id="missing-language",
                        query="engineer",
                        filters=PeopleSearchFilters(
                            profile_language_names=("Klingon",),
                        ),
                    )
                )
        finally:
            await browser.close()

    assert len(fixture_browser.navigations) == 1


@pytest.mark.timeout(30)
async def test_people_search_supports_current_filter_panel_and_result_layout() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = CurrentPeopleSearchFixtureBrowser(page)
        collector = PeopleSearchPage(cast(BrowserManager, fixture_browser), max_pages=1)
        request = PeopleSearchInput(
            context_id="context-1",
            request_id="current-people-search",
            query="distributed systems staff engineer",
            filters=PeopleSearchFilters(
                connection_degrees=(PeopleSearchConnectionDegree.SECOND,),
                actively_hiring_job_title_names=("Fixture Engineer",),
                location_names=("Fixture City",),
                connections_of_names=("Fixture Connector",),
                industry_names=("Fixture Industry",),
                profile_language_names=("English",),
                service_category_names=("Fixture Service",),
            ),
            page_size=1,
        )
        try:
            people, coverage, captured_text, first_url = await collector.collect(request)
        finally:
            await browser.close()

    assert [person.profile_slug for person in people] == ["jordan-result-"]
    assert people[0].name == "Jordan Result"
    assert people[0].headline == "Staff Software Engineer at Example Cloud"
    assert people[0].location == "Bengaluru, Karnataka, India"
    assert people[0].connection_degree is PersonConnectionDegree.SECOND
    assert people[0].mutual_connections_text == "12 mutual connections"
    assert coverage.stop_reason is StopReason.RESULT_LIMIT
    assert "Jordan Result" in captured_text
    assert len(fixture_browser.navigations) == 2
    assert len(fixture_browser.visible_control_navigations) == 1

    query = parse_qs(urlsplit(first_url).query)
    assert query["keywords"] == ["distributed systems staff engineer"]
    assert _decoded_values(query, "network") == ["S"]
    assert _decoded_values(query, "activelyHiringForJobTitles") == ["101"]
    assert _decoded_values(query, "geoUrn") == ["102713980"]
    assert _decoded_values(query, "connectionOf") == ["ACoFixtureConnector"]
    assert _decoded_values(query, "industry") == ["4"]
    assert _decoded_values(query, "profileLanguage") == ["en"]
    assert _decoded_values(query, "serviceCategory") == ["123"]


@pytest.mark.timeout(20)
async def test_people_search_current_panel_retries_one_dropped_submission() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = CurrentPeopleSearchFixtureBrowser(
            page,
            submitted_urls=("https://www.linkedin.com/search/results/people/?keywords=engineer",),
        )
        collector = PeopleSearchPage(cast(BrowserManager, fixture_browser), max_pages=1)
        try:
            people, coverage, _, source_url = await collector.collect(
                PeopleSearchInput(
                    context_id="context-1",
                    request_id="retried-current-filter",
                    query="engineer",
                    filters=PeopleSearchFilters(location_names=("Fixture City",)),
                    page_size=1,
                )
            )
        finally:
            await browser.close()

    assert [person.profile_slug for person in people] == ["jordan-result-"]
    assert coverage.stop_reason is StopReason.RESULT_LIMIT
    assert _decoded_values(parse_qs(urlsplit(source_url).query), "geoUrn") == ["102713980"]
    assert len(fixture_browser.visible_control_navigations) == 2


@pytest.mark.timeout(20)
async def test_people_search_current_panel_fails_closed_when_submission_drops_filter() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = CurrentPeopleSearchFixtureBrowser(
            page,
            submitted_url="https://www.linkedin.com/search/results/people/?keywords=engineer",
        )
        collector = PeopleSearchPage(cast(BrowserManager, fixture_browser), max_pages=1)
        try:
            with pytest.raises(ParserDriftError, match="did not retain every requested location"):
                await collector.collect(
                    PeopleSearchInput(
                        context_id="context-1",
                        request_id="dropped-current-filter",
                        query="engineer",
                        filters=PeopleSearchFilters(location_names=("Fixture City",)),
                    )
                )
        finally:
            await browser.close()

    assert len(fixture_browser.navigations) == 1
    assert len(fixture_browser.visible_control_navigations) == 2


@pytest.mark.parametrize(
    ("filters", "message"),
    (
        (
            PeopleSearchFilters(actively_hiring=True),
            "did not retain actively_hiring",
        ),
        (
            PeopleSearchFilters(
                actively_hiring_job_title_names=("Fixture Engineer",),
            ),
            "did not retain every requested actively_hiring_job_title",
        ),
    ),
)
@pytest.mark.timeout(20)
async def test_people_search_current_panel_fails_closed_when_submission_drops_toggle(
    filters: PeopleSearchFilters,
    message: str,
) -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = CurrentPeopleSearchFixtureBrowser(
            page,
            submitted_url="https://www.linkedin.com/search/results/people/?keywords=engineer",
        )
        collector = PeopleSearchPage(cast(BrowserManager, fixture_browser), max_pages=1)
        try:
            with pytest.raises(ParserDriftError, match=message):
                await collector.collect(
                    PeopleSearchInput(
                        context_id="context-1",
                        request_id="dropped-current-toggle",
                        query="engineer",
                        filters=filters,
                    )
                )
        finally:
            await browser.close()


@pytest.mark.timeout(30)
async def test_person_profile_supports_current_heading_and_roleless_detail_layout() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = CurrentProfileFixtureBrowser(page)
        reader = PersonProfilePage(
            cast(BrowserManager, fixture_browser),
            max_detail_pages=10,
        )
        try:
            person, captures = await reader.read(
                PeopleGetInput(
                    context_id="context-1",
                    request_id="current-profile",
                    profile_slug="jane-doe",
                )
            )
        finally:
            await browser.close()

    assert person.name == "Jane Doe"
    assert person.headline == "Staff Software Engineer building reliable AI systems"
    assert person.location == "Bengaluru, Karnataka, India"
    assert person.current_company_text == "Acme Cloud"
    assert person.education_summary_text == "Stanford University"
    assert person.about == ("I build dependable distributed systems and mentor engineering teams.")
    assert [experience.title for experience in person.experiences] == [
        "Staff Software Engineer",
        "Senior Software Engineer",
        "Software Engineer Intern",
    ]
    assert person.experiences[0].organization is None
    assert person.experiences[0].employment_type == "Full-time"
    assert person.experiences[0].location is None
    assert person.experiences[0].description == (
        "• Leading reliability engineering.\nCore Technologies: Distributed systems and Python"
    )
    assert person.experiences[0].is_current is True
    assert person.experiences[1].organization is None
    assert person.experiences[1].employment_type == "Full-time"
    assert person.experiences[1].location is None
    assert person.experiences[1].description == (
        "• Built high-scale storage services.\nSkills: Cloud Storage • Reliability"
    )
    assert person.experiences[2].organization is None
    assert person.experiences[2].employment_type == "Internship"
    assert person.experiences[2].location is None
    assert person.experiences[2].description is None
    assert person.experiences[1].is_current is False
    assert [education.school for education in person.education] == [
        "Stanford University",
        "Example Institute of Technology",
    ]
    assert person.education[0].degree == "Master of Science"
    assert person.education[0].field_of_study == "Computer Science"
    assert {section.key for section in person.sections} >= {
        "about",
        "experience",
        "education",
        "projects",
    }
    assert {section.key for section in person.sections}.isdisjoint(
        {
            "explore-premium-profiles",
            "more-profiles-for-you",
            "people-you-may-know",
            "who-your-viewers-also-viewed",
        }
    )
    project = next(section for section in person.sections if section.key == "projects")
    assert project.entries[0].title == "Open Reliability Toolkit"
    assert str(project.entries[0].links[0].url) == "https://example.com/reliability-toolkit"
    assert person.coverage.pages_visited == 3
    assert person.coverage.detail_pages_discovered == 2
    assert person.coverage.detail_pages_visited == 2
    assert person.coverage.truncated is False
    assert len(captures) == 3
    assert "Who your viewers also viewed" in captures[0].captured_text
    captured_by_url = {str(capture.source_url): capture.captured_text for capture in captures}
    assert all(
        evidence.quote in captured_by_url[str(evidence.source_url)] for evidence in person.evidence
    )


@pytest.mark.timeout(20)
async def test_person_profile_ignores_self_verification_and_guidance() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = SelfProfileFixtureBrowser(page)
        reader = PersonProfilePage(
            cast(BrowserManager, fixture_browser),
            max_detail_pages=10,
        )
        try:
            person, captures = await reader.read(
                PeopleGetInput(
                    context_id="context-1",
                    request_id="self-profile-current",
                    profile_slug="test-member",
                )
            )
        finally:
            await browser.close()

    assert person.name == "Test Member"
    assert person.headline == "Software Engineer at Example Cloud"
    assert person.location == "Fixture City, Test Region"
    assert person.connection_count_text == "1 connection"
    assert person.current_company_text == "Example Cloud"
    assert person.education_summary_text == "Fixture University"
    assert person.sections == ()
    assert person.coverage.detail_pages_discovered == 0
    assert person.coverage.detail_pages_visited == 0
    assert person.coverage.detail_sections_discovered == ()
    assert person.coverage.truncated is False
    assert len(captures) == 1
    assert fixture_browser.navigations == ["https://www.linkedin.com/in/test-member/"]


@pytest.mark.timeout(20)
async def test_person_profile_reads_current_roleless_detail_collection_cards() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = CurrentRolelessDetailFixtureBrowser(page)
        reader = PersonProfilePage(
            cast(BrowserManager, fixture_browser),
            max_detail_pages=10,
        )
        try:
            person, captures = await reader.read(
                PeopleGetInput(
                    context_id="context-1",
                    request_id="current-roleless-honors",
                    profile_slug="jane-doe",
                    sections=(PersonProfileSectionSelector.HONORS_AWARDS,),
                )
            )
        finally:
            await browser.close()

    assert tuple(section.key for section in person.sections) == ("honors-awards",)
    assert [entry.title for entry in person.sections[0].entries] == [
        "Reliability Engineering Award",
        "Open Source Finalist",
    ]
    assert person.sections[0].entries[0].subtitle == "Issued by Acme Foundation · Jun 2025"
    assert "More profiles for you" not in person.sections[0].visible_text
    assert person.coverage.detail_sections_visited == ("honors-awards",)
    assert person.coverage.truncated is False
    assert len(captures) == 2
    assert fixture_browser.navigations == [
        "https://www.linkedin.com/in/jane-doe/",
        "https://www.linkedin.com/in/jane-doe/details/honors/",
    ]


@pytest.mark.timeout(30)
async def test_person_profile_visits_and_returns_only_selected_detail_sections() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = PeopleFixtureBrowser(page)
        reader = PersonProfilePage(
            cast(BrowserManager, fixture_browser),
            max_detail_pages=10,
        )
        try:
            person, captures = await reader.read(
                PeopleGetInput(
                    context_id="context-1",
                    request_id="profile-skills-only",
                    profile_slug="jane-doe",
                    sections=(PersonProfileSectionSelector.SKILLS,),
                )
            )
        finally:
            await browser.close()

    assert person.about is None
    assert person.experiences == ()
    assert person.education == ()
    assert tuple(section.key for section in person.sections) == ("skills",)
    assert [entry.title for entry in person.sections[0].entries] == [
        "Distributed Systems",
        "Python",
        "Kubernetes",
    ]
    assert person.sections[0].entries[0].subtitle == "Staff Software Engineer at Acme Cloud"
    assert all(entry.subtitle != "Endorse" for entry in person.sections[0].entries)
    assert person.coverage.requested_sections == (PersonProfileSectionSelector.SKILLS,)
    assert person.coverage.returned_sections == ("overview", "skills")
    assert person.coverage.detail_pages_discovered == 3
    assert person.coverage.detail_pages_visited == 1
    assert person.coverage.detail_sections_visited == ("skills",)
    assert person.coverage.unavailable_sections == ()
    assert person.coverage.truncated is False
    assert len(captures) == 2
    assert fixture_browser.navigations == [
        "https://www.linkedin.com/in/jane-doe/",
        "https://www.linkedin.com/in/jane-doe/details/skills/",
    ]


@pytest.mark.timeout(30)
async def test_person_profile_reports_unavailable_and_truncated_selected_sections() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = PeopleFixtureBrowser(page)
        reader = PersonProfilePage(
            cast(BrowserManager, fixture_browser),
            max_detail_pages=2,
        )
        try:
            person, _captures = await reader.read(
                PeopleGetInput(
                    context_id="context-1",
                    request_id="profile-selected-coverage",
                    profile_slug="jane-doe",
                    sections=(
                        PersonProfileSectionSelector.EXPERIENCE,
                        PersonProfileSectionSelector.EDUCATION,
                        PersonProfileSectionSelector.SKILLS,
                        PersonProfileSectionSelector.PROJECTS,
                    ),
                )
            )
        finally:
            await browser.close()

    assert person.coverage.detail_sections_visited == ("experience", "education")
    assert person.coverage.truncated_sections == ("skills",)
    assert person.coverage.unavailable_sections == (PersonProfileSectionSelector.PROJECTS,)
    assert person.coverage.truncated is True
    assert {section.key for section in person.sections} == {
        "experience",
        "education",
        "skills",
    }


@pytest.mark.timeout(20)
async def test_person_profile_overview_selection_never_visits_detail_pages() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = PeopleFixtureBrowser(page)
        reader = PersonProfilePage(
            cast(BrowserManager, fixture_browser),
            max_detail_pages=10,
        )
        try:
            person, captures = await reader.read(
                PeopleGetInput(
                    context_id="context-1",
                    request_id="profile-overview-only",
                    profile_slug="jane-doe",
                    sections=(PersonProfileSectionSelector.OVERVIEW,),
                )
            )
        finally:
            await browser.close()

    assert person.sections == ()
    assert person.about is None
    assert person.experiences == ()
    assert person.education == ()
    assert person.coverage.returned_sections == ("overview",)
    assert person.coverage.detail_pages_discovered == 3
    assert person.coverage.detail_pages_visited == 0
    assert person.coverage.unavailable_sections == ()
    assert person.coverage.truncated is False
    assert len(captures) == 1
    assert fixture_browser.navigations == ["https://www.linkedin.com/in/jane-doe/"]


@pytest.mark.timeout(20)
async def test_person_profile_fails_closed_without_visible_name() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            with pytest.raises(ParserDriftError, match="visible heading"):
                await PersonProfilePage(
                    cast(
                        BrowserManager,
                        StaticProfileBrowser(
                            page,
                            "<html><body><main>Profile without a name</main></body></html>",
                        ),
                    ),
                    max_detail_pages=0,
                ).read(
                    PeopleGetInput(
                        context_id="context-1",
                        request_id="missing-name",
                        profile_slug="missing-name",
                    )
                )
        finally:
            await browser.close()
