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

import linkedin_mcp.browser.pages.jobs as jobs_page_module
from linkedin_mcp.browser import BrowserManager
from linkedin_mcp.browser.pages import JobDetailPage, JobSearchPage
from linkedin_mcp.domain.evidence import source_from_job_detail
from linkedin_mcp.domain.models import (
    JobApplyMethod,
    JobBenefit,
    JobCommitment,
    JobDetailInput,
    JobEmploymentType,
    JobExperienceLevel,
    JobSearchFilters,
    JobSearchInput,
    JobSearchSort,
    JobWorkplaceType,
    StopReason,
)
from linkedin_mcp.errors import ParserDriftError

FIXTURES = Path(__file__).parents[1] / "fixtures" / "linkedin"
JOB_FIXTURES = FIXTURES / "jobs" / "latest"


class FixtureBrowser:
    def __init__(self, page: Page, html: str) -> None:
        self._page = page
        self.html = html
        self.navigations: list[str] = []

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        yield self._page

    async def navigate(self, page: Page, url: str) -> None:
        self.navigations.append(url)
        await page.set_content(self.html)

    async def click_visible_control(self, page: Page, control: Locator) -> None:
        await control.click()
        await page.wait_for_timeout(10)


class PagedFixtureBrowser(FixtureBrowser):
    def __init__(self, page: Page, first_page: str, second_page: str) -> None:
        super().__init__(page, first_page)
        self._first_page = first_page
        self._second_page = second_page

    async def navigate(self, page: Page, url: str) -> None:
        self.navigations.append(url)
        start = parse_qs(urlsplit(url).query).get("start", ["0"])[0]
        await page.set_content(self._second_page if start == "25" else self._first_page)


class DelayedDetailBrowser(FixtureBrowser):
    async def navigate(self, page: Page, url: str) -> None:
        self.navigations.append(url)
        await page.set_content(
            """
            <!doctype html>
            <html>
              <head>
                <title>Senior Python Engineer | Acme Cloud | LinkedIn</title>
              </head>
              <body>
                <main>
                  <div id="job-top-card">
                    <a href="https://www.linkedin.com/company/acme-cloud/life/">
                      Acme Cloud
                    </a>
                    <p>Senior Python Engineer</p>
                    <p>Bengaluru, India · 3 hours ago</p>
                    <a href="https://www.linkedin.com/jobs/view/4100000001/">
                      Hybrid
                    </a>
                    <a href="https://www.linkedin.com/jobs/view/4100000001/">
                      Full-time
                    </a>
                    <button type="button" aria-label="Save the job">Save</button>
                  </div>
                  <div id="late-detail"></div>
                </main>
              </body>
            </html>
            """
        )
        await page.evaluate(
            """
            () => {
              window.setTimeout(() => {
                document.querySelector("#late-detail").innerHTML = `
                  <section>
                    <div><h2>About the job</h2></div>
                    <div data-testid="expandable-text-box">
                      Build reliable Python services after rendering.
                    </div>
                  </section>
                `;
              }, 50);
            }
            """
        )


def test_latest_job_fixture_manifest_locks_live_verified_ui_contract() -> None:
    manifest = json.loads((JOB_FIXTURES / "manifest.json").read_text())

    assert manifest["provenance"] == "mock_verified"
    assert manifest["verified_at"] == "2026-07-30"
    assert manifest["contains_live_data"] is False
    assert manifest["contains_authentication_state"] is False
    assert manifest["search_card_selector"] == "main li[data-occludable-job-id]"
    assert manifest["search_company_identity_optional"] is True
    assert manifest["detail_company_identity_optional"] is True
    assert "Other" in manifest["job_type_choices"]
    assert manifest["sort_choices"] == ["Most relevant", "Most recent"]
    assert len(manifest["experience_level_choices"]) == 6
    assert len(manifest["workplace_type_choices"]) == 3
    assert len(manifest["benefit_choices"]) == 11
    assert len(manifest["commitment_choices"]) == 5
    assert manifest["top_filter_controls"] == ["Distance"]
    assert "Distance" not in manifest["all_filters_dialog_sections"]
    assert manifest["search_empty_signals"] == [
        "0 results",
        "Jobs you may be interested in",
    ]


