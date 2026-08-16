from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urljoin, urlsplit

import pytest
from playwright.async_api import Locator, Page, async_playwright
from pydantic import ValidationError

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.linkedin.browser import BrowserManager
from linkedin_mcp.linkedin.companies.evidence import sources_from_company_profile
from linkedin_mcp.linkedin.companies.pages import CompanyProfilePage, CompanySearchPage
from linkedin_mcp.linkedin.models import (
    CompanyGetInput,
    CompanyProfileEvidence,
    CompanyProfileObservation,
    CompanySearchFilters,
    CompanySearchInput,
    CompanySize,
    StopReason,
)

FIXTURES = Path(__file__).parents[1] / "fixtures" / "linkedin"
COMPANY_FIXTURES = FIXTURES / "companies" / "latest"


class CompanyFixtureBrowser:
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
        if path.startswith("/search/results/companies"):
            if self._search_html is not None:
                await page.set_content(self._search_html)
                return
            fixture = "companies/latest/search.html"
        elif path.endswith("/about/"):
            fixture = "companies/latest/about.html"
        else:
            fixture = "companies/latest/overview.html"
        await page.set_content((FIXTURES / fixture).read_text(encoding="utf-8"))

    async def click_visible_control(self, page: Page, control: Locator) -> None:
        del page
        await control.click()

    async def navigate_via_visible_control(self, page: Page, control: Locator) -> str:
        del page
        href = await control.get_attribute("href")
        if not href:
            raise AssertionError("The fixture Show results control has no target URL.")
        return urljoin("https://www.linkedin.com", href)


def _decoded_values(query: dict[str, list[str]], key: str) -> list[str]:
    return cast(list[str], json.loads(query[key][0]))


def test_company_fixture_manifest_locks_current_visible_surface() -> None:
    manifest = cast(
        dict[str, object],
        json.loads((COMPANY_FIXTURES / "manifest.json").read_text(encoding="utf-8")),
    )

    assert manifest["provenance"] == "mock_verified"
    assert manifest["verified_at"] == "2026-08-05"
    assert manifest["contains_live_data"] is False
    assert manifest["filter_sections"] == [
        "Locations",
        "Industry",
        "Company size",
        "Job listings on LinkedIn",
        "Connections",
    ]
    assert len(cast(list[object], manifest["company_size_choices"])) == 8


def test_company_contracts_reject_unbounded_search_and_invalid_filters() -> None:
    with pytest.raises(ValidationError, match="requires query"):
        CompanySearchInput(
            context_id="context-1",
            request_id="empty-company-search",
        )

    with pytest.raises(ValidationError, match="location filters must not contain duplicates"):
        CompanySearchFilters(location_ids=("india",), location_names=("INDIA",))

    with pytest.raises(ValidationError, match="combined location"):
        CompanySearchFilters(
            location_ids=tuple(str(index) for index in range(5)),
            location_names=tuple(f"Location {index}" for index in range(6)),
        )

    with pytest.raises(ValidationError, match="combined industry"):
        CompanySearchFilters(
            industry_ids=tuple(str(index) for index in range(5)),
            industry_names=tuple(f"Industry {index}" for index in range(6)),
        )

    with pytest.raises(ValueError, match="page bound"):
        CompanySearchPage(cast(BrowserManager, object()), max_pages=0)


def test_company_search_url_encodes_every_visible_filter() -> None:
    request = CompanySearchInput(
        context_id="context-1",
        request_id="company-search-filters",
        query='"cloud infrastructure" AND observability',
        filters=CompanySearchFilters(
            location_ids=("102713980",),
            industry_ids=("4",),
            company_sizes=(
                CompanySize.EMPLOYEES_51_200,
                CompanySize.EMPLOYEES_1001_5000,
            ),
            has_job_listings=True,
            has_first_degree_connections=True,
        ),
    )

    query = parse_qs(urlsplit(CompanySearchPage.build_url(request, page_index=2)).query)

    assert query["origin"] == ["GLOBAL_SEARCH_HEADER"]
    assert query["page"] == ["2"]
    assert query["keywords"] == ['"cloud infrastructure" AND observability']
    assert _decoded_values(query, "companyHqGeo") == ["102713980"]
    assert _decoded_values(query, "industryCompanyVertical") == ["4"]
    assert _decoded_values(query, "companySize") == ["D", "G"]
    assert _decoded_values(query, "hasJobs") == ["1"]
    assert _decoded_values(query, "network") == ["F"]


