"""Visible LinkedIn page implementation for `linkedin_mcp.tools.people.search.page`."""

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

from linkedin_mcp.browser import BrowserManager
from linkedin_mcp.browser.urls import canonical_profile_url, profile_slug_from_url
from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.infra.playwright import Paced
from linkedin_mcp.infra.playwright.collections import (
    CollectionSettleOutcome,
    visible_locator_signature,
    wait_for_collection_initial_state,
)
from linkedin_mcp.tools.people.search.models import (
    PeopleSearchConnectionDegree,
    PeopleSearchCoverage,
    PeopleSearchFilters,
    PeopleSearchInput,
    PersonConnectionDegree,
    PersonSummary,
    StopReason,
)
from linkedin_mcp.tools.people.surface import (
    ACTION_LINES,
    CONNECTION_COUNT_PATTERN,
    CONNECTION_DEGREE_PATTERN,
    FOLLOWER_COUNT_PATTERN,
    connection_degree,
    first_text,
    unique_lines,
)
from linkedin_mcp.tools.people.surface import (
    lines as visible_text_lines,
)

_CONNECTION_FILTER_CODES = {
    PeopleSearchConnectionDegree.FIRST: "F",
    PeopleSearchConnectionDegree.SECOND: "S",
    PeopleSearchConnectionDegree.THIRD_OR_MORE: "O",
}

_MUTUAL_PATTERN = re.compile(r"\bmutual connections?\b", re.IGNORECASE)

_PEOPLE_SEARCH_END_PATTERN = re.compile(
    r"^(?:no (?:matching )?(?:people|results)(?: found| to show)?|"
    r"we couldn(?:'|\N{RIGHT SINGLE QUOTATION MARK})t find any results)"
    r"(?:[.!])?$",
    re.IGNORECASE,
)

_INITIAL_RESULTS_POLL_ATTEMPTS = 20

_INITIAL_RESULTS_POLL_DELAY_MS = 250


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
    lines = visible_text_lines(option_text)
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
    paced: Paced,
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
            await paced.uncheck(checkbox)
            await panel.page.wait_for_timeout(200)
        if not await checkbox.is_checked():
            await paced.check(checkbox)
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
    paced: Paced,
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
                await paced.uncheck(checkbox)
                await page.wait_for_timeout(200)
            if not await checkbox.is_checked():
                await paced.check(checkbox)
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
        await paced.click(visible_buttons[0])
        textbox = region.get_by_placeholder(button_pattern)
        try:
            await textbox.first.wait_for(state="visible", timeout=5_000)
            await paced.fill(textbox.first, requested_name)
        except PlaywrightTimeoutError as error:
            raise ParserDriftError(
                f"LinkedIn's visible {facet.add_button_names[0].lower()} input was unavailable."
            ) from error
        await paced.click(await _modern_typeahead_option(page, requested_name, facet))
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
            browser.paced,
            page,
            panel,
            requested_names,
            facet,
            force_reapply=force_reapply,
        )
    await _check_modern_names(
        browser.paced,
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
            await browser.paced.uncheck(actively_hiring)
            await page.wait_for_timeout(200)
        if not await actively_hiring.is_checked():
            await browser.paced.check(actively_hiring)
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
    submitted_url = await browser.paced.click_and_wait_for_navigation(
        page,
        show_results.first,
    )
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
        await browser.paced.click(all_filters.first)
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


def _profile_name(link_text: str, aria_label: str | None) -> str | None:
    for candidate in (link_text, aria_label or ""):
        lines = unique_lines(candidate)
        if not lines:
            continue
        value = lines[0]
        match = re.match(r"^View\s+(.+?)(?:'s|\u2019s)\s+profile$", value, re.IGNORECASE)
        if match:
            value = match.group(1)
        value = CONNECTION_DEGREE_PATTERN.sub("", value).strip(" \t·•")
        if value and value.casefold() not in {"view profile", "profile"}:
            return value
    return None


class PeopleSearchPage:
    def __init__(self, browser: BrowserManager, *, max_pages: int) -> None:
        if max_pages < 1:
            raise ValueError("People search must allow at least one internal page.")
        self._browser = browser
        self._paced = browser.paced
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
                await self._paced.goto(page, self.build_url(request))
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
                await self._paced.goto(
                    page, self.build_url(request, page_index, resolved_facets=resolved_facets)
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
        main_text = await first_text(page.locator("main"))
        if main_text:
            return main_text
        body_text = await first_text(page.locator("body"))
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
                        len(unique_lines(link_text)) or 1_000,
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
            lines = unique_lines(visible_text)
            content_lines: list[str] = []
            for line in lines:
                without_degree = CONNECTION_DEGREE_PATTERN.sub("", line).strip(" \t·•+")
                if (
                    without_degree == name
                    or line.casefold() in ACTION_LINES
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
                and not CONNECTION_COUNT_PATTERN.search(line)
                and not FOLLOWER_COUNT_PATTERN.search(line)
            ]
            headline = descriptive_lines[0] if descriptive_lines else None
            location = descriptive_lines[1] if len(descriptive_lines) > 1 else None
            people[profile_slug] = PersonSummary(
                profile_slug=profile_slug,
                profile_url=HttpUrl(canonical_profile_url(profile_slug)),
                name=name,
                headline=headline,
                location=location,
                connection_degree=(
                    PersonConnectionDegree(value)
                    if (value := connection_degree(visible_text)) is not None
                    else None
                ),
                mutual_connections_text=mutual_connections_text,
                visible_text=visible_text,
            )
        return tuple(people.values())