def _current_job_card(job_id: str, title: str, company: str) -> str:
    return f"""
      <li data-occludable-job-id="{job_id}">
        <div data-job-id="{job_id}" class="job-card-container job-card-list">
          <div class="artdeco-entity-lockup__title">
            <a
              class="job-card-list__title--link"
              href="/jobs/view/{job_id}/"
              aria-label="{title}"
            >
              <span aria-hidden="true"><strong>{title}</strong></span>
              <span class="visually-hidden">{title}</span>
            </a>
          </div>
          <div class="artdeco-entity-lockup__subtitle"><span>{company}</span></div>
          <div class="artdeco-entity-lockup__caption"><span>India (Remote)</span></div>
          <ul class="job-card-list__footer-wrapper"><li>1 hour ago</li></ul>
        </div>
      </li>
    """


def _current_search_page(
    cards: tuple[tuple[str, str, str], ...],
    *,
    result_count: int,
    has_next: bool,
    page_number: int,
) -> str:
    card_html = "\n".join(_current_job_card(*card) for card in cards)
    next_button = (
        '<button type="button" aria-label="View next page">Next</button>' if has_next else ""
    )
    return f"""
      <!doctype html>
      <html><body>
        <section aria-label="search filters">
          <h2>Jobs search</h2>
          <button type="button" aria-label="Show all filters">All filters</button>
        </section>
        <main>
          <header class="scaffold-layout__list-header">
            <h1>engineer in India</h1><span>{result_count} results</span>
          </header>
          <ul>{card_html}</ul>
          <button type="button" aria-label="Page {page_number}">{page_number}</button>
          {next_button}
        </main>
      </body></html>
    """


@pytest.mark.timeout(20)
async def test_current_job_search_cards_extract_exact_typed_fields_and_evidence() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.set_content((FIXTURES / "jobs/latest/search.html").read_text())
            jobs = await JobSearchPage.extract_visible_jobs(page)
        finally:
            await browser.close()

    assert [job.job_id for job in jobs] == [
        "4100000001",
        "4100000002",
        "4100000004",
    ]
    assert jobs[0].title == "Senior Python Engineer"
    assert jobs[0].company_name == "Acme Cloud"
    assert jobs[0].location == "Bengaluru, Karnataka, India"
    assert jobs[0].workplace_type is JobWorkplaceType.HYBRID
    assert jobs[0].listed_at_text == "3 hours ago"
    assert jobs[0].easy_apply is True
    assert jobs[0].verified is True
    assert jobs[0].promoted is True
    assert "12 connections work here" in jobs[0].insights
    assert jobs[1].workplace_type is JobWorkplaceType.REMOTE
    assert jobs[1].easy_apply is False
    assert "₹25K/month - ₹45K/month" in jobs[1].insights
    assert jobs[2].title == "Anonymous Android Engineer"
    assert jobs[2].company_name is None
    assert jobs[2].company_url is None
    assert jobs[2].location == "India"
    assert jobs[2].workplace_type is JobWorkplaceType.REMOTE
    assert jobs[2].promoted is True
    assert all(item.quote in job.visible_text for job in jobs for item in job.evidence)


@pytest.mark.timeout(20)
async def test_current_job_card_supports_aria_title_company_link_and_plain_location() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.set_content(
                """
                <main>
                  <li data-occludable-job-id="4100000010">
                    <div data-job-id="4100000010">
                      <a
                        class="job-card-list__title--link"
                        href="/jobs/view/4100000010/"
                        aria-label="Accessible Reliability Engineer with verification"
                      ></a>
                      <div class="artdeco-entity-lockup__subtitle">
                        <a href="/company/observed-systems/">Observed Systems</a>
                      </div>
                      <div class="artdeco-entity-lockup__caption">Worldwide</div>
                      <ul class="job-card-list__footer-wrapper">
                        <li>Has verifications</li>
                      </ul>
                    </div>
                  </li>
                </main>
                """
            )
            jobs = await JobSearchPage.extract_visible_jobs(page)
        finally:
            await browser.close()

    assert len(jobs) == 1
    assert jobs[0].title == "Accessible Reliability Engineer"
    assert jobs[0].verified is True
    assert jobs[0].company_name == "Observed Systems"
    assert str(jobs[0].company_url) == ("https://www.linkedin.com/company/observed-systems/")
    assert jobs[0].location == "Worldwide"
    assert jobs[0].workplace_type is None
    assert jobs[0].listed_at_text is None


