"""Bounded LinkedIn Jobs search and detail page objects."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode, urljoin

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import HttpUrl

from linkedin_mcp.browser.convergence import CollectionSettleOutcome
from linkedin_mcp.browser.manager import BrowserManager
from linkedin_mcp.domain.models import (
    EvidenceField,
    JobApplyMethod,
    JobBenefit,
    JobCommitment,
    JobDetailInput,
    JobDetailObservation,
    JobEmploymentType,
    JobExperienceLevel,
    JobHiringTeamMember,
    JobSearchCoverage,
    JobSearchFilters,
    JobSearchInput,
    JobSearchSort,
    JobSummary,
    JobWorkplaceType,
    StopReason,
)
from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.policy import (
    canonical_job_url,
    canonical_profile_url,
    job_id_from_url,
    profile_slug_from_url,
)

_LISTED_PATTERN = re.compile(
    r"\b(?:reposted\s+)?(?:\d+\s+)?(?:minute|hour|day|week|month)s?\s+ago\b|\breposted\b",
    re.IGNORECASE,
)
_EMPLOYMENT_TYPES = (
    "Full-time",
    "Part-time",
    "Contract",
    "Temporary",
    "Internship",
    "Volunteer",
    "Other",
)
_WORKPLACE_TYPES = ("Remote", "Hybrid", "On-site")
_WORKPLACE_VALUES = {
    "remote": JobWorkplaceType.REMOTE,
    "hybrid": JobWorkplaceType.HYBRID,
    "on-site": JobWorkplaceType.ON_SITE,
}
_WORKPLACE_LABELS = {value: label for label, value in _WORKPLACE_VALUES.items()}
_WORKPLACE_SUFFIX_PATTERN = re.compile(
    r"^(?P<location>.+?)\s+\((?P<workplace>Remote|Hybrid|On-site)\)$",
    re.IGNORECASE,
)
_APPLICANT_PATTERN = re.compile(
    r"\b(?:(?:over|under)\s+)?[\d,.+]+\s+(?:applicants?|people clicked apply)\b",
    re.IGNORECASE,
)
_DETAIL_ACTION_LINES = frozenset({"apply", "save", "easy apply"})
_DETAIL_NOISE_PREFIXES = (
    "promoted by",
    "responses managed",
    "use ai to",
    "get ai-powered",
    "show match details",
    "tailor my resume",
    "help me stand out",
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
_CONNECTION_DEGREE_PATTERN = re.compile(r"^[•·]?\s*(?:1st|2nd|3rd|\d+(?:st|nd|rd|th))$", re.I)


async def _job_search_has_explicit_end(page: Page) -> bool:
    main = page.locator("main")
    if await main.count() == 0:
        return False
    text = (await main.first.inner_text()).strip()
    lines = _lines(text)
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


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


async def _first_text(locator: Locator) -> str | None:
    if await locator.count() == 0:
        return None
    value = (await locator.first.inner_text()).strip()
    return value or None


async def _first_href(locator: Locator) -> str | None:
    if await locator.count() == 0:
        return None
    value = await locator.first.get_attribute("href")
    return value.strip() if value and value.strip() else None


def _first_pattern_text(lines: list[str], pattern: re.Pattern[str]) -> str | None:
    for line in lines:
        match = pattern.search(line)
        if match:
            return match.group(0).strip()
    return None


def _metadata_location(lines: list[str]) -> str | None:
    for line in lines[:12]:
        match = _LISTED_PATTERN.search(line)
        if match is None:
            continue
        candidate = line[: match.start()].strip(" \t·•")
        if candidate:
            return candidate
    return None


def _fallback_location(
    lines: list[str],
    *,
    excluded: set[str | None],
) -> str | None:
    exact_noise = {
        *(value.casefold() for value in _EMPLOYMENT_TYPES),
        *(value.casefold() for value in _WORKPLACE_TYPES),
        *_DETAIL_ACTION_LINES,
    }
    for line in lines[:12]:
        lowered = line.casefold()
        if (
            line in excluded
            or lowered in exact_noise
            or _LISTED_PATTERN.search(line)
            or _APPLICANT_PATTERN.search(line)
            or lowered == "about the job"
            or any(lowered.startswith(prefix) for prefix in _DETAIL_NOISE_PREFIXES)
        ):
            continue
        return line
    return None


def _location_and_workplace(value: str) -> tuple[str, JobWorkplaceType | None]:
    match = _WORKPLACE_SUFFIX_PATTERN.fullmatch(value)
    if match is None:
        return value, None
    return (
        match.group("location").strip(),
        _WORKPLACE_VALUES[match.group("workplace").casefold()],
    )


def _visible_workplace(lines: list[str]) -> JobWorkplaceType | None:
    for line in lines:
        value = _WORKPLACE_VALUES.get(line.casefold())
        if value is not None:
            return value
    return None


async def _job_search_result_count(page: Page) -> tuple[int | None, bool]:
    header = page.locator("main .scaffold-layout__list-header").first
    text = await _first_text(header)
    if text is None:
        text = await _first_text(page.locator("main"))
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
    return await _first_text(page.locator("main .scaffold-layout__list-header"))


async def _job_top_card(main: Locator, job_id: str) -> Locator:
    save_control = main.get_by_role(
        "button",
        name=re.compile(r"^save (?:the )?job$", re.I),
    ).first
    if await save_control.count() == 0:
        raise ParserDriftError("LinkedIn job detail has no identifiable primary job card.")
    candidate = save_control
    for _ in range(8):
        candidate = candidate.locator("..")
        attribute_links = candidate.locator(f'a[href="{canonical_job_url(job_id)}"]')
        if await attribute_links.count() > 0:
            return candidate
    raise ParserDriftError("LinkedIn job detail has no identifiable primary job card.")


async def _about_job_container(main: Locator) -> tuple[Locator, Locator]:
    about_heading = main.get_by_role(
        "heading",
        name=re.compile(r"^about the job$", re.I),
    ).first
    if await about_heading.count() == 0:
        raise ParserDriftError("LinkedIn job detail has no visible About the job section.")
    container = about_heading
    for _ in range(5):
        container = container.locator("..")
        boxes = container.locator('[data-testid="expandable-text-box"]')
        if await boxes.count() > 0:
            return container, boxes.first
    raise ParserDriftError("LinkedIn job detail has no current expandable About the job content.")


async def _visible_hiring_team(
    main: Locator,
) -> tuple[tuple[JobHiringTeamMember, ...], str | None]:
    marker = main.get_by_text("Meet the hiring team", exact=True)
    if await marker.count() == 0:
        return (), None
    container = marker.first.locator("..")
    section_text = (await container.inner_text()).strip()
    if not section_text:
        return (), None

    links = container.locator('a[href*="/in/"]')
    links_by_slug: dict[str, list[Locator]] = {}
    for index in range(await links.count()):
        link = links.nth(index)
        href = await link.get_attribute("href")
        if not href:
            continue
        absolute_href = urljoin("https://www.linkedin.com", href)
        profile_slug = profile_slug_from_url(absolute_href)
        if profile_slug:
            links_by_slug.setdefault(profile_slug, []).append(link)

    members: list[JobHiringTeamMember] = []
    for profile_slug, matching_links in links_by_slug.items():
        visible_values = [
            (await link.inner_text()).strip() for link in matching_links if await link.is_visible()
        ]
        visible_values = [value for value in visible_values if value]
        if not visible_values:
            continue
        visible_text = max(visible_values, key=len).strip(" \x7f")
        lines = [line.strip(" \x7f") for line in _lines(visible_text)]
        name_candidates = [
            candidate_lines[0].strip(" \x7f")
            for value in visible_values
            if (candidate_lines := _lines(value))
        ]
        if not name_candidates:
            continue
        name = min(name_candidates, key=len)
        connection_degree_text = next(
            (line for line in lines if _CONNECTION_DEGREE_PATTERN.fullmatch(line)),
            None,
        )
        mutual_connections_text = next(
            (line for line in lines if "mutual connection" in line.casefold()),
            None,
        )
        role_text = next(
            (
                line
                for line in lines
                if line.casefold() in {"job poster", "hiring manager", "recruiter"}
            ),
            None,
        )
        headline = next(
            (
                line
                for line in lines
                if line
                not in {
                    name,
                    connection_degree_text,
                    mutual_connections_text,
                    role_text,
                    "Message",
                }
            ),
            None,
        )
        members.append(
            JobHiringTeamMember(
                profile_slug=profile_slug,
                profile_url=HttpUrl(canonical_profile_url(profile_slug)),
                name=name,
                headline=headline,
                connection_degree_text=connection_degree_text,
                role_text=role_text,
                mutual_connections_text=mutual_connections_text,
                visible_text=visible_text,
            )
        )
    return tuple(members), section_text


async def _visible_job_title(
    page: Page,
    main: Locator,
    *,
    visible_text: str,
    company_name: str | None,
) -> str:
    semantic_title = await _first_text(main.get_by_role("heading", level=1))
    if semantic_title:
        semantic_lines = _lines(semantic_title)
        if semantic_lines and all(line == semantic_lines[0] for line in semantic_lines):
            return semantic_lines[0]
        return semantic_title

    visible_lines = _lines(visible_text)
    document_title = (await page.title()).strip()
    linkedin_suffix = " | LinkedIn"
    if document_title.endswith(linkedin_suffix):
        title_and_company = document_title[: -len(linkedin_suffix)]
        if company_name:
            company_suffix = f" | {company_name}"
            if title_and_company.endswith(company_suffix):
                title_and_company = title_and_company[: -len(company_suffix)]
        candidate = title_and_company.strip()
        if candidate and candidate in visible_lines:
            return candidate

    if company_name:
        for index, line in enumerate(visible_lines[:-1]):
            if line != company_name:
                continue
            candidate = visible_lines[index + 1]
            if candidate and len(candidate) <= 500:
                return candidate

    raise ParserDriftError("LinkedIn job detail has no confidently identifiable visible title.")


async def _visible_description(description_box: Locator) -> str:
    description = (await description_box.inner_text()).strip()
    description = re.sub(r"\s*(?:…|\.\.\.)\s*more\s*$", "", description, flags=re.I).strip()
    if not description:
        raise ParserDriftError("LinkedIn job detail has an empty About the job description.")
    return description


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
    def __init__(self, browser: BrowserManager, *, max_pages: int) -> None:
        if max_pages < 1:
            raise ValueError("Job search must allow at least one internal page.")
        self._browser = browser
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
        async with self._browser.page() as page:
            if _has_named_facets(request.filters):
                await self._browser.navigate(page, self.build_url(request))
                await _wait_for_job_search_state(page)
                resolved_facets = await _resolve_named_facets(page, request.filters)
            first_url = self.build_url(request, resolved_facets=resolved_facets)
            for page_index in range(self._max_pages):
                await self._browser.navigate(
                    page,
                    self.build_url(
                        request,
                        page_index,
                        resolved_facets=resolved_facets,
                    ),
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
        main_text = await _first_text(page.locator("main"))
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
        title = await _first_text(link.locator('span[aria-hidden="true"]'))
        aria_label = (await link.get_attribute("aria-label") or "").strip()
        if not title and aria_label:
            title = re.sub(r"\s+with verification$", "", aria_label, flags=re.I).strip()
        if not title or not visible_text:
            raise ParserDriftError(
                "LinkedIn Jobs returned a result card without visible title content."
            )

        company_container = card.locator(".artdeco-entity-lockup__subtitle")
        company_name = await _first_text(company_container)
        location_text = await _first_text(card.locator(".artdeco-entity-lockup__caption"))
        if not location_text:
            raise ParserDriftError(
                f"LinkedIn Jobs result card {job_id} did not hydrate its visible location field."
            )
        company_href = await _first_href(company_container.locator('a[href*="/company/"]'))
        company_url = (
            HttpUrl(urljoin("https://www.linkedin.com", company_href)) if company_href else None
        )
        location, workplace_type = _location_and_workplace(_lines(location_text)[0])

        core_values = {title, aria_label, company_name, location_text}
        insights = tuple(line for line in _lines(visible_text) if line not in core_values)
        listed_at_text = _first_pattern_text(list(insights), _LISTED_PATTERN)
        easy_apply = any(line.casefold() == "easy apply" for line in insights)
        verified = bool(aria_label and aria_label.casefold().endswith(" with verification"))
        promoted = any(line.casefold().startswith("promoted") for line in insights)

        evidence_values: list[tuple[str, str | None]] = [
            ("title", title),
            ("company_name", company_name),
            ("location", location),
            (
                "workplace_type",
                _WORKPLACE_LABELS.get(workplace_type) if workplace_type is not None else None,
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


class JobDetailPage:
    def __init__(self, browser: BrowserManager) -> None:
        self._browser = browser

    async def read(self, request: JobDetailInput) -> JobDetailObservation:
        async with self._browser.page() as page:
            await self._browser.navigate(page, canonical_job_url(request.job_id))
            await self._wait_until_ready(page, request.job_id)
            await self._expand_description(page)
            return await self.extract_visible_job(page, request.job_id)

    @staticmethod
    async def _wait_until_ready(page: Page, job_id: str) -> None:
        main = page.locator("main")
        about_heading = main.get_by_role(
            "heading",
            name=re.compile(r"^about the job$", re.I),
        )
        save_control = main.get_by_role(
            "button",
            name=re.compile(r"^save (?:the )?job$", re.I),
        )
        try:
            await main.first.wait_for(state="visible")
            await about_heading.first.wait_for(state="visible")
            await save_control.first.wait_for(state="visible")
            await main.locator(f'a[href="{canonical_job_url(job_id)}"]').first.wait_for(
                state="visible"
            )
            await main.locator('[data-testid="expandable-text-box"]').first.wait_for(
                state="visible"
            )
        except PlaywrightTimeoutError as error:
            raise ParserDriftError(
                "LinkedIn job detail did not render its visible About the job section."
            ) from error

    async def _expand_description(self, page: Page) -> None:
        main = page.locator("main").first
        _, description_box = await _about_job_container(main)
        expand_button = description_box.locator('[data-testid="expandable-text-button"]')
        if await expand_button.count() == 0:
            return
        before_height = await description_box.evaluate(
            "element => element.getBoundingClientRect().height"
        )
        spans = expand_button.locator("span")
        click_target = spans.last if await spans.count() > 0 else expand_button
        try:
            await self._browser.click_visible_control(page, click_target)
        except PlaywrightError as error:
            raise ParserDriftError(
                "LinkedIn job detail exposed its description expansion control "
                "but it could not be activated."
            ) from error

        for _ in range(20):
            if await expand_button.count() == 0:
                return
            current_height = await description_box.evaluate(
                "element => element.getBoundingClientRect().height"
            )
            if current_height > before_height:
                return
            await page.wait_for_timeout(100)
        raise ParserDriftError(
            "LinkedIn job detail did not visibly expand its About the job description."
        )

    @staticmethod
    async def extract_visible_job(page: Page, job_id: str) -> JobDetailObservation:
        main = page.locator("main").first
        if await main.count() == 0:
            raise ParserDriftError("LinkedIn job detail returned no visible text.")

        top_card = await _job_top_card(main, job_id)
        top_text = (await top_card.inner_text()).strip()
        if not top_text:
            raise ParserDriftError("LinkedIn job detail returned an empty primary job card.")
        company_link = top_card.locator('a[href*="/company/"]')
        company_name = await _first_text(company_link)
        company_href = await _first_href(company_link)
        company_url = (
            HttpUrl(urljoin("https://www.linkedin.com", company_href)) if company_href else None
        )

        lines = _lines(top_text)
        title = await _visible_job_title(
            page,
            top_card,
            visible_text=top_text,
            company_name=company_name,
        )
        attribute_lines: list[str] = []
        attribute_links = top_card.locator(f'a[href="{canonical_job_url(job_id)}"]')
        for index in range(await attribute_links.count()):
            attribute_lines.extend(_lines(await attribute_links.nth(index).inner_text()))
        semantic_lines = [*lines, *attribute_lines]

        listed_at_text = _first_pattern_text(lines, _LISTED_PATTERN)
        applicant_text = _first_pattern_text(lines, _APPLICANT_PATTERN)
        employment_type = next(
            (
                value
                for value in _EMPLOYMENT_TYPES
                if any(line.casefold() == value.casefold() for line in semantic_lines[:20])
            ),
            None,
        )
        workplace_type = _visible_workplace(semantic_lines[:20])

        excluded = {title, company_name, listed_at_text, applicant_text, employment_type}
        location = _metadata_location(lines) or _fallback_location(lines, excluded=excluded)

        easy_apply_control = top_card.get_by_role(
            "link",
            name=re.compile(r"easy apply", re.I),
        )
        if await easy_apply_control.count() == 0:
            easy_apply_control = top_card.get_by_role(
                "button",
                name=re.compile(r"easy apply", re.I),
            )
        external_apply_control = top_card.get_by_role(
            "button",
            name=re.compile(r"^apply(?: on company website)?$", re.I),
        )
        if await easy_apply_control.count() > 0:
            apply_method = JobApplyMethod.EASY_APPLY
            application_quote = "Easy Apply"
        elif await external_apply_control.count() > 0:
            apply_method = JobApplyMethod.EXTERNAL
            application_quote = "Apply"
        else:
            apply_method = JobApplyMethod.UNAVAILABLE
            application_quote = None

        metadata_line = next(
            (
                line
                for line in lines
                if _LISTED_PATTERN.search(line) or _APPLICANT_PATTERN.search(line)
            ),
            None,
        )
        excluded_lines = {
            title,
            company_name,
            metadata_line,
            employment_type,
            *(_WORKPLACE_TYPES),
            "Easy Apply",
            "Apply",
            "Save",
        }
        insights = tuple(line for line in lines if line not in excluded_lines)
        promoted = any(line.casefold().startswith("promoted") for line in insights)

        _, description_box = await _about_job_container(main)
        description_text = await _visible_description(description_box)
        hiring_team, hiring_team_text = await _visible_hiring_team(main)
        visible_text = "\n\n".join(
            value
            for value in (
                top_text,
                hiring_team_text,
                f"About the job\n\n{description_text}",
            )
            if value
        )

        evidence_values: list[tuple[str, str | None]] = [
            ("title", title),
            ("company_name", company_name),
            ("location", location),
            (
                "workplace_type",
                _WORKPLACE_LABELS.get(workplace_type) if workplace_type is not None else None,
            ),
            ("employment_type", employment_type),
            ("listed_at_text", listed_at_text),
            ("applicant_text", applicant_text),
            ("description_text", description_text),
            ("apply_method", application_quote),
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
        for index, member in enumerate(hiring_team):
            evidence_values.append((f"hiring_team.{index}.name", member.name))
            if member.headline:
                evidence_values.append((f"hiring_team.{index}.headline", member.headline))
        evidence = tuple(
            EvidenceField(field=field, quote=value)
            for field, value in evidence_values
            if value and value in visible_text
        )
        return JobDetailObservation(
            job_id=job_id,
            job_url=HttpUrl(canonical_job_url(job_id)),
            title=title,
            company_name=company_name,
            company_url=company_url,
            location=location,
            workplace_type=workplace_type,
            employment_type=employment_type,
            listed_at_text=listed_at_text,
            applicant_text=applicant_text,
            description_text=description_text,
            apply_method=apply_method,
            easy_apply=apply_method is JobApplyMethod.EASY_APPLY,
            promoted=promoted,
            insights=insights,
            hiring_team=hiring_team,
            visible_text=visible_text,
            evidence=evidence,
            captured_at=datetime.now(UTC),
        )
