"""Bounded LinkedIn People search and member-profile page objects."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import HttpUrl

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools._shared.browser import BrowserManager
from linkedin_mcp.tools._shared.collections import (
    CollectionSettleOutcome,
    visible_locator_signature,
    wait_for_collection_initial_state,
)
from linkedin_mcp.tools._shared.identifiers import PROFILE_SLUG_SEGMENT_PATTERN
from linkedin_mcp.tools._shared.models import StopReason
from linkedin_mcp.tools._shared.urls import canonical_profile_url, profile_slug_from_url
from linkedin_mcp.tools.people._shared.models import (
    PeopleGetInput,
    PeopleSearchConnectionDegree,
    PeopleSearchCoverage,
    PeopleSearchFilters,
    PeopleSearchInput,
    PersonConnectionDegree,
    PersonEducation,
    PersonExperience,
    PersonProfileCoverage,
    PersonProfileEvidence,
    PersonProfileLink,
    PersonProfileObservation,
    PersonProfilePageCapture,
    PersonProfileSection,
    PersonProfileSectionEntry,
    PersonProfileSectionSelector,
    PersonSummary,
)

_CONNECTION_FILTER_CODES = {
    PeopleSearchConnectionDegree.FIRST: "F",
    PeopleSearchConnectionDegree.SECOND: "S",
    PeopleSearchConnectionDegree.THIRD_OR_MORE: "O",
}
_CONNECTION_DEGREE_PATTERN = re.compile(r"\b(1st|2nd|3rd)\b", re.IGNORECASE)
_CONNECTION_COUNT_PATTERN = re.compile(
    r"\b(?:[\d,.+]+|500\+)\s+connections?\b",
    re.IGNORECASE,
)
_FOLLOWER_COUNT_PATTERN = re.compile(r"\b[\d,.+]+\s+followers?\b", re.IGNORECASE)
_MUTUAL_PATTERN = re.compile(r"\bmutual connections?\b", re.IGNORECASE)
_DATE_RANGE_PATTERN = re.compile(
    r"\b(?:19|20)\d{2}\b|\bPresent\b|\b(?:\d+\s+)?(?:mos?|yrs?)\b",
    re.IGNORECASE,
)
_EMPLOYMENT_TYPE_LINES = frozenset(
    {
        "apprenticeship",
        "contract",
        "freelance",
        "full-time",
        "internship",
        "part-time",
        "seasonal",
        "self-employed",
        "temporary",
        "volunteer",
    }
)
_SKILL_ACTION_PATTERN = re.compile(
    r"^(?:endorse|remove endorsement for|unendorse)\s+(.+)$",
    re.IGNORECASE,
)
_PROFILE_DETAIL_PATH = re.compile(
    rf"^/in/(?P<slug>{PROFILE_SLUG_SEGMENT_PATTERN})/"
    r"details/(?P<section>[A-Za-z0-9_-]+)/?"
)
_PEOPLE_SEARCH_END_PATTERN = re.compile(
    r"^(?:no (?:matching )?(?:people|results)(?: found| to show)?|"
    r"we couldn(?:'|\N{RIGHT SINGLE QUOTATION MARK})t find any results)"
    r"(?:[.!])?$",
    re.IGNORECASE,
)
_INITIAL_RESULTS_POLL_ATTEMPTS = 20
_INITIAL_RESULTS_POLL_DELAY_MS = 250
_DETAIL_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "experience": ("experience",),
    "education": ("education",),
    "certifications": ("licenses & certifications", "certifications"),
    "projects": ("projects",),
    "volunteering-experiences": ("volunteering", "volunteer experience"),
    "skills": ("skills",),
    "interests": ("interests",),
    "featured": ("featured",),
    "courses": ("courses",),
    "honors": ("honors & awards", "honors"),
    "languages": ("languages",),
    "organizations": ("organizations",),
    "publications": ("publications",),
    "patents": ("patents",),
    "recommendations": ("recommendations",),
    "test-scores": ("test scores",),
}
_CANONICAL_DETAIL_SECTION_KEYS = {
    "certifications": "licenses-certifications",
    "honors": "honors-awards",
    "volunteering-experiences": "volunteering",
}
_CANONICAL_HEADING_SECTION_KEYS = {
    "volunteer-experience": "volunteering",
}
_ACTION_LINES = frozenset(
    {
        "connect",
        "follow",
        "message",
        "more",
        "pending",
        "view profile",
        "contact info",
        "show all",
        "see more",
    }
)
_AUXILIARY_PROFILE_SECTION_KEYS = frozenset(
    {
        "analytics",
        "explore-premium-profiles",
        "guidance",
        "more-profiles-for-you",
        "people-you-may-know",
        "profile-language",
        "public-profile-url",
        "resources",
        "suggested-for-you",
        "who-your-viewers-also-viewed",
        "you-might-like",
    }
)


async def _people_search_has_explicit_end(page: Page) -> bool:
    main = page.locator("main")
    if await main.count() == 0:
        return False
    text = (await main.first.inner_text()).strip()
    return any(
        _PEOPLE_SEARCH_END_PATTERN.fullmatch(line.strip())
        for line in text.splitlines()
        if line.strip()
    )


async def _unidentifiable_people_result_count(page: Page) -> int:
    """Count current visible result cards whose identity LinkedIn withholds."""

    value = await page.locator("main").first.evaluate(
        """
        root => Array.from(root.querySelectorAll('[role="listitem"]'))
          .filter(element => element.getClientRects().length > 0)
          .filter(element => {
            const lines = (element.innerText || "")
              .split(/\\n+/)
              .map(line => line.trim())
              .filter(Boolean);
            return lines[0]?.toLowerCase() === "linkedin member" &&
              !element.querySelector('a[href*="/in/"]') &&
              element.querySelector("img");
          })
          .length
        """
    )
    if not isinstance(value, int):
        raise ParserDriftError("LinkedIn returned an invalid anonymous People-result count.")
    return value


async def _wait_for_people_search_state(page: Page) -> CollectionSettleOutcome:
    async def read_signature() -> tuple[str, ...]:
        return await visible_locator_signature(
            page.locator('main [role="listitem"] a[href*="/in/"]'),
            identity_attributes=("href",),
        )

    async def read_explicit_end() -> bool:
        return (
            await _people_search_has_explicit_end(page)
            or await _unidentifiable_people_result_count(page) > 0
        )

    result = await wait_for_collection_initial_state(
        page,
        read_signature=read_signature,
        read_explicit_end=read_explicit_end,
        attempts=_INITIAL_RESULTS_POLL_ATTEMPTS,
        delay_ms=_INITIAL_RESULTS_POLL_DELAY_MS,
    )
    return result.outcome


@dataclass(frozen=True, slots=True)
class _ResolvedPeopleSearchFacets:
    actively_hiring_job_title_ids: tuple[str, ...] = ()
    location_ids: tuple[str, ...] = ()
    current_company_ids: tuple[str, ...] = ()
    connections_of_ids: tuple[str, ...] = ()
    followers_of_ids: tuple[str, ...] = ()
    past_company_ids: tuple[str, ...] = ()
    school_ids: tuple[str, ...] = ()
    industry_ids: tuple[str, ...] = ()
    profile_language_ids: tuple[str, ...] = ()
    service_category_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _TypeaheadFacet:
    input_name: str
    section_headings: tuple[str, ...]
    add_button_names: tuple[str, ...]
    option_kinds: tuple[str, ...]
    id_field_name: str


_LOCATION_FACET = _TypeaheadFacet(
    input_name="geoUrn-filter-value",
    section_headings=("Locations",),
    add_button_names=("Add a location",),
    option_kinds=("Location",),
    id_field_name="location_ids",
)
_CURRENT_COMPANY_FACET = _TypeaheadFacet(
    input_name="currentCompany-filter-value",
    section_headings=("Current companies", "Current company"),
    add_button_names=("Add a company",),
    option_kinds=("Company",),
    id_field_name="current_company_ids",
)
_CONNECTIONS_OF_FACET = _TypeaheadFacet(
    input_name="connectionsOf-filter-value",
    section_headings=("Connections of",),
    add_button_names=("Add a connection", "Add a person"),
    option_kinds=("Member", "Person"),
    id_field_name="connections_of_ids",
)
_FOLLOWERS_OF_FACET = _TypeaheadFacet(
    input_name="followersOf-filter-value",
    section_headings=("Followers of",),
    add_button_names=("Add a creator", "Add a person"),
    option_kinds=("Member", "Person"),
    id_field_name="followers_of_ids",
)
_PAST_COMPANY_FACET = _TypeaheadFacet(
    input_name="pastCompany-filter-value",
    section_headings=("Past companies", "Past company"),
    add_button_names=("Add a past company", "Add a company"),
    option_kinds=("Company",),
    id_field_name="past_company_ids",
)
_SCHOOL_FACET = _TypeaheadFacet(
    input_name="schoolFilter-filter-value",
    section_headings=("Schools", "School"),
    add_button_names=("Add a school",),
    option_kinds=("School",),
    id_field_name="school_ids",
)
_INDUSTRY_FACET = _TypeaheadFacet(
    input_name="industry-filter-value",
    section_headings=("Industries", "Industry"),
    add_button_names=("Add an industry",),
    option_kinds=("Industry",),
    id_field_name="industry_ids",
)
_ACTIVELY_HIRING_JOB_TITLE_FACET = _TypeaheadFacet(
    input_name="activelyHiringForJobTitles-filter-value",
    section_headings=("Actively hiring",),
    add_button_names=("Hiring for job title",),
    option_kinds=("Job title",),
    id_field_name="actively_hiring_job_title_ids",
)
_SERVICE_CATEGORY_FACET = _TypeaheadFacet(
    input_name="serviceCategory-filter-value",
    section_headings=("Service categories", "Services"),
    add_button_names=("Add a service", "Add a service category"),
    option_kinds=("Service", "Service category"),
    id_field_name="service_category_ids",
)


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _unique_lines(text: str) -> list[str]:
    values: list[str] = []
    for line in _lines(text):
        if values and values[-1] == line:
            continue
        values.append(line)
    return values


async def _first_text(locator: Locator) -> str | None:
    if await locator.count() == 0:
        return None
    value = (await locator.first.inner_text()).strip()
    return value or None


def _json_list(values: tuple[str, ...]) -> str:
    return json.dumps(list(values), separators=(",", ":"))


def _merge_values(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for group in groups for value in group))


def _add_people_search_filters(
    parameters: dict[str, str | int],
    filters: PeopleSearchFilters,
    resolved_facets: _ResolvedPeopleSearchFacets | None = None,
) -> None:
    resolved = resolved_facets or _ResolvedPeopleSearchFacets()
    if filters.connection_degrees:
        parameters["network"] = _json_list(
            tuple(_CONNECTION_FILTER_CODES[value] for value in filters.connection_degrees)
        )
    for parameter_name, values in (
        (
            "activelyHiringForJobTitles",
            _merge_values(
                filters.actively_hiring_job_title_ids,
                resolved.actively_hiring_job_title_ids,
            ),
        ),
        ("geoUrn", _merge_values(filters.location_ids, resolved.location_ids)),
        (
            "currentCompany",
            _merge_values(filters.current_company_ids, resolved.current_company_ids),
        ),
        (
            "connectionOf",
            _merge_values(filters.connections_of_ids, resolved.connections_of_ids),
        ),
        (
            "followerOf",
            _merge_values(filters.followers_of_ids, resolved.followers_of_ids),
        ),
        (
            "pastCompany",
            _merge_values(filters.past_company_ids, resolved.past_company_ids),
        ),
        ("schoolFilter", _merge_values(filters.school_ids, resolved.school_ids)),
        ("industry", _merge_values(filters.industry_ids, resolved.industry_ids)),
        (
            "profileLanguage",
            _merge_values(filters.profile_language_ids, resolved.profile_language_ids),
        ),
        (
            "serviceCategory",
            _merge_values(filters.service_category_ids, resolved.service_category_ids),
        ),
    ):
        if values:
            parameters[parameter_name] = _json_list(values)
    for parameter_name, value in (
        ("firstName", filters.first_name),
        ("lastName", filters.last_name),
        ("title", filters.title),
        ("company", filters.company),
        ("schoolFreetext", filters.school),
    ):
        if value:
            parameters[parameter_name] = value


def _requires_visible_filter_resolution(filters: PeopleSearchFilters) -> bool:
    return any(
        (
            filters.actively_hiring_job_title_names,
            filters.location_names,
            filters.current_company_names,
            filters.connections_of_names,
            filters.followers_of_names,
            filters.past_company_names,
            filters.school_names,
            filters.industry_names,
            filters.profile_language_names,
            filters.service_category_names,
            filters.actively_hiring,
        )
    )


def _typeahead_option_label(option_text: str, option_kinds: tuple[str, ...]) -> str:
    lines = _lines(option_text)
    if not lines:
        return ""
    label = re.split(r"\s+[•·]\s+", " ".join(lines[0].split()), maxsplit=1)[0]
    for option_kind in option_kinds:
        suffix = f" {option_kind}"
        if label.casefold().endswith(suffix.casefold()):
            return label[: -len(suffix)].strip()
    return label


def _button_name_pattern(names: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(name) for name in names)
    return re.compile(rf"^(?:{alternatives})$", re.IGNORECASE)


async def _modern_filter_panel(page: Page) -> Locator | None:
    headings = page.get_by_text("People filters", exact=True)
    for heading_index in range(await headings.count()):
        heading = headings.nth(heading_index)
        if not await heading.is_visible():
            continue
        asides = page.locator("aside")
        for aside_index in range(await asides.count()):
            aside = asides.nth(aside_index)
            if await aside.get_by_text("People filters", exact=True).count():
                return aside
        region = heading
        for _ in range(8):
            region = region.locator("..")
            if await region.get_by_text("Show results", exact=True).count():
                return region
    return None


async def _exact_modern_checkbox(
    panel: Locator,
    requested_name: str,
    *,
    id_field_name: str,
) -> Locator | None:
    pattern = re.compile(rf"^{re.escape(' '.join(requested_name.split()))}$", re.IGNORECASE)
    candidates = panel.get_by_role("checkbox", name=pattern)
    visible: list[Locator] = []
    for index in range(await candidates.count()):
        candidate = candidates.nth(index)
        if await candidate.is_visible():
            visible.append(candidate)
    if len(visible) > 1:
        raise ParserDriftError(
            f"LinkedIn returned multiple exact matches for {requested_name!r}; "
            f"use {id_field_name} to disambiguate."
        )
    return visible[0] if visible else None


async def _check_modern_names(
    panel: Locator,
    requested_names: tuple[str, ...],
    *,
    id_field_name: str,
    section_headings: tuple[str, ...] = (),
    force_reapply: bool = False,
) -> None:
    for requested_name in requested_names:
        region = (
            await _modern_checkbox_region(
                panel,
                section_headings=section_headings,
                requested_name=requested_name,
                id_field_name=id_field_name,
            )
            if section_headings
            else panel
        )
        checkbox = await _exact_modern_checkbox(
            region,
            requested_name,
            id_field_name=id_field_name,
        )
        if checkbox is None:
            raise ParserDriftError(
                f"LinkedIn did not show an exact filter choice for {requested_name!r}; "
                f"use {id_field_name} instead."
            )
        if force_reapply and await checkbox.is_checked():
            await checkbox.uncheck()
            await panel.page.wait_for_timeout(200)
        if not await checkbox.is_checked():
            await checkbox.check()
            await panel.page.wait_for_timeout(200)


async def _modern_checkbox_region(
    panel: Locator,
    *,
    section_headings: tuple[str, ...],
    requested_name: str,
    id_field_name: str,
) -> Locator:
    checkbox_pattern = re.compile(
        rf"^{re.escape(' '.join(requested_name.split()))}$",
        re.IGNORECASE,
    )
    for heading_name in section_headings:
        headings = panel.get_by_text(
            re.compile(rf"^{re.escape(heading_name)}$", re.IGNORECASE),
        )
        for heading_index in range(await headings.count()):
            heading = headings.nth(heading_index)
            if not await heading.is_visible():
                continue
            region = heading
            for _ in range(8):
                region = region.locator("..")
                if await region.get_by_role("checkbox", name=checkbox_pattern).count():
                    return region
    raise ParserDriftError(
        f"LinkedIn did not show an exact filter choice for {requested_name!r}; "
        f"use {id_field_name} instead."
    )


async def _modern_facet_region(
    panel: Locator,
    facet: _TypeaheadFacet,
) -> Locator:
    button_pattern = _button_name_pattern(facet.add_button_names)
    for heading_name in facet.section_headings:
        headings = panel.get_by_text(
            re.compile(rf"^{re.escape(heading_name)}$", re.IGNORECASE),
        )
        for heading_index in range(await headings.count()):
            heading = headings.nth(heading_index)
            if not await heading.is_visible():
                continue
            region = heading
            for _ in range(8):
                region = region.locator("..")
                buttons = region.get_by_role("button", name=button_pattern)
                visible_buttons = 0
                for button_index in range(await buttons.count()):
                    if await buttons.nth(button_index).is_visible():
                        visible_buttons += 1
                if visible_buttons == 1:
                    return region
    raise ParserDriftError(
        f"LinkedIn's visible {facet.section_headings[0]} filter was unavailable; "
        f"use {facet.id_field_name} instead."
    )


async def _modern_typeahead_option(
    page: Page,
    requested_name: str,
    facet: _TypeaheadFacet,
) -> Locator:
    options = page.get_by_role("option")
    matching_indices: list[int] = []
    stable_rounds = 0
    previous_matches: tuple[int, ...] = ()
    for _ in range(25):
        matching_indices.clear()
        for index in range(await options.count()):
            option = options.nth(index)
            if not await option.is_visible():
                continue
            option_text = await option.inner_text()
            if (
                _typeahead_option_label(option_text, facet.option_kinds).casefold()
                == requested_name.casefold()
            ):
                matching_indices.append(index)
        current_matches = tuple(matching_indices)
        if current_matches and current_matches == previous_matches:
            stable_rounds += 1
        else:
            stable_rounds = 0
        previous_matches = current_matches
        if current_matches and stable_rounds >= 2:
            break
        await page.wait_for_timeout(200)
    if len(matching_indices) != 1:
        qualifier = "no" if not matching_indices else "multiple"
        raise ParserDriftError(
            f"LinkedIn returned {qualifier} exact visible matches for {requested_name!r}; "
            f"use {facet.id_field_name} instead."
        )
    return options.nth(matching_indices[0])


async def _select_modern_typeahead_names(
    page: Page,
    panel: Locator,
    requested_names: tuple[str, ...],
    facet: _TypeaheadFacet,
    *,
    force_reapply: bool = False,
) -> None:
    for requested_name in requested_names:
        region = await _modern_facet_region(panel, facet)
        checkbox = await _exact_modern_checkbox(
            region,
            requested_name,
            id_field_name=facet.id_field_name,
        )
        if checkbox is not None:
            if force_reapply and await checkbox.is_checked():
                await checkbox.uncheck()
                await page.wait_for_timeout(200)
            if not await checkbox.is_checked():
                await checkbox.check()
                await page.wait_for_timeout(200)
            continue

        button_pattern = _button_name_pattern(facet.add_button_names)
        add_buttons = region.get_by_role("button", name=button_pattern)
        visible_buttons = [
            add_buttons.nth(index)
            for index in range(await add_buttons.count())
            if await add_buttons.nth(index).is_visible()
        ]
        if len(visible_buttons) != 1:
            raise ParserDriftError(
                f"LinkedIn's visible {facet.add_button_names[0].lower()} control was ambiguous."
            )
        await visible_buttons[0].click()
        textbox = region.get_by_placeholder(button_pattern)
        try:
            await textbox.first.wait_for(state="visible", timeout=5_000)
            await textbox.first.fill(requested_name)
        except PlaywrightTimeoutError as error:
            raise ParserDriftError(
                f"LinkedIn's visible {facet.add_button_names[0].lower()} input was unavailable."
            ) from error
        await (await _modern_typeahead_option(page, requested_name, facet)).click()
        for _ in range(10):
            checkbox = await _exact_modern_checkbox(
                region,
                requested_name,
                id_field_name=facet.id_field_name,
            )
            if checkbox is not None and await checkbox.is_checked():
                break
            await page.wait_for_timeout(200)


def _query_array_values(source_url: str, parameter_name: str) -> tuple[str, ...]:
    raw_values = parse_qs(urlsplit(source_url).query).get(parameter_name, ())
    values: list[str] = []
    for raw_value in raw_values:
        try:
            decoded = json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise ParserDriftError(
                f"LinkedIn returned an invalid {parameter_name} filter value."
            ) from error
        if not isinstance(decoded, list):
            raise ParserDriftError(f"LinkedIn returned an invalid {parameter_name} filter value.")
        for value in cast(list[object], decoded):
            if not isinstance(value, str) or not value:
                raise ParserDriftError(
                    f"LinkedIn returned an invalid {parameter_name} filter value."
                )
            values.append(value)
    return tuple(dict.fromkeys(values))


def _query_array_alias_values(
    source_url: str,
    *parameter_names: str,
) -> tuple[str, ...]:
    return _merge_values(*tuple(_query_array_values(source_url, name) for name in parameter_names))


def _resolved_facets_from_url(source_url: str) -> _ResolvedPeopleSearchFacets:
    return _ResolvedPeopleSearchFacets(
        actively_hiring_job_title_ids=_query_array_alias_values(
            source_url,
            "activelyHiringForJobTitles",
            "activelyHiringForJobTitle",
        ),
        location_ids=_query_array_values(source_url, "geoUrn"),
        current_company_ids=_query_array_values(source_url, "currentCompany"),
        connections_of_ids=_query_array_alias_values(
            source_url,
            "connectionOf",
            "connectionsOf",
        ),
        followers_of_ids=_query_array_alias_values(
            source_url,
            "followerOf",
            "followersOf",
        ),
        past_company_ids=_query_array_values(source_url, "pastCompany"),
        school_ids=_query_array_values(source_url, "schoolFilter"),
        industry_ids=_query_array_values(source_url, "industry"),
        profile_language_ids=_query_array_values(source_url, "profileLanguage"),
        service_category_ids=_query_array_values(source_url, "serviceCategory"),
    )


def _validate_modern_resolved_facets(
    filters: PeopleSearchFilters,
    resolved: _ResolvedPeopleSearchFacets,
) -> None:
    for direct_ids, requested_names, resolved_ids, id_field_name in (
        (
            filters.actively_hiring_job_title_ids,
            filters.actively_hiring_job_title_names,
            resolved.actively_hiring_job_title_ids,
            "actively_hiring_job_title_ids",
        ),
        (
            filters.location_ids,
            filters.location_names,
            resolved.location_ids,
            "location_ids",
        ),
        (
            filters.current_company_ids,
            filters.current_company_names,
            resolved.current_company_ids,
            "current_company_ids",
        ),
        (
            filters.connections_of_ids,
            filters.connections_of_names,
            resolved.connections_of_ids,
            "connections_of_ids",
        ),
        (
            filters.followers_of_ids,
            filters.followers_of_names,
            resolved.followers_of_ids,
            "followers_of_ids",
        ),
        (
            filters.past_company_ids,
            filters.past_company_names,
            resolved.past_company_ids,
            "past_company_ids",
        ),
        (
            filters.school_ids,
            filters.school_names,
            resolved.school_ids,
            "school_ids",
        ),
        (
            filters.industry_ids,
            filters.industry_names,
            resolved.industry_ids,
            "industry_ids",
        ),
        (
            filters.profile_language_ids,
            filters.profile_language_names,
            resolved.profile_language_ids,
            "profile_language_ids",
        ),
        (
            filters.service_category_ids,
            filters.service_category_names,
            resolved.service_category_ids,
            "service_category_ids",
        ),
    ):
        expected_count = len(direct_ids) + len(requested_names)
        if len(resolved_ids) < expected_count:
            raise ParserDriftError(
                "LinkedIn's submitted People search did not retain every requested "
                f"{id_field_name.removesuffix('_ids')} filter; use {id_field_name} "
                "for any unresolved values."
            )
    if filters.actively_hiring and not resolved.actively_hiring_job_title_ids:
        raise ParserDriftError("LinkedIn's submitted People search did not retain actively_hiring.")


async def _resolve_modern_named_facets(
    browser: BrowserManager,
    page: Page,
    panel: Locator,
    filters: PeopleSearchFilters,
    *,
    force_reapply: bool = False,
) -> _ResolvedPeopleSearchFacets:
    for requested_names, facet in (
        (
            filters.actively_hiring_job_title_names,
            _ACTIVELY_HIRING_JOB_TITLE_FACET,
        ),
        (filters.location_names, _LOCATION_FACET),
        (filters.current_company_names, _CURRENT_COMPANY_FACET),
        (filters.connections_of_names, _CONNECTIONS_OF_FACET),
        (filters.followers_of_names, _FOLLOWERS_OF_FACET),
        (filters.past_company_names, _PAST_COMPANY_FACET),
        (filters.school_names, _SCHOOL_FACET),
        (filters.industry_names, _INDUSTRY_FACET),
        (filters.service_category_names, _SERVICE_CATEGORY_FACET),
    ):
        await _select_modern_typeahead_names(
            page,
            panel,
            requested_names,
            facet,
            force_reapply=force_reapply,
        )
    await _check_modern_names(
        panel,
        filters.profile_language_names,
        id_field_name="profile_language_ids",
        section_headings=("Profile Languages", "Profile languages"),
        force_reapply=force_reapply,
    )
    if filters.actively_hiring:
        actively_hiring = await _exact_modern_checkbox(
            panel,
            "Any job title",
            id_field_name="actively_hiring",
        )
        if actively_hiring is None:
            actively_hiring = await _exact_modern_checkbox(
                panel,
                "Actively hiring",
                id_field_name="actively_hiring",
            )
        if actively_hiring is None:
            raise ParserDriftError(
                "LinkedIn did not expose the requested actively_hiring filter for this account."
            )
        if force_reapply and await actively_hiring.is_checked():
            await actively_hiring.uncheck()
            await page.wait_for_timeout(200)
        if not await actively_hiring.is_checked():
            await actively_hiring.check()
            await page.wait_for_timeout(200)

    show_results = page.get_by_role(
        "link",
        name=re.compile(r"^show results$", re.IGNORECASE),
    )
    if await show_results.count() == 0:
        show_results = panel.get_by_text("Show results", exact=True).locator("xpath=ancestor::a[1]")
    try:
        await show_results.first.wait_for(state="visible", timeout=5_000)
    except PlaywrightTimeoutError as error:
        raise ParserDriftError(
            "LinkedIn's visible Show results control was unavailable for People search."
        ) from error
    submitted_url = await browser.navigate_via_visible_control(page, show_results.first)
    resolved = _resolved_facets_from_url(submitted_url)
    _validate_modern_resolved_facets(filters, resolved)
    return resolved


async def _resolve_named_facets(
    browser: BrowserManager,
    page: Page,
    filters: PeopleSearchFilters,
    *,
    force_reapply: bool = False,
) -> _ResolvedPeopleSearchFacets:
    all_filters = page.get_by_role(
        "button",
        name=re.compile(r"all filters", re.IGNORECASE),
    )
    try:
        await all_filters.first.wait_for(state="visible", timeout=5_000)
        await all_filters.first.click()
    except PlaywrightTimeoutError as error:
        raise ParserDriftError(
            "LinkedIn's visible All filters control was unavailable for People search."
        ) from error

    for _ in range(50):
        panel = await _modern_filter_panel(page)
        if panel is not None:
            return await _resolve_modern_named_facets(
                browser,
                page,
                panel,
                filters,
                force_reapply=force_reapply,
            )
        await page.wait_for_timeout(100)
    raise ParserDriftError(
        "LinkedIn's visible People filters panel was unavailable for People search."
    )


def _connection_degree(text: str) -> PersonConnectionDegree | None:
    match = _CONNECTION_DEGREE_PATTERN.search(text)
    if match is None:
        if "out of network" in text.casefold():
            return PersonConnectionDegree.OUT_OF_NETWORK
        return None
    return {
        "1st": PersonConnectionDegree.FIRST,
        "2nd": PersonConnectionDegree.SECOND,
        "3rd": PersonConnectionDegree.THIRD_OR_MORE,
    }[match.group(1).casefold()]


def _profile_name(link_text: str, aria_label: str | None) -> str | None:
    for candidate in (link_text, aria_label or ""):
        lines = _unique_lines(candidate)
        if not lines:
            continue
        value = lines[0]
        match = re.match(r"^View\s+(.+?)(?:'s|\u2019s)\s+profile$", value, re.IGNORECASE)
        if match:
            value = match.group(1)
        value = _CONNECTION_DEGREE_PATTERN.sub("", value).strip(" \t·•")
        if value and value.casefold() not in {"view profile", "profile"}:
            return value
    return None


class PeopleSearchPage:
    def __init__(self, browser: BrowserManager, *, max_pages: int) -> None:
        if max_pages < 1:
            raise ValueError("People search must allow at least one internal page.")
        self._browser = browser
        self._max_pages = max_pages

    @staticmethod
    def build_url(
        request: PeopleSearchInput,
        page_index: int = 0,
        *,
        resolved_facets: _ResolvedPeopleSearchFacets | None = None,
    ) -> str:
        parameters: dict[str, str | int] = {"origin": "FACETED_SEARCH"}
        if request.query:
            parameters["keywords"] = request.query
        _add_people_search_filters(parameters, request.filters, resolved_facets)
        if page_index:
            parameters["page"] = page_index + 1
        return f"https://www.linkedin.com/search/results/people/?{urlencode(parameters)}"

    async def collect(
        self,
        request: PeopleSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[PersonSummary, ...], PeopleSearchCoverage, str, str]:
        limit = request.page_size if result_limit is None else result_limit
        if limit < 1:
            raise ValueError("People search result limit must be positive.")
        people_by_slug: dict[str, PersonSummary] = {}
        page_texts: list[str] = []
        pages_visited = 0
        unidentifiable_result_count = 0
        stop_reason = StopReason.SAFETY_BOUND
        resolved_facets = _ResolvedPeopleSearchFacets()
        async with self._browser.page() as page:
            if _requires_visible_filter_resolution(request.filters):
                await self._browser.navigate(page, self.build_url(request))
                for resolution_attempt in range(2):
                    try:
                        resolved_facets = await _resolve_named_facets(
                            self._browser,
                            page,
                            request.filters,
                            force_reapply=resolution_attempt > 0,
                        )
                        break
                    except ParserDriftError as error:
                        if (
                            resolution_attempt == 0
                            and "submitted People search did not retain" in error.safe_message
                        ):
                            continue
                        raise
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
                rendered_state = await _wait_for_people_search_state(page)
                pages_visited += 1
                page_text = await self.extract_visible_text(page)
                page_texts.append(page_text)
                page_people = await self.extract_visible_people(page)
                page_unidentifiable_count = await _unidentifiable_people_result_count(page)
                unidentifiable_result_count += page_unidentifiable_count
                added = 0
                for person in page_people:
                    if person.profile_slug in people_by_slug:
                        continue
                    people_by_slug[person.profile_slug] = person
                    added += 1
                    if len(people_by_slug) >= limit:
                        stop_reason = StopReason.RESULT_LIMIT
                        break
                if len(people_by_slug) >= limit:
                    break
                if page_unidentifiable_count:
                    stop_reason = StopReason.VISIBLE_PAGE_COMPLETE
                    break
                if added == 0:
                    if rendered_state is CollectionSettleOutcome.EXPLICIT_END:
                        stop_reason = StopReason.NO_NEW_RESULTS
                    break
        captured_at = datetime.now(UTC)
        people = tuple(people_by_slug.values())
        coverage = PeopleSearchCoverage(
            query=request.query,
            filters=request.filters,
            pages_visited=pages_visited,
            result_count=len(people),
            unidentifiable_result_count=unidentifiable_result_count,
            max_results=limit,
            stop_reason=stop_reason,
            captured_at=captured_at,
        )
        return (
            people,
            coverage,
            "\n\n--- page boundary ---\n\n".join(page_texts),
            first_url,
        )

    @staticmethod
    async def extract_visible_text(page: Page) -> str:
        main_text = await _first_text(page.locator("main"))
        if main_text:
            return main_text
        body_text = await _first_text(page.locator("body"))
        if not body_text:
            raise ParserDriftError("LinkedIn People search returned no visible text.")
        return body_text

    @staticmethod
    async def extract_visible_people(page: Page) -> tuple[PersonSummary, ...]:
        main = page.locator("main")
        raw_cards = await main.get_by_role("listitem").evaluate_all(
            """
            elements => elements
              .filter(element => element.getClientRects().length > 0)
              .slice(0, 500)
              .map(element => ({
                visible_text: element.innerText?.trim() ?? "",
                links: Array.from(element.querySelectorAll('a[href*="/in/"]'))
                  .slice(0, 100)
                  .map(link => ({
                    href: link.getAttribute("href") ?? "",
                    text: link.innerText?.trim() ?? "",
                    aria_label: link.getAttribute("aria-label")
                  }))
              }))
            """
        )
        people: dict[str, PersonSummary] = {}
        for raw_card in cast(list[object], raw_cards):
            if not isinstance(raw_card, dict):
                continue
            card = cast(dict[str, object], raw_card)
            visible_text = card.get("visible_text")
            raw_links = card.get("links")
            if (
                not isinstance(visible_text, str)
                or not visible_text
                or not isinstance(raw_links, list)
            ):
                continue
            candidates: list[tuple[int, int, str, str]] = []
            slug_counts: dict[str, int] = {}
            for link_index, raw_link in enumerate(cast(list[object], raw_links)):
                if not isinstance(raw_link, dict):
                    continue
                link = cast(dict[str, object], raw_link)
                href = link.get("href")
                link_text = link.get("text")
                aria_label = link.get("aria_label")
                if (
                    not isinstance(href, str)
                    or not isinstance(link_text, str)
                    or not (isinstance(aria_label, str) or aria_label is None)
                ):
                    continue
                candidate_slug = profile_slug_from_url(urljoin("https://www.linkedin.com", href))
                candidate_name = _profile_name(link_text, aria_label)
                if not candidate_slug or not candidate_name:
                    continue
                slug_counts[candidate_slug] = slug_counts.get(candidate_slug, 0) + 1
                candidates.append(
                    (
                        len(_unique_lines(link_text)) or 1_000,
                        link_index,
                        candidate_slug,
                        candidate_name,
                    )
                )
            if not candidates:
                continue
            target_slug = max(
                slug_counts,
                key=lambda value: (
                    slug_counts[value],
                    -min(
                        link_index
                        for _, link_index, candidate_slug, _ in candidates
                        if candidate_slug == value
                    ),
                ),
            )
            _, _, profile_slug, name = min(
                (candidate for candidate in candidates if candidate[2] == target_slug),
                key=lambda value: (value[0], value[1]),
            )
            if not profile_slug or not name or profile_slug in people:
                continue
            lines = _unique_lines(visible_text)
            content_lines: list[str] = []
            for line in lines:
                without_degree = _CONNECTION_DEGREE_PATTERN.sub("", line).strip(" \t·•+")
                if (
                    without_degree == name
                    or line.casefold() in _ACTION_LINES
                    or not without_degree
                    or line.casefold().startswith("view ")
                ):
                    continue
                content_lines.append(line)
            mutual_connections_text = next(
                (line for line in content_lines if _MUTUAL_PATTERN.search(line)),
                None,
            )
            descriptive_lines = [
                line
                for line in content_lines
                if line != mutual_connections_text
                and not _CONNECTION_COUNT_PATTERN.search(line)
                and not _FOLLOWER_COUNT_PATTERN.search(line)
            ]
            headline = descriptive_lines[0] if descriptive_lines else None
            location = descriptive_lines[1] if len(descriptive_lines) > 1 else None
            people[profile_slug] = PersonSummary(
                profile_slug=profile_slug,
                profile_url=HttpUrl(canonical_profile_url(profile_slug)),
                name=name,
                headline=headline,
                location=location,
                connection_degree=_connection_degree(visible_text),
                mutual_connections_text=mutual_connections_text,
                visible_text=visible_text,
            )
        return tuple(people.values())


def _section_key(heading: str, source_url: str) -> str:
    detail_match = _PROFILE_DETAIL_PATH.match(urlsplit(source_url).path)
    if detail_match:
        raw_key = detail_match.group("section").lower().replace("_", "-")
        return _CANONICAL_DETAIL_SECTION_KEYS.get(raw_key, raw_key)
    without_count = re.sub(r"\s*\([\d,]+\)\s*$", "", heading)
    normalized = re.sub(r"[^a-z0-9]+", "-", without_count.casefold()).strip("-")
    normalized = normalized[:100] or "other"
    return _CANONICAL_HEADING_SECTION_KEYS.get(normalized, normalized)


def _detail_section_key(url: str) -> str:
    match = _PROFILE_DETAIL_PATH.match(urlsplit(url).path)
    if match is None:
        raise ParserDriftError("LinkedIn profile detail link has an unsupported path.")
    raw_key = match.group("section").lower().replace("_", "-")
    return _CANONICAL_DETAIL_SECTION_KEYS.get(raw_key, raw_key)


def _detail_heading_matches(detail_key: str, heading: str) -> bool:
    normalized_heading = re.sub(
        r"\s+",
        " ",
        re.sub(r"\s*\([\d,]+\)\s*$", "", heading).strip().casefold(),
    )
    aliases = _DETAIL_SECTION_ALIASES.get(
        detail_key,
        (detail_key.replace("-", " "),),
    )
    return normalized_heading in aliases


async def _detail_section_from_visible_heading(
    main: Locator,
    source_url: str,
    detail_key: str,
) -> PersonProfileSection | None:
    values: list[PersonProfileSection] = []
    aliases = _DETAIL_SECTION_ALIASES.get(
        detail_key,
        (detail_key.replace("-", " "),),
    )
    for alias in aliases:
        candidates = main.get_by_text(
            re.compile(
                rf"^{re.escape(alias)}(?:\s*\([\d,]+\))?$",
                re.IGNORECASE,
            )
        )
        for index in range(await candidates.count()):
            candidate = candidates.nth(index)
            if not await candidate.is_visible():
                continue
            sections = candidate.locator("xpath=ancestor::section[1]")
            region = sections.first if await sections.count() else candidate.locator("..")
            visible_text = (await region.inner_text()).strip()
            if not visible_text:
                continue
            heading = (await candidate.inner_text()).strip()
            heading_lines = _unique_lines(heading)
            values.append(
                PersonProfileSection(
                    key=_section_key(heading, source_url),
                    heading=heading_lines[0] if heading_lines else alias,
                    source_url=HttpUrl(source_url),
                    visible_text=visible_text,
                    entries=await _entries_for_section(
                        region,
                        _section_key(heading, source_url),
                    ),
                )
            )
    return (
        max(
            values,
            key=lambda section: (len(section.entries), len(section.visible_text)),
        )
        if values
        else None
    )


async def _entry_links(entry: Locator) -> tuple[PersonProfileLink, ...]:
    links: list[PersonProfileLink] = []
    locators = entry.locator("a[href]")
    for index in range(min(await locators.count(), 50)):
        link = locators.nth(index)
        href = await link.get_attribute("href")
        if not href:
            continue
        absolute_url = urljoin("https://www.linkedin.com", href)
        if urlsplit(absolute_url).scheme not in {"http", "https"}:
            continue
        aria_label = (await link.get_attribute("aria-label") or "").strip()
        visible_label = (await link.inner_text()).strip()
        label = aria_label or visible_label
        if len(label) > 1_000:
            label_lines = _unique_lines(label)
            label = (label_lines[0] if label_lines else label)[:1_000].strip()
        if not label:
            continue
        item = PersonProfileLink(label=label, url=HttpUrl(absolute_url))
        if item not in links:
            links.append(item)
    return tuple(links)


async def _section_entries(section: Locator) -> tuple[PersonProfileSectionEntry, ...]:
    entries: list[PersonProfileSectionEntry] = []
    items = section.get_by_role("listitem")
    for index in range(min(await items.count(), 500)):
        item = items.nth(index)
        if not await item.is_visible() or await item.get_by_role("listitem").count():
            continue
        visible_text = (await item.inner_text()).strip()
        lines = _unique_lines(visible_text)
        if not lines:
            continue
        entry = PersonProfileSectionEntry(
            title=lines[0],
            subtitle=lines[1] if len(lines) > 1 else None,
            visible_text=visible_text,
            links=await _entry_links(item),
        )
        if entry.visible_text not in {existing.visible_text for existing in entries}:
            entries.append(entry)
    return tuple(entries)


async def _current_collection_entries(
    section: Locator,
) -> tuple[PersonProfileSectionEntry, ...]:
    """Read current roleless profile-detail cards from their collection boundary."""

    entries: list[PersonProfileSectionEntry] = []
    items = section.locator(
        '[data-component-type="LazyColumn"] '
        "> [data-lazy-mount-id] "
        '> [componentkey^="entity-collection-item-"]'
    )
    for index in range(min(await items.count(), 500)):
        item = items.nth(index)
        if not await item.is_visible():
            continue
        visible_text = (await item.inner_text()).strip()
        lines = _unique_lines(visible_text)
        if not lines:
            continue
        entry = PersonProfileSectionEntry(
            title=lines[0],
            subtitle=lines[1] if len(lines) > 1 else None,
            visible_text=visible_text,
            links=await _entry_links(item),
        )
        if entry.visible_text not in {existing.visible_text for existing in entries}:
            entries.append(entry)
    return tuple(entries)


async def _skill_entries(section: Locator) -> tuple[PersonProfileSectionEntry, ...]:
    """Bind current skill cards through their exact accessible action control."""

    entries: list[PersonProfileSectionEntry] = []
    seen_skills: set[str] = set()
    controls = section.get_by_role("button")
    for index in range(min(await controls.count(), 500)):
        control = controls.nth(index)
        if not await control.is_visible():
            continue
        accessible_name = (await control.get_attribute("aria-label") or "").strip()
        match = _SKILL_ACTION_PATTERN.fullmatch(accessible_name)
        if not match:
            continue
        skill_name = match.group(1).strip()
        if not skill_name or skill_name.casefold() in seen_skills:
            continue

        region = control.locator("xpath=..")
        for _ in range(6):
            visible_text = (await region.inner_text()).strip()
            lines = _unique_lines(visible_text)
            matching_controls = region.get_by_role("button", name=accessible_name, exact=True)
            if (
                lines
                and lines[0].casefold() == skill_name.casefold()
                and await matching_controls.count() == 1
            ):
                action_lines = {
                    line.casefold()
                    for line in _unique_lines(await matching_controls.first.inner_text())
                }
                metadata_lines = [
                    line
                    for line in lines[1:]
                    if line.casefold() not in action_lines
                    and line.casefold() != accessible_name.casefold()
                ]
                entries.append(
                    PersonProfileSectionEntry(
                        title=skill_name,
                        subtitle=metadata_lines[0] if metadata_lines else None,
                        visible_text=visible_text,
                        links=await _entry_links(region),
                    )
                )
                seen_skills.add(skill_name.casefold())
                break
            region = region.locator("xpath=..")
    return tuple(entries)


async def _linked_section_entries(
    section: Locator,
    link_fragment: str,
) -> tuple[PersonProfileSectionEntry, ...]:
    raw_entries = await section.locator(f'a[href*="{link_fragment}"]').evaluate_all(
        """
        (elements, fragment) => elements.slice(0, 500).flatMap(link => {
          let region = link.parentElement;
          for (let index = 0; region && index < 9; index += 1) {
            const visibleText = region.innerText?.trim() ?? "";
            const lines = visibleText.split("\\n").map(value => value.trim()).filter(Boolean);
            const matchingLinks =
              region.querySelectorAll(`a[href*="${fragment}"]`).length;
            if (lines.length >= 2 && matchingLinks === 1) {
              return [{
                visible_text: visibleText,
                links: Array.from(region.querySelectorAll("a[href]"))
                  .slice(0, 50)
                  .map(item => ({
                    href: item.getAttribute("href") ?? "",
                    text: item.innerText?.trim() ?? "",
                    aria_label: item.getAttribute("aria-label")
                  }))
              }];
            }
            region = region.parentElement;
          }
          return [];
        })
        """,
        link_fragment,
    )
    entries: list[PersonProfileSectionEntry] = []
    for raw_entry in cast(list[object], raw_entries):
        if not isinstance(raw_entry, dict):
            continue
        entry_value = cast(dict[str, object], raw_entry)
        visible_text = entry_value.get("visible_text")
        raw_links = entry_value.get("links")
        if not isinstance(visible_text, str) or not visible_text or not isinstance(raw_links, list):
            continue
        lines = _unique_lines(visible_text)
        if not lines:
            continue
        links: list[PersonProfileLink] = []
        for raw_link in cast(list[object], raw_links):
            if not isinstance(raw_link, dict):
                continue
            link_value = cast(dict[str, object], raw_link)
            href = link_value.get("href")
            text = link_value.get("text")
            aria_label = link_value.get("aria_label")
            if (
                not isinstance(href, str)
                or not href
                or not isinstance(text, str)
                or not (isinstance(aria_label, str) or aria_label is None)
            ):
                continue
            absolute_url = urljoin("https://www.linkedin.com", href)
            if urlsplit(absolute_url).scheme not in {"http", "https"}:
                continue
            label = (aria_label or text).strip()
            if len(label) > 1_000:
                label_lines = _unique_lines(label)
                label = (label_lines[0] if label_lines else label)[:1_000].strip()
            if label:
                item = PersonProfileLink(label=label, url=HttpUrl(absolute_url))
                if item not in links:
                    links.append(item)
        entry = PersonProfileSectionEntry(
            title=lines[0],
            subtitle=lines[1] if len(lines) > 1 else None,
            visible_text=visible_text,
            links=tuple(links),
        )
        if entry.visible_text not in {existing.visible_text for existing in entries}:
            entries.append(entry)
    return tuple(entries)


async def _entries_for_section(
    section: Locator,
    section_key: str,
) -> tuple[PersonProfileSectionEntry, ...]:
    if section_key == "skills":
        current_entries = await _skill_entries(section)
        if current_entries:
            return current_entries
    if section_key not in {"education", "experience", "interests", "skills"}:
        current_entries = await _current_collection_entries(section)
        if current_entries:
            return current_entries
    entries = await _section_entries(section)
    if entries:
        return entries
    link_fragment = {
        "experience": "/company/",
        "education": "/school/",
        "interests": "/company/",
    }.get(section_key)
    linked_entries = await _linked_section_entries(section, link_fragment) if link_fragment else ()
    if section_key != "interests":
        return linked_entries
    return tuple(
        entry.model_copy(
            update={
                "title": (
                    re.sub(r",\s*Company$", "", entry.title, flags=re.IGNORECASE)
                    if entry.title
                    else entry.title
                ),
                "subtitle": _find_line(_unique_lines(entry.visible_text), _FOLLOWER_COUNT_PATTERN)
                or entry.subtitle,
            }
        )
        for entry in linked_entries
    )


async def _extract_sections(
    main: Locator,
    source_url: str,
    *,
    profile_name: str,
) -> tuple[PersonProfileSection, ...]:
    results: list[PersonProfileSection] = []
    sections = main.locator("section")
    for index in range(min(await sections.count(), 100)):
        section = sections.nth(index)
        if not await section.is_visible():
            continue
        headings = section.get_by_role("heading")
        heading = await _first_text(headings)
        if not heading:
            continue
        heading_lines = _unique_lines(heading)
        heading = heading_lines[0] if heading_lines else heading
        if heading == profile_name:
            continue
        visible_text = (await section.inner_text()).strip()
        if not visible_text or visible_text == heading:
            continue
        section_key = _section_key(heading, source_url)
        if section_key in _AUXILIARY_PROFILE_SECTION_KEYS:
            continue
        results.append(
            PersonProfileSection(
                key=section_key,
                heading=heading,
                source_url=HttpUrl(source_url),
                visible_text=visible_text,
                entries=await _entries_for_section(section, section_key),
            )
        )
    detail_match = _PROFILE_DETAIL_PATH.match(urlsplit(source_url).path)
    if not results and detail_match:
        page_heading = await _first_text(main.get_by_role("heading"))
        page_text = (await main.inner_text()).strip()
        if page_heading and page_text and page_text != page_heading:
            results.append(
                PersonProfileSection(
                    key=_section_key(page_heading, source_url),
                    heading=_unique_lines(page_heading)[0],
                    source_url=HttpUrl(source_url),
                    visible_text=page_text,
                    entries=await _entries_for_section(
                        main,
                        _section_key(page_heading, source_url),
                    ),
                )
            )

    if detail_match:
        detail_key = detail_match.group("section").lower().replace("_", "-")
        matching = [
            section for section in results if _detail_heading_matches(detail_key, section.heading)
        ]
        if not matching:
            fallback = await _detail_section_from_visible_heading(
                main,
                source_url,
                detail_key,
            )
            if fallback is not None:
                return (fallback,)
            raise ParserDriftError(
                f"LinkedIn profile detail {detail_key!r} had no matching visible section."
            )
        return (
            max(
                matching,
                key=lambda section: (len(section.entries), len(section.visible_text)),
            ),
        )
    return tuple(results)


def _section_body(section: PersonProfileSection) -> str | None:
    value = section.visible_text.strip()
    heading_index = value.casefold().find(section.heading.casefold())
    if heading_index == 0:
        value = value[len(section.heading) :].strip()
    value = re.split(
        r"\n\s*(?:\N{HORIZONTAL ELLIPSIS}|\.\.\.)\s*more\s*(?:\n|$)",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    value = re.split(
        r"\n\s*top skills\s*(?:\n|$)",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    value = re.sub(
        r"\n(?:see more|show all|show less)(?:\s+[^\n]+)?\s*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    return value or None


def _find_line(lines: list[str], pattern: re.Pattern[str]) -> str | None:
    return next((line for line in lines if pattern.search(line)), None)


def _first_pattern_text(lines: list[str], pattern: re.Pattern[str]) -> str | None:
    for line in lines:
        match = pattern.search(line)
        if match:
            return match.group(0).strip()
    return None


def _looks_like_experience_location(value: str) -> bool:
    normalized = value.strip()
    if not normalized or len(normalized) > 200:
        return False
    if normalized.startswith(("-", "*", "\N{BULLET}")):
        return False
    if normalized.casefold().startswith(("core technologies:", "skills:")):
        return False
    lowered = normalized.casefold()
    if re.search(r"\bskills?\b", lowered):
        return False
    return (
        lowered in {"remote", "hybrid", "on-site", "onsite"}
        or "," in normalized
        or lowered.endswith(" area")
    )


def _parse_experiences(
    sections: tuple[PersonProfileSection, ...],
) -> tuple[PersonExperience, ...]:
    values: list[PersonExperience] = []
    for section in sections:
        if section.heading.casefold() != "experience" and section.key != "experience":
            continue
        for entry in section.entries:
            lines = _unique_lines(entry.visible_text)
            if not lines:
                continue
            skill_association_lines = {
                line
                for link in entry.links
                if "skill-associations-details" in urlsplit(str(link.url)).path
                for line in _unique_lines(link.label)
            }
            date_range = _find_line(lines, _DATE_RANGE_PATTERN)
            date_index = lines.index(date_range) if date_range in lines else -1
            title = lines[0]
            organization_line = lines[1] if len(lines) > 1 and lines[1] != date_range else None
            organization: str | None = None
            employment_type: str | None = None
            if organization_line:
                if organization_line.casefold() in _EMPLOYMENT_TYPE_LINES:
                    employment_type = organization_line
                else:
                    organization_parts = [part.strip() for part in organization_line.split("·")]
                    organization = organization_parts[0] or None
                    employment_type = organization_parts[1] if len(organization_parts) > 1 else None
            date_parts = [part.strip() for part in date_range.split("·")] if date_range else []
            location_candidate = (
                lines[date_index + 1] if date_index >= 0 and date_index + 1 < len(lines) else None
            )
            location = (
                location_candidate
                if location_candidate
                and location_candidate not in skill_association_lines
                and _looks_like_experience_location(location_candidate)
                else None
            )
            description_start = date_index + 2 if location else date_index + 1
            description_lines = lines[description_start:] if description_start > 0 else lines[2:]
            cleaned_description_lines: list[str] = []
            for line in description_lines:
                if re.fullmatch(
                    r"(?:\N{HORIZONTAL ELLIPSIS}|\.\.\.)\s*more",
                    line,
                    flags=re.IGNORECASE,
                ):
                    break
                if line not in skill_association_lines:
                    cleaned_description_lines.append(line)
            organization_url = next(
                (link.url for link in entry.links if "/company/" in urlsplit(str(link.url)).path),
                None,
            )
            values.append(
                PersonExperience(
                    title=title,
                    organization=organization,
                    organization_url=organization_url,
                    employment_type=employment_type,
                    date_range=date_parts[0] if date_parts else date_range,
                    duration=date_parts[1] if len(date_parts) > 1 else None,
                    location=location,
                    description="\n".join(cleaned_description_lines).strip() or None,
                    is_current=("present" in date_range.casefold() if date_range else None),
                    source_url=section.source_url,
                    visible_text=entry.visible_text,
                )
            )
    return tuple(values)


def _parse_education(
    sections: tuple[PersonProfileSection, ...],
) -> tuple[PersonEducation, ...]:
    values: list[PersonEducation] = []
    for section in sections:
        if section.heading.casefold() != "education" and section.key != "education":
            continue
        for entry in section.entries:
            lines = _unique_lines(entry.visible_text)
            if not lines:
                continue
            date_range = _find_line(lines, _DATE_RANGE_PATTERN)
            date_index = lines.index(date_range) if date_range in lines else -1
            degree_line = lines[1] if len(lines) > 1 and lines[1] != date_range else None
            degree_parts = (
                [part.strip() for part in degree_line.split(",", maxsplit=1)] if degree_line else []
            )
            description_lines = lines[date_index + 1 :] if date_index >= 0 else lines[2:]
            school_url = next(
                (link.url for link in entry.links if "/school/" in urlsplit(str(link.url)).path),
                None,
            )
            values.append(
                PersonEducation(
                    school=lines[0],
                    school_url=school_url,
                    degree=degree_parts[0] if degree_parts else None,
                    field_of_study=degree_parts[1] if len(degree_parts) > 1 else None,
                    date_range=date_range,
                    description="\n".join(description_lines).strip() or None,
                    source_url=section.source_url,
                    visible_text=entry.visible_text,
                )
            )
    return tuple(values)


async def _expand_and_scroll(page: Page) -> None:
    main = page.locator("main")
    source_path = urlsplit(page.url).path.rstrip("/")
    for scroll_index in range(8):
        try:
            await main.wait_for(state="visible", timeout=5_000)
        except PlaywrightTimeoutError as error:
            raise ParserDriftError(
                "LinkedIn member profile became unavailable during bounded scrolling "
                f"at step {scroll_index + 1}."
            ) from error
        await main.evaluate("element => { element.scrollTop = element.scrollHeight; }")
        await page.keyboard.press("End")
        await page.wait_for_timeout(200)
        if urlsplit(page.url).path.rstrip("/") != source_path:
            raise ParserDriftError("LinkedIn member profile navigated away during scrolling.")
    buttons = main.get_by_role(
        "button",
        name=re.compile(r"^(?:see more|show more)", re.IGNORECASE),
    )
    for index in range(min(await buttons.count(), 100)):
        button = buttons.nth(index)
        try:
            if not await button.is_visible():
                continue
            source_url = page.url
            await button.click(timeout=1_000)
            if page.url != source_url:
                raise ParserDriftError(
                    "A profile content-expansion control unexpectedly navigated away."
                )
        except PlaywrightTimeoutError:
            continue
    await main.evaluate("element => { element.scrollTop = 0; }")
    await page.keyboard.press("Home")


async def _visible_page_text(page: Page) -> str:
    text = await _first_text(page.locator("main"))
    if text:
        return text
    text = await _first_text(page.locator("body"))
    if not text:
        raise ParserDriftError("LinkedIn member profile returned no visible text.")
    return text


async def _profile_detail_urls(
    main: Locator,
    profile_slug: str,
) -> tuple[str, ...]:
    urls: list[str] = []
    links = main.locator('a[href*="/details/"]')
    for index in range(min(await links.count(), 100)):
        link = links.nth(index)
        if not await link.is_visible():
            continue
        href = await link.get_attribute("href")
        if not href:
            continue
        label = " ".join(
            (
                (await link.inner_text()).strip(),
                (await link.get_attribute("aria-label") or "").strip(),
            )
        ).strip()
        if not re.search(r"\b(?:show|see)\s+all\b", label, re.IGNORECASE):
            continue
        url = urljoin("https://www.linkedin.com", href)
        match = _PROFILE_DETAIL_PATH.match(urlsplit(url).path)
        if not match or match.group("slug") != profile_slug:
            continue
        clean_url = f"https://www.linkedin.com{urlsplit(url).path}"
        if _detail_section_key(clean_url) in _AUXILIARY_PROFILE_SECTION_KEYS:
            continue
        if clean_url not in urls:
            urls.append(clean_url)
    return tuple(urls)


async def _top_card(main: Locator) -> tuple[Locator, str, str]:
    headings = main.get_by_role("heading", level=1)
    name = await _first_text(headings)
    if not name:
        page = main.page
        title = await page.title()
        candidate = re.split(r"\s*[|·]\s*LinkedIn", title, maxsplit=1)[0].strip()
        main_text = (await main.inner_text()).strip()
        if (
            not candidate
            or len(candidate) > 500
            or candidate not in {line.strip() for line in main_text.splitlines()}
        ):
            raise ParserDriftError("LinkedIn member profile has no exact visible member name.")
        candidate_headings = main.get_by_role(
            "heading",
            name=re.compile(rf"^{re.escape(candidate)}$"),
        )
        visible_headings: list[Locator] = []
        for index in range(await candidate_headings.count()):
            heading = candidate_headings.nth(index)
            if await heading.is_visible():
                visible_headings.append(heading)
        if len(visible_headings) != 1:
            raise ParserDriftError("LinkedIn member profile has no unique visible member name.")
        name = candidate
        name_heading = visible_headings[0]
    else:
        name = _unique_lines(name)[0]
        name_heading = headings.first
    top = name_heading.locator("xpath=ancestor::section[1]")
    if await top.count() == 0:
        top = name_heading.locator("..")
    visible_text = (await top.inner_text()).strip()
    if not visible_text:
        raise ParserDriftError("LinkedIn member profile introduction is empty.")
    return top, name, visible_text


async def _top_card_fields(
    top: Locator,
    name: str,
    visible_text: str,
) -> tuple[
    str | None,
    str | None,
    str | None,
    PersonConnectionDegree | None,
    str | None,
    str | None,
]:
    lines = _unique_lines(visible_text)
    auxiliary_lines = {
        line
        for value in await top.locator(
            'a[href*="/trust/verification/"], a[href*="/verify/"]'
        ).all_inner_texts()
        for line in _unique_lines(value)
    }
    try:
        name_index = lines.index(name)
    except ValueError:
        name_index = 0
    candidates = lines[name_index + 1 :]
    pronouns = next(
        (
            line
            for line in candidates[:3]
            if "/" in line
            and len(line) <= 80
            and (
                (line.startswith("(") and line.endswith(")"))
                or re.fullmatch(r"[A-Za-z]+(?:/[A-Za-z]+)+", line)
            )
        ),
        None,
    )
    headline = next(
        (
            line
            for line in candidates
            if line != pronouns
            and line not in auxiliary_lines
            and line.casefold() not in _ACTION_LINES
            and not _CONNECTION_DEGREE_PATTERN.fullmatch(line.strip(" ·•"))
            and not _CONNECTION_COUNT_PATTERN.search(line)
            and not _FOLLOWER_COUNT_PATTERN.search(line)
            and line.casefold() != "contact info"
        ),
        None,
    )
    contact_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.casefold().strip(" ·•").startswith("contact info")
        ),
        -1,
    )
    location = None
    if contact_index > 0:
        location = next(
            (
                candidate
                for candidate in reversed(lines[:contact_index])
                if candidate not in {name, headline, pronouns}
                and candidate not in auxiliary_lines
                and candidate.strip(" ·•")
                and not _CONNECTION_DEGREE_PATTERN.fullmatch(candidate.strip(" ·•"))
                and not _CONNECTION_COUNT_PATTERN.search(candidate)
                and not _FOLLOWER_COUNT_PATTERN.search(candidate)
            ),
            None,
        )
    connection_count = _first_pattern_text(lines, _CONNECTION_COUNT_PATTERN)
    follower_count = _first_pattern_text(lines, _FOLLOWER_COUNT_PATTERN)
    return (
        pronouns,
        headline,
        location,
        _connection_degree(visible_text),
        connection_count,
        follower_count,
    )


def _merge_sections(
    main_sections: tuple[PersonProfileSection, ...],
    detail_sections: tuple[PersonProfileSection, ...],
) -> tuple[PersonProfileSection, ...]:
    values: dict[str, PersonProfileSection] = {section.key: section for section in main_sections}
    for section in detail_sections:
        values[section.key] = section
    return tuple(values.values())


class PersonProfilePage:
    def __init__(self, browser: BrowserManager, *, max_detail_pages: int) -> None:
        if max_detail_pages < 0:
            raise ValueError("Profile detail-page bound cannot be negative.")
        self._browser = browser
        self._max_detail_pages = max_detail_pages

    async def read(
        self,
        request: PeopleGetInput,
    ) -> tuple[PersonProfileObservation, tuple[PersonProfilePageCapture, ...]]:
        captures: list[PersonProfilePageCapture] = []
        detail_sections: list[PersonProfileSection] = []
        read_all_sections = request.sections == (PersonProfileSectionSelector.ALL,)
        requested_section_keys = (
            None
            if read_all_sections
            else {
                section.value
                for section in request.sections
                if section is not PersonProfileSectionSelector.OVERVIEW
            }
        )
        async with self._browser.page() as page:
            await self._browser.navigate(page, canonical_profile_url(request.profile_slug))
            try:
                await (
                    page.locator("main")
                    .get_by_role("heading")
                    .first.wait_for(
                        state="visible",
                        timeout=10_000,
                    )
                )
            except PlaywrightTimeoutError as error:
                raise ParserDriftError("LinkedIn member profile has no visible heading.") from error
            main = page.locator("main")
            await _top_card(main)
            await page.wait_for_timeout(2_000)
            await _expand_and_scroll(page)
            main = page.locator("main")
            top, name, top_text = await _top_card(main)
            (
                pronouns,
                headline,
                location,
                connection_degree,
                connection_count_text,
                follower_count_text,
            ) = await _top_card_fields(top, name, top_text)
            current_company_text = await _first_text(top.locator('a[href*="/company/"]'))
            if current_company_text is None:
                current_company_text = await _first_text(
                    top.locator('[role="button"]:has(svg[id^="company-accent-"])')
                )
            education_summary_text = await _first_text(top.locator('a[href*="/school/"]'))
            if education_summary_text is None:
                education_summary_text = await _first_text(
                    top.locator('[role="button"]:has(svg[id^="school-accent-"])')
                )
            actual_slug = profile_slug_from_url(page.url) or request.profile_slug
            profile_url = canonical_profile_url(actual_slug)
            main_text = await _visible_page_text(page)
            main_captured_at = datetime.now(UTC)
            captures.append(
                PersonProfilePageCapture(
                    source_url=HttpUrl(profile_url),
                    page_kind="profile",
                    captured_text=main_text,
                    captured_at=main_captured_at,
                )
            )
            all_main_sections = await _extract_sections(
                main,
                profile_url,
                profile_name=name,
            )
            detail_urls = await _profile_detail_urls(main, actual_slug)
            detail_pairs = tuple((url, _detail_section_key(url)) for url in detail_urls)
            selected_detail_pairs = (
                detail_pairs
                if requested_section_keys is None
                else tuple(pair for pair in detail_pairs if pair[1] in requested_section_keys)
            )
            visited_detail_pairs = selected_detail_pairs[: self._max_detail_pages]
            truncated_detail_pairs = selected_detail_pairs[self._max_detail_pages :]
            main_sections = (
                all_main_sections
                if requested_section_keys is None
                else tuple(
                    section
                    for section in all_main_sections
                    if section.key in requested_section_keys
                )
            )

            for detail_url, _detail_key in visited_detail_pairs:
                await self._browser.navigate(page, detail_url)
                await _expand_and_scroll(page)
                detail_text = await _visible_page_text(page)
                page_sections = await _extract_sections(
                    page.locator("main"),
                    detail_url,
                    profile_name=name,
                )
                section_heading = page_sections[0].heading if page_sections else "Profile section"
                captures.append(
                    PersonProfilePageCapture(
                        source_url=HttpUrl(detail_url),
                        page_kind="section",
                        section_heading=section_heading,
                        captured_text=detail_text,
                        captured_at=datetime.now(UTC),
                    )
                )
                detail_sections.extend(page_sections)

        sections = _merge_sections(main_sections, tuple(detail_sections))
        experiences = _parse_experiences(sections)
        education = _parse_education(sections)
        about_section = next(
            (
                section
                for section in sections
                if section.heading.casefold() == "about" or section.key == "about"
            ),
            None,
        )
        about = _section_body(about_section) if about_section else None
        captured_at = datetime.now(UTC)
        returned_sections = tuple(
            dict.fromkeys(("overview", *(section.key for section in sections)))
        )
        returned_section_set = set(returned_sections)
        unavailable_sections = tuple(
            section
            for section in request.sections
            if section is not PersonProfileSectionSelector.ALL
            and section.value not in returned_section_set
        )
        coverage = PersonProfileCoverage(
            pages_visited=len(captures),
            detail_pages_discovered=len(detail_urls),
            detail_pages_visited=len(visited_detail_pairs),
            detail_page_limit=self._max_detail_pages,
            truncated=bool(truncated_detail_pairs),
            captured_at=captured_at,
            requested_sections=request.sections,
            returned_sections=returned_sections,
            detail_sections_discovered=tuple(dict.fromkeys(section for _, section in detail_pairs)),
            detail_sections_visited=tuple(
                dict.fromkeys(section for _, section in visited_detail_pairs)
            ),
            unavailable_sections=unavailable_sections,
            truncated_sections=tuple(
                dict.fromkeys(section for _, section in truncated_detail_pairs)
            ),
        )
        combined_text = "\n\n".join(
            f"--- source: {capture.source_url} ---\n{capture.captured_text}" for capture in captures
        )
        main_url = captures[0].source_url
        evidence_values = (
            ("name", name, main_url),
            ("pronouns", pronouns, main_url),
            ("headline", headline, main_url),
            ("location", location, main_url),
            ("connection_count_text", connection_count_text, main_url),
            ("follower_count_text", follower_count_text, main_url),
            ("current_company_text", current_company_text, main_url),
            ("education_summary_text", education_summary_text, main_url),
            (
                "about",
                about,
                about_section.source_url if about_section else main_url,
            ),
        )
        evidence = tuple(
            PersonProfileEvidence(field=field, quote=value, source_url=source_url)
            for field, value, source_url in evidence_values
            if value
        )
        observation = PersonProfileObservation(
            profile_slug=actual_slug,
            profile_url=HttpUrl(profile_url),
            name=name,
            pronouns=pronouns,
            headline=headline,
            location=location,
            connection_degree=connection_degree,
            connection_count_text=connection_count_text,
            follower_count_text=follower_count_text,
            current_company_text=current_company_text,
            education_summary_text=education_summary_text,
            about=about,
            experiences=experiences,
            education=education,
            sections=sections,
            visible_text=combined_text,
            evidence=evidence,
            coverage=coverage,
            captured_at=captured_at,
        )
        return observation, tuple(captures)