@pytest.mark.timeout(20)
async def test_job_search_cards_fail_closed_on_identity_and_title_corruption() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            duplicate = _current_job_card(
                "4100000011",
                "Duplicate One",
                "Observed Systems",
            )
            await page.set_content(f"<main><ul>{duplicate}{duplicate}</ul></main>")
            with pytest.raises(ParserDriftError, match="duplicate result-card identities"):
                await JobSearchPage.extract_visible_jobs(page)

            await page.set_content(
                f"<main><ul>{_current_job_card('invalid-id', 'Invalid', 'Observed')}</ul></main>"
            )
            with pytest.raises(ParserDriftError, match="invalid result-card identity"):
                await JobSearchPage.extract_visible_jobs(page)

            await page.set_content(
                """
                <main>
                  <li data-occludable-job-id="4100000012">
                    <a
                      class="job-card-list__title--link"
                      href="/jobs/view/4100000013/"
                      aria-label="Mismatched Role"
                    ></a>
                    <div class="artdeco-entity-lockup__subtitle">Observed</div>
                    <div class="artdeco-entity-lockup__caption">India</div>
                  </li>
                </main>
                """
            )
            with pytest.raises(ParserDriftError, match="mismatched result link"):
                card = page.locator('li[data-occludable-job-id="4100000012"]')
                link = card.locator("a.job-card-list__title--link")
                await JobSearchPage._extract_job_card(  # pyright: ignore[reportPrivateUsage]
                    card,
                    link,
                    "4100000012",
                )

            await page.set_content(
                """
                <main>
                  <li data-occludable-job-id="4100000014">
                    <a
                      class="job-card-list__title--link"
                      href="/jobs/view/4100000014/"
                    ></a>
                    <div class="artdeco-entity-lockup__subtitle">Observed</div>
                    <div class="artdeco-entity-lockup__caption">India</div>
                  </li>
                </main>
                """
            )
            with pytest.raises(ParserDriftError, match="without visible title"):
                await JobSearchPage.extract_visible_jobs(page)
        finally:
            await browser.close()


@pytest.mark.timeout(20)
async def test_job_search_collects_scoped_source_and_visible_terminal_coverage() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = FixtureBrowser(
            page,
            (FIXTURES / "jobs/latest/search.html").read_text(),
        )
        collector = JobSearchPage(cast(BrowserManager, fixture_browser), max_pages=3)
        try:
            jobs, coverage, captured_text, source_url = await collector.collect(
                JobSearchInput(
                    context_id="context-1",
                    request_id="current-search",
                    query="software engineer",
                    page_size=10,
                )
            )
        finally:
            await browser.close()

    assert len(jobs) == 3
    assert coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE
    assert coverage.pages_visited == 1
    assert coverage.advertised_result_count == 42
    assert coverage.advertised_result_count_is_lower_bound is False
    assert "software engineer in India" in captured_text
    assert "Senior Python Engineer" in captured_text
    assert "About the job" not in captured_text
    assert source_url.endswith("keywords=software+engineer")


@pytest.mark.timeout(20)
async def test_job_search_hydrates_every_virtualized_shell_before_completion() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        collector = JobSearchPage(
            cast(
                BrowserManager,
                FixtureBrowser(
                    page,
                    (FIXTURES / "jobs/latest/search-virtualized.html").read_text(),
                ),
            ),
            max_pages=1,
        )
        try:
            jobs, coverage, _, _ = await collector.collect(
                JobSearchInput(
                    context_id="context-1",
                    request_id="virtualized-search",
                    query="platform engineer",
                    page_size=20,
                )
            )
        finally:
            await browser.close()

    assert len(jobs) == 8
    assert jobs[0].job_id == "4100000101"
    assert jobs[-1].job_id == "4100000108"
    assert len({job.job_id for job in jobs}) == 8
    assert coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE


@pytest.mark.timeout(20)
async def test_zero_result_recommendations_are_never_returned_as_query_matches() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        collector = JobSearchPage(
            cast(
                BrowserManager,
                FixtureBrowser(
                    page,
                    (FIXTURES / "jobs/latest/search-empty.html").read_text(),
                ),
            ),
            max_pages=1,
        )
        try:
            jobs, coverage, captured_text, _ = await collector.collect(
                JobSearchInput(
                    context_id="context-1",
                    request_id="empty-search",
                    query="impossible exact query",
                )
            )
        finally:
            await browser.close()

    assert jobs == ()
    assert coverage.stop_reason is StopReason.NO_NEW_RESULTS
    assert "Jobs you may be interested in" in captured_text
    assert coverage.result_count == 0


@pytest.mark.timeout(20)
async def test_numeric_zero_result_is_terminal_before_filters_render() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        collector = JobSearchPage(
            cast(BrowserManager, FixtureBrowser(page, "<main><p>0 results</p></main>")),
            max_pages=1,
        )
        try:
            jobs, coverage, captured_text, _ = await collector.collect(
                JobSearchInput(
                    context_id="context-1",
                    request_id="numeric-empty-search",
                    query="no current match",
                )
            )
        finally:
            await browser.close()

    assert jobs == ()
    assert coverage.stop_reason is StopReason.NO_NEW_RESULTS
    assert captured_text == "0 results"


@pytest.mark.timeout(20)
async def test_job_search_fails_closed_when_current_shell_contract_never_settles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jobs_page_module, "_SEARCH_SETTLE_ATTEMPTS", 2)
    monkeypatch.setattr(jobs_page_module, "_SEARCH_SETTLE_DELAY_MS", 1)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        collector = JobSearchPage(
            cast(BrowserManager, FixtureBrowser(page, "<main><p>Loading jobs</p></main>")),
            max_pages=1,
        )
        try:
            with pytest.raises(ParserDriftError, match="did not settle"):
                await collector.collect(
                    JobSearchInput(
                        context_id="context-1",
                        request_id="unsettled-search",
                        query="engineer",
                    )
                )
        finally:
            await browser.close()


@pytest.mark.timeout(30)
async def test_job_search_uses_visible_next_control_for_exact_page_traversal() -> None:
    first_page = _current_search_page(
        (
            ("4100000201", "Engineer One", "Company One"),
            ("4100000202", "Engineer Two", "Company Two"),
        ),
        result_count=4,
        has_next=True,
        page_number=1,
    )
    second_page = _current_search_page(
        (
            ("4100000203", "Engineer Three", "Company Three"),
            ("4100000204", "Engineer Four", "Company Four"),
        ),
        result_count=4,
        has_next=False,
        page_number=2,
    )
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = PagedFixtureBrowser(page, first_page, second_page)
        collector = JobSearchPage(cast(BrowserManager, fixture_browser), max_pages=3)
        try:
            limited_jobs, limited_coverage, _, _ = await collector.collect(
                JobSearchInput(
                    context_id="context-1",
                    request_id="limited-pages",
                    query="engineer",
                    page_size=3,
                )
            )
            all_jobs, all_coverage, _, _ = await collector.collect(
                JobSearchInput(
                    context_id="context-1",
                    request_id="all-pages",
                    query="engineer",
                    page_size=10,
                )
            )
        finally:
            await browser.close()

    assert [job.job_id for job in limited_jobs] == [
        "4100000201",
        "4100000202",
        "4100000203",
    ]
    assert limited_coverage.stop_reason is StopReason.RESULT_LIMIT
    assert limited_coverage.pages_visited == 2
    assert [job.job_id for job in all_jobs] == [
        "4100000201",
        "4100000202",
        "4100000203",
        "4100000204",
    ]
    assert all_coverage.stop_reason is StopReason.VISIBLE_PAGE_COMPLETE
    assert all_coverage.pages_visited == 2