def test_company_search_encodes_every_current_company_size_bucket() -> None:
    expected = {
        CompanySize.EMPLOYEES_1_10: "B",
        CompanySize.EMPLOYEES_11_50: "C",
        CompanySize.EMPLOYEES_51_200: "D",
        CompanySize.EMPLOYEES_201_500: "E",
        CompanySize.EMPLOYEES_501_1000: "F",
        CompanySize.EMPLOYEES_1001_5000: "G",
        CompanySize.EMPLOYEES_5001_10000: "H",
        CompanySize.EMPLOYEES_10001_PLUS: "I",
    }
    request = CompanySearchInput(
        context_id="context-1",
        request_id="all-company-sizes",
        filters=CompanySearchFilters(company_sizes=tuple(expected)),
    )

    query = parse_qs(urlsplit(CompanySearchPage.build_url(request, page_index=1)).query)

    assert tuple(CompanySize) == tuple(expected)
    assert _decoded_values(query, "companySize") == list(expected.values())


@pytest.mark.timeout(30)
async def test_company_search_resolves_visible_names_and_extracts_results() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = CompanyFixtureBrowser(page)
        collector = CompanySearchPage(cast(BrowserManager, fixture_browser), max_pages=2)
        request = CompanySearchInput(
            context_id="context-1",
            request_id="company-named-filters",
            query="cloud",
            filters=CompanySearchFilters(
                location_names=("India",),
                industry_names=("Software Development",),
                company_sizes=(CompanySize.EMPLOYEES_1001_5000,),
            ),
            page_size=1,
        )
        try:
            companies, coverage, captured_text, source_url = await collector.collect(request)
        finally:
            await browser.close()

    assert [company.company_slug for company in companies] == ["acme-cloud"]
    assert companies[0].name == "Acme Cloud"
    assert companies[0].tagline == "Reliable cloud infrastructure"
    assert companies[0].location == "Bengaluru, Karnataka, India"
    assert companies[0].follower_count_text == "161K followers"
    assert companies[0].associated_member_count_text == "2,400 associated members"
    assert coverage.pages_visited == 1
    assert coverage.stop_reason is StopReason.RESULT_LIMIT
    assert "Acme Cloud" in captured_text
    assert source_url == fixture_browser.navigations[-1]
    assert len(fixture_browser.navigations) == 2

    query = parse_qs(urlsplit(source_url).query)
    assert _decoded_values(query, "companyHqGeo") == ["102713980"]
    assert _decoded_values(query, "industryCompanyVertical") == ["4"]
    assert _decoded_values(query, "companySize") == ["G"]


@pytest.mark.timeout(20)
async def test_company_search_name_resolution_fails_closed() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = CompanyFixtureBrowser(page)
        collector = CompanySearchPage(cast(BrowserManager, fixture_browser), max_pages=1)
        try:
            with pytest.raises(ParserDriftError, match="use industry_ids instead"):
                await collector.collect(
                    CompanySearchInput(
                        context_id="context-1",
                        request_id="missing-company-industry",
                        query="cloud",
                        filters=CompanySearchFilters(industry_names=("Aerospace",)),
                    )
                )
        finally:
            await browser.close()


@pytest.mark.timeout(30)
@pytest.mark.parametrize(
    ("max_pages", "expected_stop"),
    (
        (1, StopReason.SAFETY_BOUND),
        (2, StopReason.SAFETY_BOUND),
    ),
)
async def test_company_search_reports_private_page_stop_reasons(
    max_pages: int,
    expected_stop: StopReason,
) -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = CompanyFixtureBrowser(page)
        collector = CompanySearchPage(
            cast(BrowserManager, fixture_browser),
            max_pages=max_pages,
        )
        try:
            companies, coverage, _, _ = await collector.collect(
                CompanySearchInput(
                    context_id="context-1",
                    request_id=f"company-stop-{max_pages}",
                    filters=CompanySearchFilters(company_sizes=(CompanySize.EMPLOYEES_51_200,)),
                    page_size=10,
                )
            )
        finally:
            await browser.close()

    assert len(companies) == 2
    assert coverage.stop_reason is expected_stop
    assert coverage.pages_visited == max_pages


