"""Visible LinkedIn page implementation for `linkedin_mcp.tools.jobs.search.page`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode, urljoin

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import HttpUrl

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools.jobs.search.models import (
    EvidenceField,
    JobBenefit,
    JobCommitment,
    JobEmploymentType,
    JobExperienceLevel,
    JobSearchCoverage,
    JobSearchFilters,
    JobSearchInput,
    JobSearchSort,
    JobSummary,
    JobWorkplaceType,
    StopReason,
)
from linkedin_mcp.tools.jobs.surface import (
    LISTED_PATTERN,
    WORKPLACE_LABELS,
    WORKPLACE_VALUES,
    first_href,
    first_pattern_text,
    first_text,
)
from linkedin_mcp.tools.jobs.surface import (
    lines as visible_text_lines,
)
from linkedin_mcp.ui import LinkedInLocator as Locator
from linkedin_mcp.ui import LinkedInPage as Page
from linkedin_mcp.ui import LinkedInPlaywright
from linkedin_mcp.ui.collections import CollectionSettleOutcome
from linkedin_mcp.ui.urls import (
    canonical_job_url,
    job_id_from_url,
)

_WORKPLACE_SUFFIX_PATTERN = re.compile(
    r"^(?P<location>.+?)\s+\((?P<workplace>Remote|Hybrid|On-site)\)$",
    re.IGNORECASE,
)

_WORKPLACE_FILTER_CODES = {
    JobWorkplaceType.ON_SITE: "1",
    JobWorkplaceType.REMOTE: "2",
    JobWorkplaceType.HYBRID: "3",
}

_EXPERIENCE_FILTER_CODES = {
    JobExperienceLevel.INTERNSHIP: "1",
    JobExperienceLevel.ENTRY_LEVEL: "2",
    JobExperienceLevel.ASSOCIATE: "3",
    JobExperienceLevel.MID_SENIOR: "4",
    JobExperienceLevel.DIRECTOR: "5",
    JobExperienceLevel.EXECUTIVE: "6",
}

_EMPLOYMENT_FILTER_CODES = {
    JobEmploymentType.FULL_TIME: "F",
    JobEmploymentType.PART_TIME: "P",
    JobEmploymentType.CONTRACT: "C",
    JobEmploymentType.TEMPORARY: "T",
    JobEmploymentType.INTERNSHIP: "I",
    JobEmploymentType.VOLUNTEER: "V",
    JobEmploymentType.OTHER: "O",
}

_BENEFIT_FILTER_CODES = {
    JobBenefit.MEDICAL_INSURANCE: "1",
    JobBenefit.VISION_INSURANCE: "2",
    JobBenefit.DENTAL_INSURANCE: "3",
    JobBenefit.RETIREMENT_401K: "4",
    JobBenefit.PENSION_PLAN: "5",
    JobBenefit.PAID_MATERNITY_LEAVE: "7",
    JobBenefit.PAID_PATERNITY_LEAVE: "8",
    JobBenefit.COMMUTER_BENEFITS: "9",
    JobBenefit.STUDENT_LOAN_ASSISTANCE: "10",
    JobBenefit.TUITION_ASSISTANCE: "11",
    JobBenefit.DISABILITY_INSURANCE: "12",
}

_COMMITMENT_FILTER_CODES = {
    JobCommitment.CAREER_GROWTH_AND_LEARNING: "5",
    JobCommitment.DIVERSITY_EQUITY_AND_INCLUSION: "1",
    JobCommitment.ENVIRONMENTAL_SUSTAINABILITY: "2",
    JobCommitment.SOCIAL_IMPACT: "4",
    JobCommitment.WORK_LIFE_BALANCE: "3",
}

_JOB_SEARCH_END_PATTERN = re.compile(
    r"^(?:no (?:matching )?jobs?(?: found| to show)?|"
    r"no results found|0 (?:jobs?|results?))(?:[.!])?$",
    re.IGNORECASE,
)

_JOB_RECOMMENDATIONS_HEADING = "jobs you may be interested in"

_SEARCH_SETTLE_ATTEMPTS = 80

_SEARCH_SETTLE_DELAY_MS = 250

_SEARCH_STABLE_ROUNDS = 4

_CARD_HYDRATION_TIMEOUT_MS = 5_000

_RESULT_COUNT_PATTERN = re.compile(r"\b(?P<count>[\d,]+)(?P<plus>\+)?\s+results?\b", re.I)


async def _job_search_has_explicit_end(page: Page) -> bool:
    main = page.locator("main")
    if await main.count() == 0:
        return False
    text = (await main.first.inner_text()).strip()
    lines = visible_text_lines(text)
    if any(_JOB_SEARCH_END_PATTERN.fullmatch(line) for line in lines):
        return True
    return bool(lines and lines[0].casefold() == _JOB_RECOMMENDATIONS_HEADING)


async def _wait_for_job_search_state(page: Page) -> CollectionSettleOutcome:
    """Wait for the current desktop Jobs page, including its virtualized card shells."""

    shells = page.locator("main li[data-occludable-job-id]")
    previous_signature: tuple[str, ...] = ()
    stable_rounds = 0
    for _ in range(_SEARCH_SETTLE_ATTEMPTS):
        # LinkedIn briefly renders "0 results" before replacing the list with unrelated
        # recommendations. Terminal state therefore takes precedence over card presence.
        if await _job_search_has_explicit_end(page):
            return CollectionSettleOutcome.EXPLICIT_END

        raw_ids = await shells.evaluate_all(
            "elements => elements.map(element => "
            "element.getAttribute('data-occludable-job-id')).filter(Boolean)"
        )
        signature = tuple(value for value in raw_ids if isinstance(value, str))
        filter_bar = page.locator('[aria-label="search filters"]')
        filter_ready = (
            await filter_bar.count() == 1
            and await filter_bar.locator(".jobs-ghost-placeholder").count() == 0
            and await filter_bar.get_by_role(
                "button",
                name=re.compile(r"all filters", re.IGNORECASE),
            ).count()
            > 0
        )
        pagination_ready = await page.locator('main button[aria-label^="Page "]').count() > 0
        if signature and filter_ready and pagination_ready:
            stable_rounds = stable_rounds + 1 if signature == previous_signature else 0
            if stable_rounds >= _SEARCH_STABLE_ROUNDS:
                return CollectionSettleOutcome.PROGRESSED
        else:
            stable_rounds = 0
        previous_signature = signature
        await page.wait_for_timeout(_SEARCH_SETTLE_DELAY_MS)

    raise ParserDriftError(
        "LinkedIn Jobs did not settle its visible filters, pagination, and result-card shells."
    )


@dataclass(frozen=True, slots=True)
class _ResolvedJobSearchFacets:
    location_ids: tuple[str, ...] = ()
    company_ids: tuple[str, ...] = ()
    industry_ids: tuple[str, ...] = ()
    job_function_ids: tuple[str, ...] = ()
    job_title_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _TypeaheadFacet:
    input_name: str
    add_button_name: str
    option_kind: str
    id_field_name: str


_COMPANY_FACET = _TypeaheadFacet(
    input_name="company-filter-value",
    add_button_name="Add a company",
    option_kind="Company",
    id_field_name="company_ids",
)

_INDUSTRY_FACET = _TypeaheadFacet(
    input_name="industry-filter-value",
    add_button_name="Add an industry",
    option_kind="Industry",
    id_field_name="industry_ids",
)

_JOB_FUNCTION_FACET = _TypeaheadFacet(
    input_name="job-function-filter-value",
    add_button_name="Add a job function",
    option_kind="Job function",
    id_field_name="job_function_ids",
)


def _location_and_workplace(value: str) -> tuple[str, JobWorkplaceType | None]:
    match = _WORKPLACE_SUFFIX_PATTERN.fullmatch(value)
    if match is None:
        return value, None
    return (
        match.group("location").strip(),
        JobWorkplaceType(WORKPLACE_VALUES[match.group("workplace").casefold()]),
    )


async def _job_search_result_count(page: Page) -> tuple[int | None, bool]:
    header = page.locator("main .scaffold-layout__list-header").first
    text = await first_text(header)
    if text is None:
        text = await first_text(page.locator("main"))
    if text is None:
        return None, False
    match = _RESULT_COUNT_PATTERN.search(text)
    if match is None:
        return None, False
    return int(match.group("count").replace(",", "")), bool(match.group("plus"))


async def _job_search_has_next_page(page: Page) -> bool:
    control = page.get_by_role("button", name="View next page", exact=True)
    if await control.count() == 0:
        return False
    return await control.first.is_visible() and await control.first.is_enabled()


async def _job_search_header_text(page: Page) -> str | None:
    return await first_text(page.locator("main .scaffold-layout__list-header"))


def _add_job_search_filters(
    parameters: dict[str, str | int],
    filters: JobSearchFilters,
    resolved_facets: _ResolvedJobSearchFacets | None = None,
) -> None:
    resolved = resolved_facets or _ResolvedJobSearchFacets()
    if filters.sort_by is JobSearchSort.MOST_RECENT:
        parameters["sortBy"] = "DD"
    if filters.location_geo_id:
        parameters["geoId"] = filters.location_geo_id
    if filters.distance_miles is not None:
        parameters["distance"] = filters.distance_miles
    if filters.workplace_types:
        parameters["f_WT"] = ",".join(
            _WORKPLACE_FILTER_CODES[value] for value in filters.workplace_types
        )
    if filters.experience_levels:
        parameters["f_E"] = ",".join(
            _EXPERIENCE_FILTER_CODES[value] for value in filters.experience_levels
        )
    if filters.employment_types:
        parameters["f_JT"] = ",".join(
            _EMPLOYMENT_FILTER_CODES[value] for value in filters.employment_types
        )
    if filters.benefits:
        parameters["f_BE"] = ",".join(_BENEFIT_FILTER_CODES[value] for value in filters.benefits)
    if filters.commitments:
        parameters["f_CM"] = ",".join(
            _COMMITMENT_FILTER_CODES[value] for value in filters.commitments
        )
    for values, parameter_name in (
        ((*filters.location_ids, *resolved.location_ids), "f_PP"),
        ((*filters.company_ids, *resolved.company_ids), "f_C"),
        ((*filters.industry_ids, *resolved.industry_ids), "f_I"),
        ((*filters.job_function_ids, *resolved.job_function_ids), "f_F"),
        ((*filters.job_title_ids, *resolved.job_title_ids), "f_T"),
    ):
        if values:
            parameters[parameter_name] = ",".join(dict.fromkeys(values))
    for enabled, parameter_name in (
        (filters.easy_apply_only, "f_AL"),
        (filters.has_verifications, "f_VJ"),
        (filters.under_10_applicants, "f_EA"),
        (filters.in_your_network, "f_JIYN"),
        (filters.fair_chance_employer, "f_FCE"),
    ):
        if enabled:
            parameters[parameter_name] = "true"


def _has_named_facets(filters: JobSearchFilters) -> bool:
    return any(
        (
            filters.location_names,
            filters.company_names,
            filters.industry_names,
            filters.job_function_names,
            filters.job_title_names,
        )
    )


def _normalized_visible_label(value: str) -> str:
    normalized = " ".join(value.split())
    return re.split(r"\s+Filter by\s+", normalized, maxsplit=1, flags=re.IGNORECASE)[0]


async def _visible_facet_values(dialog: Locator, input_name: str) -> dict[str, tuple[str, ...]]:
    labels_by_control_id: dict[str, str] = {}
    labels = dialog.locator("label")
    for index in range(await labels.count()):
        label = labels.nth(index)
        control_id = await label.get_attribute("for")
        if not control_id:
            continue
        label_text = _normalized_visible_label(await label.inner_text())
        if label_text:
            labels_by_control_id[control_id] = label_text

    values_by_label: dict[str, list[str]] = {}
    controls = dialog.locator(f'input[name="{input_name}"]')
    for index in range(await controls.count()):
        control = controls.nth(index)
        control_id = await control.get_attribute("id")
        if not control_id or control_id not in labels_by_control_id:
            continue
        value = (await control.input_value()).strip()
        if not value:
            continue
        key = labels_by_control_id[control_id].casefold()
        values_by_label.setdefault(key, []).append(value)
    return {key: tuple(dict.fromkeys(values)) for key, values in values_by_label.items()}


def _resolved_visible_value(
    values_by_label: dict[str, tuple[str, ...]],
    requested_name: str,
    *,
    id_field_name: str,
) -> str | None:
    values = values_by_label.get(_normalized_visible_label(requested_name).casefold(), ())
    if len(values) > 1:
        raise ParserDriftError(
            f"LinkedIn returned multiple exact matches for {requested_name!r}; "
            f"use {id_field_name} to disambiguate."
        )
    return values[0] if values else None


def _typeahead_option_label(option_text: str, option_kind: str) -> str:
    label = re.split(r"\s+[•·]\s+", " ".join(option_text.split()), maxsplit=1)[0]
    kind_suffix = f" {option_kind}"
    if label.casefold().endswith(kind_suffix.casefold()):
        return label[: -len(kind_suffix)].strip()
    return label


async def _resolve_typeahead_name(
    page: Page,
    dialog: Locator,
    requested_name: str,
    facet: _TypeaheadFacet,
) -> str:
    add_button = dialog.get_by_role("button", name=facet.add_button_name, exact=True)
    try:
        await add_button.first.wait_for(state="visible", timeout=5_000)
        await add_button.first.click()
        combobox = dialog.get_by_role("combobox", name=facet.add_button_name, exact=True)
        await combobox.wait_for(state="visible", timeout=5_000)
        await combobox.fill(requested_name)
    except PlaywrightTimeoutError as error:
        raise ParserDriftError(
            f"LinkedIn's visible {facet.add_button_name.lower()} control was unavailable."
        ) from error

    options = page.get_by_role("option")
    matching_indices: list[int] = []
    for _ in range(25):
        matching_indices.clear()
        for index in range(await options.count()):
            option = options.nth(index)
            if not await option.is_visible():
                continue
            option_text = await option.inner_text()
            if (
                _typeahead_option_label(option_text, facet.option_kind).casefold()
                == requested_name.casefold()
            ):
                matching_indices.append(index)
        if matching_indices:
            break
        await page.wait_for_timeout(200)

    if len(matching_indices) != 1:
        qualifier = "no" if not matching_indices else "multiple"
        raise ParserDriftError(
            f"LinkedIn returned {qualifier} exact visible {facet.option_kind.lower()} "
            f"matches for {requested_name!r}; use {facet.id_field_name} instead."
        )

    await options.nth(matching_indices[0]).click()
    for _ in range(25):
        values = await _visible_facet_values(dialog, facet.input_name)
        resolved = _resolved_visible_value(
            values,
            requested_name,
            id_field_name=facet.id_field_name,
        )
        if resolved:
            return resolved
        await page.wait_for_timeout(200)
    raise ParserDriftError(
        f"LinkedIn did not expose an ID after selecting {requested_name!r}; "
        f"use {facet.id_field_name} instead."
    )


async def _resolve_visible_names(
    dialog: Locator,
    requested_names: tuple[str, ...],
    *,
    input_name: str,
    id_field_name: str,
) -> tuple[str, ...]:
    if not requested_names:
        return ()
    values = await _visible_facet_values(dialog, input_name)
    resolved: list[str] = []
    for requested_name in requested_names:
        value = _resolved_visible_value(
            values,
            requested_name,
            id_field_name=id_field_name,
        )
        if value is None:
            raise ParserDriftError(
                f"LinkedIn did not show an exact filter choice for {requested_name!r}; "
                f"use {id_field_name} instead."
            )
        resolved.append(value)
    return tuple(resolved)


async def _resolve_typeahead_names(
    page: Page,
    dialog: Locator,
    requested_names: tuple[str, ...],
    facet: _TypeaheadFacet,
) -> tuple[str, ...]:
    resolved: list[str] = []
    for requested_name in requested_names:
        visible_values = await _visible_facet_values(dialog, facet.input_name)
        value = _resolved_visible_value(
            visible_values,
            requested_name,
            id_field_name=facet.id_field_name,
        )
        if value is None:
            value = await _resolve_typeahead_name(page, dialog, requested_name, facet)
        resolved.append(value)
    return tuple(resolved)


async def _resolve_named_facets(
    page: Page,
    filters: JobSearchFilters,
) -> _ResolvedJobSearchFacets:
    all_filters = page.get_by_role(
        "button",
        name=re.compile(r"all filters", re.IGNORECASE),
    )
    try:
        await all_filters.first.wait_for(state="visible", timeout=20_000)
        await all_filters.first.click()
        dialog = page.get_by_role("dialog").first
        await dialog.wait_for(state="visible", timeout=10_000)
    except PlaywrightTimeoutError as error:
        raise ParserDriftError(
            "LinkedIn's visible All filters dialog was unavailable for name resolution."
        ) from error

    return _ResolvedJobSearchFacets(
        location_ids=await _resolve_visible_names(
            dialog,
            filters.location_names,
            input_name="location-filter-value",
            id_field_name="location_ids",
        ),
        company_ids=await _resolve_typeahead_names(
            page,
            dialog,
            filters.company_names,
            _COMPANY_FACET,
        ),
        industry_ids=await _resolve_typeahead_names(
            page,
            dialog,
            filters.industry_names,
            _INDUSTRY_FACET,
        ),
        job_function_ids=await _resolve_typeahead_names(
            page,
            dialog,
            filters.job_function_names,
            _JOB_FUNCTION_FACET,
        ),
        job_title_ids=await _resolve_visible_names(
            dialog,
            filters.job_title_names,
            input_name="title-filter-value",
            id_field_name="job_title_ids",
        ),
    )


class JobSearchPage:
    def __init__(self, playwright: LinkedInPlaywright, *, max_pages: int) -> None:
        if max_pages < 1:
            raise ValueError("Job search must allow at least one internal page.")
        self._playwright = playwright
        self._max_pages = max_pages

    @staticmethod
    def build_url(
        request: JobSearchInput,
        page_index: int = 0,
        *,
        resolved_facets: _ResolvedJobSearchFacets | None = None,
    ) -> str:
        parameters: dict[str, str | int] = {}
        if request.query:
            parameters["keywords"] = request.query
        if request.freshness_hours is not None:
            parameters["f_TPR"] = f"r{request.freshness_hours * 60 * 60}"
        if request.location:
            parameters["location"] = request.location
        _add_job_search_filters(parameters, request.filters, resolved_facets)
        if page_index:
            parameters["start"] = page_index * 25
        query = urlencode(parameters)
        suffix = f"?{query}" if query else ""
        return f"https://www.linkedin.com/jobs/search/{suffix}"

    async def collect(
        self,
        request: JobSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[JobSummary, ...], JobSearchCoverage, str, str]:
        limit = request.page_size if result_limit is None else result_limit
        if limit < 1:
            raise ValueError("Job search result limit must be positive.")
        jobs_by_id: dict[str, JobSummary] = {}
        page_texts: list[str] = []
        pages_visited = 0
        stop_reason = StopReason.SAFETY_BOUND
        advertised_result_count: int | None = None
        advertised_result_count_is_lower_bound = False
        resolved_facets = _ResolvedJobSearchFacets()
        async with self._playwright.page() as page:
            if _has_named_facets(request.filters):
                await page.goto(self.build_url(request))
                await _wait_for_job_search_state(page)
                resolved_facets = await _resolve_named_facets(page, request.filters)
            first_url = self.build_url(request, resolved_facets=resolved_facets)
            for page_index in range(self._max_pages):
                await page.goto(
                    self.build_url(request, page_index, resolved_facets=resolved_facets)
                )
                rendered_state = await _wait_for_job_search_state(page)
                pages_visited += 1
                if rendered_state is CollectionSettleOutcome.EXPLICIT_END:
                    page_texts.append(await self.extract_visible_text(page))
                    stop_reason = (
                        StopReason.NO_NEW_RESULTS
                        if not jobs_by_id
                        else StopReason.VISIBLE_PAGE_COMPLETE
                    )
                    break

                page_jobs = await self.extract_visible_jobs(page)
                if not page_jobs:
                    raise ParserDriftError(
                        "LinkedIn Jobs rendered result shells but no complete current job cards."
                    )
                current_count, current_is_lower_bound = await _job_search_result_count(page)
                if advertised_result_count is None and current_count is not None:
                    advertised_result_count = current_count
                    advertised_result_count_is_lower_bound = current_is_lower_bound

                added = 0
                retained_page_jobs: list[JobSummary] = []
                for job in page_jobs:
                    if job.job_id in jobs_by_id:
                        continue
                    jobs_by_id[job.job_id] = job
                    retained_page_jobs.append(job)
                    added += 1
                    if len(jobs_by_id) >= limit:
                        stop_reason = StopReason.RESULT_LIMIT
                        break
                header_text = await _job_search_header_text(page)
                page_texts.append(
                    "\n\n".join(
                        value
                        for value in (
                            header_text,
                            *(job.visible_text for job in retained_page_jobs),
                        )
                        if value
                    )
                )
                if len(jobs_by_id) >= limit:
                    break
                if not await _job_search_has_next_page(page):
                    stop_reason = (
                        StopReason.VISIBLE_PAGE_COMPLETE
                        if jobs_by_id
                        else StopReason.NO_NEW_RESULTS
                    )
                    break
                if added == 0:
                    continue
        captured_at = datetime.now(UTC)
        jobs = tuple(jobs_by_id.values())
        coverage = JobSearchCoverage(
            query=request.query,
            location=request.location,
            freshness_hours=request.freshness_hours,
            filters=request.filters,
            pages_visited=pages_visited,
            result_count=len(jobs),
            max_results=limit,
            stop_reason=stop_reason,
            advertised_result_count=advertised_result_count,
            advertised_result_count_is_lower_bound=advertised_result_count_is_lower_bound,
            captured_at=captured_at,
        )
        return jobs, coverage, "\n\n--- page boundary ---\n\n".join(page_texts), first_url

    @staticmethod
    async def extract_visible_text(page: Page) -> str:
        header = await _job_search_header_text(page)
        if header:
            return header
        main_text = await first_text(page.locator("main"))
        if main_text:
            return main_text
        raise ParserDriftError("LinkedIn job search returned no visible text.")

    @staticmethod
    async def extract_visible_jobs(page: Page) -> tuple[JobSummary, ...]:
        shells = page.locator("main li[data-occludable-job-id]")
        raw_ids = await shells.evaluate_all(
            "elements => elements.map(element => "
            "element.getAttribute('data-occludable-job-id')).filter(Boolean)"
        )
        job_ids = tuple(value for value in raw_ids if isinstance(value, str))
        if len(set(job_ids)) != len(job_ids):
            raise ParserDriftError("LinkedIn Jobs returned duplicate result-card identities.")

        results: dict[str, JobSummary] = {}
        for job_id in job_ids[:500]:
            if not re.fullmatch(r"[0-9]{5,30}", job_id):
                raise ParserDriftError("LinkedIn Jobs returned an invalid result-card identity.")
            card = page.locator(f'li[data-occludable-job-id="{job_id}"]')
            link = card.locator(f'a.job-card-list__title--link[href*="/jobs/view/{job_id}/"]')
            for _ in range(3):
                try:
                    await card.scroll_into_view_if_needed(timeout=_CARD_HYDRATION_TIMEOUT_MS)
                    await link.wait_for(
                        state="attached",
                        timeout=_CARD_HYDRATION_TIMEOUT_MS,
                    )
                    break
                except PlaywrightError:
                    card = page.locator(f'li[data-occludable-job-id="{job_id}"]')
                    link = card.locator(
                        f'a.job-card-list__title--link[href*="/jobs/view/{job_id}/"]'
                    )
            else:
                raise ParserDriftError(
                    f"LinkedIn Jobs did not hydrate visible result card {job_id}."
                )
            results[job_id] = await JobSearchPage._extract_job_card(
                card,
                link,
                job_id,
            )
        return tuple(results.values())

    @staticmethod
    async def _extract_job_card(
        card: Locator,
        link: Locator,
        job_id: str,
    ) -> JobSummary:
        href = await link.get_attribute("href")
        if not href or job_id_from_url(urljoin("https://www.linkedin.com", href)) != job_id:
            raise ParserDriftError("LinkedIn Jobs returned a mismatched result link.")

        visible_text = (await card.inner_text()).strip()
        title = await first_text(link.locator('span[aria-hidden="true"]'))
        aria_label = (await link.get_attribute("aria-label") or "").strip()
        if not title and aria_label:
            title = re.sub(r"\s+with verification$", "", aria_label, flags=re.I).strip()
        if not title or not visible_text:
            raise ParserDriftError(
                "LinkedIn Jobs returned a result card without visible title content."
            )

        company_container = card.locator(".artdeco-entity-lockup__subtitle")
        company_name = await first_text(company_container)
        location_text = await first_text(card.locator(".artdeco-entity-lockup__caption"))
        if not location_text:
            raise ParserDriftError(
                f"LinkedIn Jobs result card {job_id} did not hydrate its visible location field."
            )
        company_href = await first_href(company_container.locator('a[href*="/company/"]'))
        company_url = (
            HttpUrl(urljoin("https://www.linkedin.com", company_href)) if company_href else None
        )
        location, workplace_type = _location_and_workplace(visible_text_lines(location_text)[0])

        core_values = {title, aria_label, company_name, location_text}
        insights = tuple(
            line for line in visible_text_lines(visible_text) if line not in core_values
        )
        listed_at_text = first_pattern_text(list(insights), LISTED_PATTERN)
        easy_apply = any(line.casefold() == "easy apply" for line in insights)
        verified = bool(aria_label and aria_label.casefold().endswith(" with verification"))
        promoted = any(line.casefold().startswith("promoted") for line in insights)

        evidence_values: list[tuple[str, str | None]] = [
            ("title", title),
            ("company_name", company_name),
            ("location", location),
            (
                "workplace_type",
                WORKPLACE_LABELS.get(workplace_type.value) if workplace_type is not None else None,
            ),
            ("listed_at_text", listed_at_text),
            ("easy_apply", "Easy Apply" if easy_apply else None),
            ("verified", aria_label if verified else None),
            (
                "promoted",
                next(
                    (line for line in insights if line.casefold().startswith("promoted")),
                    None,
                ),
            ),
        ]
        evidence_values.extend(
            (f"insights.{index}", insight) for index, insight in enumerate(insights)
        )
        evidence = tuple(
            EvidenceField(field=field, quote=value)
            for field, value in evidence_values
            if value and value in visible_text
        )
        return JobSummary(
            job_id=job_id,
            job_url=HttpUrl(canonical_job_url(job_id)),
            title=title,
            company_name=company_name,
            company_url=company_url,
            location=location,
            workplace_type=workplace_type,
            listed_at_text=listed_at_text,
            easy_apply=easy_apply,
            verified=verified,
            promoted=promoted,
            insights=insights,
            visible_text=visible_text,
            evidence=evidence,
        )