def test_job_search_url_supports_optional_keywords_and_every_visible_date_choice() -> None:
    default_request = JobSearchInput(
        context_id="context-1",
        request_id="default-any-time",
        query="engineer",
    )
    any_time = JobSearchInput(
        context_id="context-1",
        request_id="any-time",
        query=None,
        location="India",
        freshness_hours=None,
    )
    past_month = any_time.model_copy(update={"request_id": "past-month", "freshness_hours": 720})

    default_query = parse_qs(urlsplit(JobSearchPage.build_url(default_request)).query)
    any_time_query = parse_qs(urlsplit(JobSearchPage.build_url(any_time)).query)
    past_month_query = parse_qs(urlsplit(JobSearchPage.build_url(past_month)).query)

    assert default_request.freshness_hours is None
    assert default_query == {"keywords": ["engineer"]}
    assert any_time_query == {"location": ["India"]}
    assert past_month_query == {
        "location": ["India"],
        "f_TPR": ["r2592000"],
    }
    with pytest.raises(ValidationError):
        JobSearchInput.model_validate(
            {
                "context_id": "context-1",
                "request_id": "unsupported-date",
                "query": "python",
                "freshness_hours": 2,
            }
        )


def test_job_search_url_encodes_every_current_typed_filter_category() -> None:
    request = JobSearchInput(
        context_id="context-1",
        request_id="request-filtered",
        query='"python engineer" NOT staffing',
        location="India",
        freshness_hours=24,
        filters=JobSearchFilters(
            sort_by=JobSearchSort.MOST_RECENT,
            location_geo_id="102713980",
            distance_miles=50,
            workplace_types=(JobWorkplaceType.REMOTE, JobWorkplaceType.HYBRID),
            experience_levels=(
                JobExperienceLevel.ENTRY_LEVEL,
                JobExperienceLevel.ASSOCIATE,
            ),
            employment_types=(
                JobEmploymentType.FULL_TIME,
                JobEmploymentType.OTHER,
            ),
            location_ids=("105214831", "105556991"),
            company_ids=("1441", "1035"),
            industry_ids=("4", "96"),
            job_function_ids=("eng", "it"),
            job_title_ids=("9", "25201"),
            benefits=(JobBenefit.MEDICAL_INSURANCE, JobBenefit.PENSION_PLAN),
            commitments=(
                JobCommitment.CAREER_GROWTH_AND_LEARNING,
                JobCommitment.SOCIAL_IMPACT,
            ),
            easy_apply_only=True,
            has_verifications=True,
            under_10_applicants=True,
            in_your_network=True,
            fair_chance_employer=True,
        ),
        page_size=50,
    )

    query = parse_qs(urlsplit(JobSearchPage.build_url(request)).query)

    assert query == {
        "keywords": ['"python engineer" NOT staffing'],
        "location": ["India"],
        "f_TPR": ["r86400"],
        "sortBy": ["DD"],
        "geoId": ["102713980"],
        "distance": ["50"],
        "f_WT": ["2,3"],
        "f_E": ["2,3"],
        "f_JT": ["F,O"],
        "f_PP": ["105214831,105556991"],
        "f_C": ["1441,1035"],
        "f_I": ["4,96"],
        "f_F": ["eng,it"],
        "f_T": ["9,25201"],
        "f_BE": ["1,5"],
        "f_CM": ["5,4"],
        "f_AL": ["true"],
        "f_VJ": ["true"],
        "f_EA": ["true"],
        "f_JIYN": ["true"],
        "f_FCE": ["true"],
    }


def test_job_search_url_encodes_every_current_enum_choice() -> None:
    request = JobSearchInput(
        context_id="context-1",
        request_id="request-all-enums",
        query="engineer",
        filters=JobSearchFilters(
            workplace_types=tuple(JobWorkplaceType),
            experience_levels=tuple(JobExperienceLevel),
            employment_types=tuple(JobEmploymentType),
            benefits=tuple(JobBenefit),
            commitments=tuple(JobCommitment),
        ),
    )
    query = parse_qs(urlsplit(JobSearchPage.build_url(request)).query)

    assert query["f_WT"] == ["1,2,3"]
    assert query["f_E"] == ["1,2,3,4,5,6"]
    assert query["f_JT"] == ["F,P,C,T,I,V,O"]
    assert query["f_BE"] == ["1,2,3,4,5,7,8,9,10,11,12"]
    assert query["f_CM"] == ["5,1,2,4,3"]