@pytest.mark.timeout(20)
async def test_company_search_waits_for_async_initial_results() -> None:
    html = """
    <!doctype html>
    <html><body><main>
      <h1>Company results</h1>
      <ul id="results"></ul>
      <template id="late-result">
        <li>
          <a href="/company/late-company/"><h2>Late Company</h2></a>
          <p>Reliable systems</p>
          <p>Bengaluru, India</p>
        </li>
      </template>
    </main>
    <script>
      setTimeout(() => {
        document.querySelector("#results").append(
          document.querySelector("#late-result").content.cloneNode(true)
        );
      }, 2200);
    </script></body></html>
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        collector = CompanySearchPage(
            cast(
                BrowserManager,
                CompanyFixtureBrowser(page, search_html=html),
            ),
            max_pages=1,
        )
        try:
            companies, coverage, _, _ = await collector.collect(
                CompanySearchInput(
                    context_id="context-1",
                    request_id="async-company-results",
                    query="reliability",
                    page_size=1,
                )
            )
        finally:
            await browser.close()

    assert [company.company_slug for company in companies] == ["late-company"]
    assert coverage.stop_reason is StopReason.RESULT_LIMIT


@pytest.mark.timeout(20)
async def test_company_search_only_completes_empty_on_visible_end_state() -> None:
    html = (
        "<html><body><main><h1>Companies</h1>"
        "<p>No matching companies found.</p></main></body></html>"
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        collector = CompanySearchPage(
            cast(
                BrowserManager,
                CompanyFixtureBrowser(page, search_html=html),
            ),
            max_pages=1,
        )
        try:
            companies, coverage, _, _ = await collector.collect(
                CompanySearchInput(
                    context_id="context-1",
                    request_id="empty-company-results",
                    query="impossible",
                )
            )
        finally:
            await browser.close()

    assert companies == ()
    assert coverage.stop_reason is StopReason.NO_NEW_RESULTS


@pytest.mark.timeout(30)
async def test_company_profile_reads_exact_overview_and_about_with_evidence() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = CompanyFixtureBrowser(page)
        reader = CompanyProfilePage(cast(BrowserManager, fixture_browser))
        request = CompanyGetInput(
            context_id="context-1",
            request_id="company-about-read",
            company_slug="acme-cloud",
        )
        try:
            company, captures = await reader.read(request)
        finally:
            await browser.close()

    assert company.name == "Acme Cloud"
    assert company.tagline == "Reliable cloud infrastructure"
    assert company.description == ("Acme Cloud builds reliable infrastructure for software teams.")
    assert company.website_url is not None
    assert str(company.website_url) == "https://acme.example/"
    assert company.industry == "Software Development"
    assert company.company_size_range == "1,001-5,000 employees"
    assert company.associated_member_count_text == "2,400 associated members"
    assert company.company_size_range != company.associated_member_count_text
    assert company.follower_count_text == "12K followers"
    assert company.headquarters == "Bengaluru, Karnataka"
    assert company.organization_type == "Privately Held"
    assert company.founded_text == "2015"
    assert company.specialties == (
        "Cloud infrastructure",
        "Observability",
        "Developer tools",
    )
    assert company.coverage.pages_visited == 2
    assert company.coverage.returned_sections == ("overview", "about")
    assert len(captures) == 2
    assert tuple(capture.page_kind for capture in captures) == ("overview", "about")
    assert len(sources_from_company_profile(company, captures)) == 2
    associated_member_evidence = next(
        evidence
        for evidence in company.evidence
        if evidence.field == "associated_member_count_text"
    )
    assert associated_member_evidence.source_url == captures[1].source_url
    assert fixture_browser.navigations == [
        "https://www.linkedin.com/company/acme-cloud/",
        "https://www.linkedin.com/company/acme-cloud/about/",
    ]


@pytest.mark.timeout(30)
async def test_company_profile_deduplicates_headings_for_one_visible_about_section() -> None:
    about_html = (
        (FIXTURES / "companies/latest/about.html")
        .read_text(encoding="utf-8")
        .replace("<h2>About</h2>", "<h2>About</h2><h3>Overview</h3>", 1)
    )

    class DuplicateAboutHeadingBrowser(CompanyFixtureBrowser):
        async def navigate(self, page: Page, url: str) -> None:
            if urlsplit(url).path.endswith("/about/"):
                self.navigations.append(url)
                await page.set_content(about_html)
                return
            await super().navigate(page, url)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        reader = CompanyProfilePage(cast(BrowserManager, DuplicateAboutHeadingBrowser(page)))
        try:
            company, captures = await reader.read(
                CompanyGetInput(
                    context_id="context-1",
                    request_id="duplicate-about-heading",
                    company_slug="acme-cloud",
                )
            )
        finally:
            await browser.close()

    assert company.name == "Acme Cloud"
    assert company.description == "Acme Cloud builds reliable infrastructure for software teams."
    assert company.industry == "Software Development"
    assert len(captures) == 2


@pytest.mark.timeout(30)
async def test_company_profile_fails_closed_when_about_identity_changes() -> None:
    about_html = (
        (FIXTURES / "companies/latest/about.html")
        .read_text(encoding="utf-8")
        .replace(
            "<h1>Acme Cloud</h1>",
            "<h1>Other Company</h1>",
        )
    )

    class MismatchedAboutBrowser(CompanyFixtureBrowser):
        async def navigate(self, page: Page, url: str) -> None:
            if urlsplit(url).path.endswith("/about/"):
                self.navigations.append(url)
                await page.set_content(about_html)
                return
            await super().navigate(page, url)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = MismatchedAboutBrowser(page)
        reader = CompanyProfilePage(cast(BrowserManager, fixture_browser))
        try:
            with pytest.raises(ParserDriftError, match="conflicts with the overview identity"):
                await reader.read(
                    CompanyGetInput(
                        context_id="context-1",
                        request_id="company-identity-mismatch",
                        company_slug="acme-cloud",
                    )
                )
        finally:
            await browser.close()


@pytest.mark.timeout(30)
async def test_company_profile_decodes_visible_linkedin_website_redirect() -> None:
    about_html = (
        (FIXTURES / "companies/latest/about.html")
        .read_text(encoding="utf-8")
        .replace(
            'href="https://acme.example/"',
            'href="https://www.linkedin.com/redir/redirect?url=https%3A%2F%2Facme.example%2F"',
        )
    )

    class RedirectedWebsiteBrowser(CompanyFixtureBrowser):
        async def navigate(self, page: Page, url: str) -> None:
            if urlsplit(url).path.endswith("/about/"):
                self.navigations.append(url)
                await page.set_content(about_html)
                return
            await super().navigate(page, url)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        reader = CompanyProfilePage(cast(BrowserManager, RedirectedWebsiteBrowser(page)))
        try:
            company, _ = await reader.read(
                CompanyGetInput(
                    context_id="context-1",
                    request_id="redirected-company-website",
                    company_slug="acme-cloud",
                )
            )
        finally:
            await browser.close()

    assert company.website_url is not None
    assert str(company.website_url) == "https://acme.example/"


@pytest.mark.timeout(30)
async def test_company_profile_evidence_requires_capture_and_exact_source_quote() -> None:
    with pytest.raises(ParserDriftError, match="exactly its overview and About sources"):
        sources_from_company_profile(
            cast(CompanyProfileObservation, None),
            (),
        )

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = CompanyFixtureBrowser(page)
        reader = CompanyProfilePage(cast(BrowserManager, fixture_browser))
        try:
            company, captures = await reader.read(
                CompanyGetInput(
                    context_id="context-1",
                    request_id="bad-company-evidence",
                    company_slug="acme-cloud",
                )
            )
        finally:
            await browser.close()

    bad_company = company.model_copy(
        update={
            "evidence": (
                CompanyProfileEvidence(
                    field="name",
                    quote="Invented Company",
                    source_url=captures[0].source_url,
                ),
            )
        }
    )
    with pytest.raises(ParserDriftError, match="not an exact company-source substring"):
        sources_from_company_profile(bad_company, captures)