def test_job_search_filters_reject_invalid_combinations_and_duplicates() -> None:
    with pytest.raises(ValidationError, match="distance_miles requires"):
        JobSearchInput(
            context_id="context-1",
            request_id="distance-without-location",
            query="engineer",
            filters=JobSearchFilters(distance_miles=25),
        )
    with pytest.raises(ValidationError, match="workplace_types cannot contain duplicate"):
        JobSearchFilters(workplace_types=(JobWorkplaceType.REMOTE, JobWorkplaceType.REMOTE))
    with pytest.raises(ValidationError, match="company_names cannot contain duplicate"):
        JobSearchFilters(company_names=("OpenAI", " openai "))
    with pytest.raises(ValidationError):
        JobSearchFilters.model_validate({"company_ids": ["not a LinkedIn ID"]})
    with pytest.raises(ValidationError, match="at most ten combined"):
        JobSearchFilters(
            job_title_ids=tuple(str(index) for index in range(5)),
            job_title_names=tuple(f"Title {index}" for index in range(6)),
        )


@pytest.mark.timeout(20)
async def test_job_search_resolves_current_visible_facet_names_to_exact_ids() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = FixtureBrowser(
            page,
            (FIXTURES / "jobs/latest/search-filters.html").read_text(),
        )
        collector = JobSearchPage(cast(BrowserManager, fixture_browser), max_pages=1)
        request = JobSearchInput(
            context_id="context-1",
            request_id="request-named-filters",
            query="python",
            filters=JobSearchFilters(
                location_names=("Bengaluru",),
                company_names=("OpenAI",),
                industry_names=("Software Development",),
                job_function_names=("Engineering",),
                job_title_names=("Software Engineer",),
            ),
            page_size=1,
        )
        try:
            jobs, coverage, _, first_url = await collector.collect(request)
        finally:
            await browser.close()

    assert len(jobs) == 1
    assert coverage.filters == request.filters
    assert len(fixture_browser.navigations) == 2
    resolution_query = parse_qs(urlsplit(fixture_browser.navigations[0]).query)
    result_query = parse_qs(urlsplit(fixture_browser.navigations[1]).query)
    assert not {"f_PP", "f_C", "f_I", "f_F", "f_T"} & resolution_query.keys()
    assert result_query["f_PP"] == ["105214831"]
    assert result_query["f_C"] == ["11130470"]
    assert result_query["f_I"] == ["4"]
    assert result_query["f_F"] == ["eng"]
    assert result_query["f_T"] == ["9"]
    assert first_url == fixture_browser.navigations[1]


@pytest.mark.timeout(20)
async def test_job_search_name_resolution_fails_closed_when_choice_is_not_visible() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = FixtureBrowser(
            page,
            (FIXTURES / "jobs/latest/search-filters.html").read_text(),
        )
        collector = JobSearchPage(cast(BrowserManager, fixture_browser), max_pages=1)
        try:
            with pytest.raises(ParserDriftError, match="use location_ids instead"):
                await collector.collect(
                    JobSearchInput(
                        context_id="context-1",
                        request_id="request-unknown-location",
                        query="python",
                        filters=JobSearchFilters(location_names=("Atlantis",)),
                    )
                )
        finally:
            await browser.close()


@pytest.mark.timeout(20)
async def test_current_easy_apply_job_expands_jd_and_retains_hiring_team() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = FixtureBrowser(
            page,
            (FIXTURES / "jobs/latest/detail-easy-apply.html").read_text(),
        )
        reader = JobDetailPage(cast(BrowserManager, fixture_browser))
        try:
            job = await reader.read(
                JobDetailInput(
                    context_id="context-1",
                    request_id="detail-1",
                    job_id="4100000001",
                )
            )
            assert await page.locator('[data-testid="expandable-text-button"]').count() == 0
        finally:
            await browser.close()

    assert job.title == "Senior Python Engineer"
    assert job.company_name == "Acme Cloud"
    assert job.location == "Bengaluru, Karnataka, India"
    assert job.workplace_type is JobWorkplaceType.HYBRID
    assert job.employment_type == "Full-time"
    assert job.listed_at_text == "3 hours ago"
    assert job.applicant_text == "Over 100 applicants"
    assert job.apply_method is JobApplyMethod.EASY_APPLY
    assert job.easy_apply is True
    assert job.promoted is True
    assert job.description_text is not None
    assert "Improve PostgreSQL performance" in job.description_text
    assert "more" not in job.description_text[-10:].casefold()
    assert len(job.hiring_team) == 1
    assert job.hiring_team[0].profile_slug == "leena-shah-fixture"
    assert job.hiring_team[0].name == "Leena Shah"
    assert job.hiring_team[0].role_text == "Job poster"
    assert "Noise that must not enter retained job evidence." not in job.visible_text
    source = source_from_job_detail(job)
    assert all(evidence.quote in source.captured_text for evidence in job.evidence)


@pytest.mark.timeout(20)
async def test_current_external_apply_job_reports_company_site_method() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = FixtureBrowser(
            page,
            (FIXTURES / "jobs/latest/detail-external-apply.html").read_text(),
        )
        reader = JobDetailPage(cast(BrowserManager, fixture_browser))
        try:
            job = await reader.read(
                JobDetailInput(
                    context_id="context-1",
                    request_id="detail-external",
                    job_id="4100000002",
                )
            )
        finally:
            await browser.close()

    assert job.title == "Software Development Engineer"
    assert job.location == "Noida, Uttar Pradesh, India"
    assert job.workplace_type is JobWorkplaceType.ON_SITE
    assert job.applicant_text == "Over 100 people clicked apply"
    assert job.apply_method is JobApplyMethod.EXTERNAL
    assert job.easy_apply is False
    assert "Responses managed off LinkedIn" in job.insights[0]


@pytest.mark.timeout(20)
async def test_current_anonymous_job_preserves_missing_company_identity() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = FixtureBrowser(
            page,
            (FIXTURES / "jobs/latest/detail-anonymous.html").read_text(),
        )
        reader = JobDetailPage(cast(BrowserManager, fixture_browser))
        try:
            job = await reader.read(
                JobDetailInput(
                    context_id="context-1",
                    request_id="detail-anonymous",
                    job_id="4100000004",
                )
            )
        finally:
            await browser.close()

    assert job.title == "Anonymous Android Engineer"
    assert job.company_name is None
    assert job.company_url is None
    assert job.location == "India"
    assert job.workplace_type is JobWorkplaceType.REMOTE
    assert job.employment_type == "Full-time"
    assert job.apply_method is JobApplyMethod.EXTERNAL
    assert job.description_text is not None
    assert all(evidence.quote in job.visible_text for evidence in job.evidence)


@pytest.mark.timeout(20)
async def test_job_detail_uses_semantic_title_and_visible_location_fallback() -> None:
    html = """
      <!doctype html>
      <html>
        <head><title>Semantic detail fixture</title></head>
        <body>
          <main>
            <div id="job-top-card">
              <a href="https://www.linkedin.com/company/observed-systems/">
                Observed Systems
              </a>
              <h1>
                <span>Fallback Reliability Engineer</span><br />
                <span>Fallback Reliability Engineer</span>
              </h1>
              <p>Chennai, Tamil Nadu, India</p>
              <a href="https://www.linkedin.com/jobs/view/4100000015/">Remote</a>
              <a href="https://www.linkedin.com/jobs/view/4100000015/">Full-time</a>
              <button type="button" aria-label="Apply on company website">Apply</button>
              <button type="button" aria-label="Save the job">Save</button>
            </div>
            <section>
              <h2>About the job</h2>
              <div data-testid="expandable-text-box">
                Operate reliable current systems without a visible posting age.
              </div>
            </section>
          </main>
        </body>
      </html>
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        reader = JobDetailPage(cast(BrowserManager, FixtureBrowser(page, html)))
        try:
            job = await reader.read(
                JobDetailInput(
                    context_id="context-1",
                    request_id="detail-semantic-fallback",
                    job_id="4100000015",
                )
            )
        finally:
            await browser.close()

    assert job.title == "Fallback Reliability Engineer"
    assert job.location == "Chennai, Tamil Nadu, India"
    assert job.workplace_type is JobWorkplaceType.REMOTE
    assert job.listed_at_text is None
    assert job.apply_method is JobApplyMethod.EXTERNAL


@pytest.mark.timeout(20)
async def test_job_detail_uses_company_adjacent_title_without_document_identity() -> None:
    html = """
      <!doctype html>
      <html>
        <head><title>Current detail fixture</title></head>
        <body>
          <main>
            <div id="job-top-card">
              <a href="https://www.linkedin.com/company/observed-systems/">
                Observed Systems
              </a>
              <p>Company Adjacent Engineer</p>
              <p>Pune, India · 4 hours ago</p>
              <a href="https://www.linkedin.com/jobs/view/4100000016/">Hybrid</a>
              <a href="https://www.linkedin.com/jobs/view/4100000016/">Contract</a>
              <button type="button" aria-label="Save the job">Save</button>
            </div>
            <section>
              <h2>About the job</h2>
              <div data-testid="expandable-text-box">
                Verify the current title fallback without relying on document metadata.
              </div>
            </section>
          </main>
        </body>
      </html>
    """
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        reader = JobDetailPage(cast(BrowserManager, FixtureBrowser(page, html)))
        try:
            job = await reader.read(
                JobDetailInput(
                    context_id="context-1",
                    request_id="detail-company-adjacent-title",
                    job_id="4100000016",
                )
            )
        finally:
            await browser.close()

    assert job.title == "Company Adjacent Engineer"
    assert job.location == "Pune, India"
    assert job.workplace_type is JobWorkplaceType.HYBRID
    assert job.employment_type == "Contract"
    assert job.apply_method is JobApplyMethod.UNAVAILABLE


@pytest.mark.timeout(20)
async def test_current_closed_job_reports_unavailable_application_method() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = FixtureBrowser(
            page,
            (FIXTURES / "jobs/latest/detail-unavailable.html").read_text(),
        )
        reader = JobDetailPage(cast(BrowserManager, fixture_browser))
        try:
            job = await reader.read(
                JobDetailInput(
                    context_id="context-1",
                    request_id="detail-unavailable",
                    job_id="4100000003",
                )
            )
        finally:
            await browser.close()

    assert job.apply_method is JobApplyMethod.UNAVAILABLE
    assert job.easy_apply is False
    assert job.employment_type == "Contract"
    assert "No longer accepting applications" in job.insights


@pytest.mark.timeout(20)
async def test_job_detail_waits_for_current_description_to_render() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        fixture_browser = DelayedDetailBrowser(page, "")
        reader = JobDetailPage(cast(BrowserManager, fixture_browser))
        try:
            result = await reader.read(
                JobDetailInput(
                    context_id="context-1",
                    request_id="detail-delayed",
                    job_id="4100000001",
                )
            )
        finally:
            await browser.close()

    assert result.title == "Senior Python Engineer"
    assert result.description_text == "Build reliable Python services after rendering."


@pytest.mark.timeout(20)
async def test_current_job_parsers_fail_closed_on_missing_structural_contracts() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.set_content("<html><body></body></html>")
            with pytest.raises(ParserDriftError, match="no visible text"):
                await JobSearchPage.extract_visible_text(page)

            await page.set_content(
                """
                <main>
                  <li data-occludable-job-id="4100000001">
                    <a
                      class="job-card-list__title--link"
                      href="/jobs/view/4100000001/"
                      aria-label="Incomplete job"
                    >
                      <span aria-hidden="true">Incomplete job</span>
                    </a>
                  </li>
                </main>
                """
            )
            with pytest.raises(ParserDriftError, match="visible location field"):
                await JobSearchPage.extract_visible_jobs(page)

            await page.set_content(
                "<main><a href='/company/acme/'>Acme</a><p>Old layout</p></main>"
            )
            with pytest.raises(ParserDriftError, match="primary job card"):
                await JobDetailPage.extract_visible_job(page, "4100000001")
        finally:
            await browser.close()
