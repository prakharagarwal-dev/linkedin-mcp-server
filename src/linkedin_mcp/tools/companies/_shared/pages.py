"""Bounded visible LinkedIn Company search and company-profile page objects."""

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
from linkedin_mcp.tools._shared.models import StopReason
from linkedin_mcp.tools._shared.urls import (
    canonical_company_url,
    company_slug_from_url,
)
from linkedin_mcp.tools.companies._shared.models import (
    CompanyGetInput,
    CompanyProfileCoverage,
    CompanyProfileEvidence,
    CompanyProfileObservation,
    CompanyProfilePageCapture,
    CompanySearchCoverage,
    CompanySearchFilters,
    CompanySearchInput,
    CompanySize,
    CompanySummary,
)

_COMPANY_SEARCH_URL = "https://www.linkedin.com/search/results/companies/"
_COMPANY_SIZE_CODES = {
    CompanySize.EMPLOYEES_1_10: "B",
    CompanySize.EMPLOYEES_11_50: "C",
    CompanySize.EMPLOYEES_51_200: "D",
    CompanySize.EMPLOYEES_201_500: "E",
    CompanySize.EMPLOYEES_501_1000: "F",
    CompanySize.EMPLOYEES_1001_5000: "G",
    CompanySize.EMPLOYEES_5001_10000: "H",
    CompanySize.EMPLOYEES_10001_PLUS: "I",
}
_VISIBLE_COUNT = r"\d[\d,.]*[KMB]?\+?"
_FOLLOWER_COUNT_PATTERN = re.compile(
    rf"\b{_VISIBLE_COUNT}\s+followers?\b",
    re.IGNORECASE,
)
_ASSOCIATED_MEMBER_PATTERN = re.compile(
    rf"\b{_VISIBLE_COUNT}\s+(?:associated\s+)?(?:members?|employees?)\b",
    re.IGNORECASE,
)
_EXPLICIT_ASSOCIATED_MEMBER_PATTERN = re.compile(
    rf"\b{_VISIBLE_COUNT}\s+associated\s+members?\b",
    re.IGNORECASE,
)
_COMPANY_SIZE_PATTERN = re.compile(
    r"\b(?:self-employed|(?:1|11|51|201|501|1,001|5,001|10,001)"
    r"\s*-\s*(?:10|50|200|500|1,000|5,000|10,000)|10,001\+)"
    r"\s+employees?\b",
    re.IGNORECASE,
)
_ACTION_LINES = frozenset(
    {
        "follow",
        "following",
        "message",
        "visit website",
        "more",
        "see all",
        "show all",
    }
)
_COMPANY_SEARCH_END_PATTERN = re.compile(
    r"^(?:no (?:matching )?(?:companies|results)(?: found| to show)?|"
    r"we couldn(?:'|\N{RIGHT SINGLE QUOTATION MARK})t find any results)"
    r"(?:[.!])?$",
    re.IGNORECASE,
)
_INITIAL_RESULTS_POLL_ATTEMPTS = 20
_INITIAL_RESULTS_POLL_DELAY_MS = 250
_ABOUT_FIELD_LABELS = (
    "Website",
    "Industry",
    "Company size",
    "Headquarters",
    "Type",
    "Founded",
    "Specialties",
)


async def _company_search_has_explicit_end(page: Page) -> bool:
    main = page.locator("main")
    if await main.count() == 0:
        return False
    text = (await main.first.inner_text()).strip()
    return any(
        _COMPANY_SEARCH_END_PATTERN.fullmatch(line.strip())
        for line in text.splitlines()
        if line.strip()
    )


async def _wait_for_company_search_state(page: Page) -> CollectionSettleOutcome:
    async def read_signature() -> tuple[str, ...]:
        return await visible_locator_signature(
            page.locator('main li a[href*="/company/"]'),
            identity_attributes=("href",),
        )

    result = await wait_for_collection_initial_state(
        page,
        read_signature=read_signature,
        read_explicit_end=lambda: _company_search_has_explicit_end(page),
        attempts=_INITIAL_RESULTS_POLL_ATTEMPTS,
        delay_ms=_INITIAL_RESULTS_POLL_DELAY_MS,
    )
    return result.outcome


@dataclass(frozen=True, slots=True)
class _ResolvedCompanyFacets:
    location_ids: tuple[str, ...] = ()
    industry_ids: tuple[str, ...] = ()


_EMPTY_RESOLVED_COMPANY_FACETS = _ResolvedCompanyFacets()


def _unique_lines(value: str) -> list[str]:
    values: list[str] = []
    for raw_line in value.splitlines():
        line = " ".join(raw_line.split())
        if line and line not in values:
            values.append(line)
    return values


async def _first_visible_text(locator: Locator) -> str | None:
    for index in range(min(await locator.count(), 100)):
        candidate = locator.nth(index)
        if not await candidate.is_visible():
            continue
        value = (await candidate.inner_text()).strip()
        if value:
            return value
    return None


async def _expand_and_scroll(page: Page) -> None:
    main = page.locator("main")
    try:
        await main.wait_for(state="visible", timeout=10_000)
    except PlaywrightTimeoutError as error:
        raise ParserDriftError("LinkedIn Company surface has no visible main region.") from error
    source_path = urlsplit(page.url).path.rstrip("/")
    for _ in range(8):
        await main.evaluate("element => { element.scrollTop = element.scrollHeight; }")
        await page.keyboard.press("End")
        await page.wait_for_timeout(200)
        if urlsplit(page.url).path.rstrip("/") != source_path:
            raise ParserDriftError("LinkedIn Company surface navigated away while scrolling.")
    buttons = main.get_by_role(
        "button",
        name=re.compile(r"^(?:see more|show more)", re.IGNORECASE),
    )
    for index in range(min(await buttons.count(), 100)):
        button = buttons.nth(index)
        try:
            if await button.is_visible():
                source_url = page.url
                await button.click(timeout=1_000)
                if page.url != source_url:
                    raise ParserDriftError(
                        "A Company content-expansion control unexpectedly navigated away."
                    )
        except PlaywrightTimeoutError:
            continue
    await main.evaluate("element => { element.scrollTop = 0; }")
    await page.keyboard.press("Home")


def _add_company_filters(
    parameters: dict[str, str],
    filters: CompanySearchFilters,
    resolved: _ResolvedCompanyFacets,
) -> None:
    location_ids = tuple(dict.fromkeys((*filters.location_ids, *resolved.location_ids)))
    industry_ids = tuple(dict.fromkeys((*filters.industry_ids, *resolved.industry_ids)))
    if location_ids:
        parameters["companyHqGeo"] = json.dumps(location_ids, separators=(",", ":"))
    if industry_ids:
        parameters["industryCompanyVertical"] = json.dumps(
            industry_ids,
            separators=(",", ":"),
        )
    if filters.company_sizes:
        parameters["companySize"] = json.dumps(
            tuple(_COMPANY_SIZE_CODES[value] for value in filters.company_sizes),
            separators=(",", ":"),
        )
    if filters.has_job_listings:
        parameters["hasJobs"] = '["1"]'
    if filters.has_first_degree_connections:
        parameters["network"] = '["F"]'


def _build_company_search_url(
    request: CompanySearchInput,
    *,
    page_index: int,
    resolved: _ResolvedCompanyFacets = _EMPTY_RESOLVED_COMPANY_FACETS,
) -> str:
    parameters = {
        "origin": "GLOBAL_SEARCH_HEADER",
        "page": str(page_index),
    }
    if request.query:
        parameters["keywords"] = request.query
    _add_company_filters(parameters, request.filters, resolved)
    return f"{_COMPANY_SEARCH_URL}?{urlencode(parameters)}"


@dataclass(frozen=True, slots=True)
class _CompanyTypeaheadFacet:
    heading: str
    add_button_name: str
    query_parameter: str
    id_field_name: str


_LOCATION_TYPEAHEAD = _CompanyTypeaheadFacet(
    heading="Locations",
    add_button_name="Add a location",
    query_parameter="companyHqGeo",
    id_field_name="location_ids",
)
_INDUSTRY_TYPEAHEAD = _CompanyTypeaheadFacet(
    heading="Industry",
    add_button_name="Add an industry",
    query_parameter="industryCompanyVertical",
    id_field_name="industry_ids",
)


async def _company_filter_panel(page: Page) -> Locator:
    show_results = page.get_by_role(
        "link",
        name=re.compile(r"^Show results$", re.IGNORECASE),
    )
    for _ in range(50):
        for index in range(await show_results.count()):
            control = show_results.nth(index)
            if not await control.is_visible():
                continue
            region = control
            for _ in range(10):
                region = region.locator("..")
                has_every_heading = True
                for heading in ("Locations", "Industry", "Company size"):
                    if not await region.get_by_role(
                        "heading",
                        name=re.compile(rf"^{re.escape(heading)}$", re.IGNORECASE),
                    ).count():
                        has_every_heading = False
                        break
                if has_every_heading:
                    return region
        await page.wait_for_timeout(100)
    raise ParserDriftError("LinkedIn's visible Company filters panel was unavailable.")


async def _company_facet_region(
    panel: Locator,
    facet: _CompanyTypeaheadFacet,
) -> Locator:
    headings = panel.get_by_role(
        "heading",
        name=re.compile(rf"^{re.escape(facet.heading)}$", re.IGNORECASE),
    )
    for heading_index in range(await headings.count()):
        heading = headings.nth(heading_index)
        if not await heading.is_visible():
            continue
        region = heading
        for _ in range(8):
            region = region.locator("..")
            buttons = region.get_by_role(
                "button",
                name=re.compile(
                    rf"^{re.escape(facet.add_button_name)}$",
                    re.IGNORECASE,
                ),
            )
            visible_buttons = [
                buttons.nth(index)
                for index in range(await buttons.count())
                if await buttons.nth(index).is_visible()
            ]
            if len(visible_buttons) == 1:
                return region
    raise ParserDriftError(
        f"LinkedIn's visible {facet.heading} Company filter was unavailable; "
        f"use {facet.id_field_name} instead."
    )


async def _exact_company_checkbox(
    region: Locator,
    requested_name: str,
    *,
    id_field_name: str,
) -> Locator | None:
    normalized = " ".join(requested_name.split())
    candidates = region.get_by_role(
        "checkbox",
        name=re.compile(rf"^{re.escape(normalized)}$", re.IGNORECASE),
    )
    visible = [
        candidates.nth(index)
        for index in range(await candidates.count())
        if await candidates.nth(index).is_visible()
    ]
    if len(visible) > 1:
        raise ParserDriftError(
            f"LinkedIn returned multiple exact matches for {requested_name!r}; "
            f"use {id_field_name} to disambiguate."
        )
    return visible[0] if visible else None


async def _exact_company_typeahead_option(
    page: Page,
    requested_name: str,
    *,
    id_field_name: str,
) -> Locator:
    options = page.get_by_role("option")
    matching_indices: list[int] = []
    previous_matches: tuple[int, ...] = ()
    stable_rounds = 0
    for _ in range(25):
        matching_indices.clear()
        for index in range(await options.count()):
            option = options.nth(index)
            if not await option.is_visible():
                continue
            label = re.split(
                r"\s+[•·]\s+",
                " ".join((await option.inner_text()).split()),
                maxsplit=1,
            )[0]
            if label.casefold() == requested_name.casefold():
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
            f"use {id_field_name} instead."
        )
    return options.nth(matching_indices[0])


async def _select_company_facet_names(
    page: Page,
    panel: Locator,
    requested_names: tuple[str, ...],
    facet: _CompanyTypeaheadFacet,
) -> None:
    for requested_name in requested_names:
        region = await _company_facet_region(panel, facet)
        checkbox = await _exact_company_checkbox(
            region,
            requested_name,
            id_field_name=facet.id_field_name,
        )
        if checkbox is not None:
            if not await checkbox.is_checked():
                await checkbox.check()
                await page.wait_for_timeout(200)
            continue

        add_buttons = region.get_by_role(
            "button",
            name=re.compile(
                rf"^{re.escape(facet.add_button_name)}$",
                re.IGNORECASE,
            ),
        )
        visible_buttons = [
            add_buttons.nth(index)
            for index in range(await add_buttons.count())
            if await add_buttons.nth(index).is_visible()
        ]
        if len(visible_buttons) != 1:
            raise ParserDriftError(
                f"LinkedIn's visible {facet.add_button_name.lower()} control was ambiguous."
            )
        await visible_buttons[0].click()
        textbox = region.get_by_placeholder(
            re.compile(
                rf"^{re.escape(facet.add_button_name)}$",
                re.IGNORECASE,
            ),
        )
        try:
            await textbox.first.wait_for(state="visible", timeout=5_000)
            await textbox.first.fill(requested_name)
        except PlaywrightTimeoutError as error:
            raise ParserDriftError(
                f"LinkedIn's visible {facet.add_button_name.lower()} input was unavailable."
            ) from error
        await (
            await _exact_company_typeahead_option(
                page,
                requested_name,
                id_field_name=facet.id_field_name,
            )
        ).click()
        for _ in range(10):
            checkbox = await _exact_company_checkbox(
                region,
                requested_name,
                id_field_name=facet.id_field_name,
            )
            if checkbox is not None and await checkbox.is_checked():
                break
            await page.wait_for_timeout(200)
        else:
            raise ParserDriftError(
                f"LinkedIn did not retain the selected {requested_name!r} Company filter."
            )


def _company_query_array_values(source_url: str, parameter_name: str) -> tuple[str, ...]:
    raw_values = parse_qs(urlsplit(source_url).query).get(parameter_name, ())
    values: list[str] = []
    for raw_value in raw_values:
        try:
            decoded = json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise ParserDriftError(
                f"LinkedIn returned an invalid {parameter_name} Company filter."
            ) from error
        if not isinstance(decoded, list):
            raise ParserDriftError(f"LinkedIn returned an invalid {parameter_name} Company filter.")
        for value in cast(list[object], decoded):
            if not isinstance(value, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,64}",
                value,
            ):
                raise ParserDriftError(
                    f"LinkedIn returned an invalid {parameter_name} Company filter."
                )
            values.append(value)
    return tuple(dict.fromkeys(values))


def _validate_resolved_company_facets(
    filters: CompanySearchFilters,
    resolved: _ResolvedCompanyFacets,
) -> None:
    for direct_ids, requested_names, resolved_ids, id_field_name in (
        (
            filters.location_ids,
            filters.location_names,
            resolved.location_ids,
            "location_ids",
        ),
        (
            filters.industry_ids,
            filters.industry_names,
            resolved.industry_ids,
            "industry_ids",
        ),
    ):
        if not set(direct_ids).issubset(resolved_ids) or len(resolved_ids) < max(
            len(direct_ids),
            len(requested_names),
        ):
            raise ParserDriftError(
                "LinkedIn's submitted Company search did not retain every requested "
                f"{id_field_name.removesuffix('_ids')} filter; use {id_field_name} "
                "for unresolved values."
            )


async def _resolve_named_company_facets(
    browser: BrowserManager,
    page: Page,
    filters: CompanySearchFilters,
) -> _ResolvedCompanyFacets:
    all_filters = page.get_by_role(
        "button",
        name=re.compile(r"^All filters$", re.IGNORECASE),
    )
    try:
        await all_filters.first.wait_for(state="visible", timeout=20_000)
    except PlaywrightTimeoutError as error:
        raise ParserDriftError(
            "LinkedIn Company search has no unique visible All filters control."
        ) from error
    visible_controls = [
        all_filters.nth(index)
        for index in range(await all_filters.count())
        if await all_filters.nth(index).is_visible()
    ]
    if len(visible_controls) != 1:
        raise ParserDriftError("LinkedIn Company search has no unique visible All filters control.")
    await browser.click_visible_control(page, visible_controls[0])

    panel = await _company_filter_panel(page)
    await _select_company_facet_names(
        page,
        panel,
        filters.location_names,
        _LOCATION_TYPEAHEAD,
    )
    await _select_company_facet_names(
        page,
        panel,
        filters.industry_names,
        _INDUSTRY_TYPEAHEAD,
    )
    show_results = panel.get_by_role(
        "link",
        name=re.compile(r"^Show results$", re.IGNORECASE),
    )
    try:
        await show_results.first.wait_for(state="visible", timeout=5_000)
    except PlaywrightTimeoutError as error:
        raise ParserDriftError(
            "LinkedIn's visible Show results control was unavailable for Company search."
        ) from error
    submitted_url = await browser.navigate_via_visible_control(page, show_results.first)
    resolved = _ResolvedCompanyFacets(
        location_ids=_company_query_array_values(
            submitted_url,
            _LOCATION_TYPEAHEAD.query_parameter,
        ),
        industry_ids=_company_query_array_values(
            submitted_url,
            _INDUSTRY_TYPEAHEAD.query_parameter,
        ),
    )
    _validate_resolved_company_facets(filters, resolved)
    return resolved


async def _company_result_region(link: Locator) -> Locator:
    for candidate in (
        link.locator("xpath=ancestor::li[1]"),
        link.locator("xpath=ancestor::*[@data-chameleon-result-urn][1]"),
        link.locator("xpath=ancestor::div[@data-view-name][1]"),
    ):
        if await candidate.count() and await candidate.first.is_visible():
            text = (await candidate.first.inner_text()).strip()
            if text:
                return candidate.first
    return link.locator("..")


async def _extract_company_results(page: Page) -> tuple[CompanySummary, ...]:
    main = page.locator("main")
    links = main.locator('a[href*="/company/"]')
    values: dict[str, CompanySummary] = {}
    for index in range(min(await links.count(), 500)):
        link = links.nth(index)
        if not await link.is_visible():
            continue
        href = await link.get_attribute("href")
        if not href:
            continue
        absolute_url = urljoin("https://www.linkedin.com", href)
        slug = company_slug_from_url(absolute_url)
        if slug is None or slug in values:
            continue
        region = await _company_result_region(link)
        visible_text = (await region.inner_text()).strip()
        lines = _unique_lines(visible_text)
        if not lines:
            continue
        name = await _first_visible_text(region.get_by_role("heading"))
        if not name:
            name = (await link.inner_text()).strip()
        name_lines = _unique_lines(name or "")
        if not name_lines:
            continue
        name = name_lines[0]
        descriptive = [
            line
            for line in lines
            if line != name
            and line.casefold() not in _ACTION_LINES
            and not _FOLLOWER_COUNT_PATTERN.search(line)
            and not _ASSOCIATED_MEMBER_PATTERN.search(line)
        ]
        follower_count = next(
            (
                match.group(0)
                for line in lines
                if (match := _FOLLOWER_COUNT_PATTERN.search(line)) is not None
            ),
            None,
        )
        member_count = next(
            (
                match.group(0)
                for line in lines
                if (match := _ASSOCIATED_MEMBER_PATTERN.search(line)) is not None
            ),
            None,
        )
        values[slug] = CompanySummary(
            company_slug=slug,
            company_url=HttpUrl(canonical_company_url(slug)),
            name=name,
            tagline=descriptive[0] if descriptive else None,
            location=descriptive[1] if len(descriptive) > 1 else None,
            follower_count_text=follower_count,
            associated_member_count_text=member_count,
            visible_text=visible_text,
        )
    return tuple(values.values())


class CompanySearchPage:
    def __init__(self, browser: BrowserManager, *, max_pages: int) -> None:
        if max_pages < 1:
            raise ValueError("Company search page bound must be positive.")
        self._browser = browser
        self._max_pages = max_pages

    @staticmethod
    def build_url(
        request: CompanySearchInput,
        *,
        page_index: int,
        resolved: _ResolvedCompanyFacets = _EMPTY_RESOLVED_COMPANY_FACETS,
    ) -> str:
        return _build_company_search_url(
            request,
            page_index=page_index,
            resolved=resolved,
        )

    async def collect(
        self,
        request: CompanySearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[CompanySummary, ...], CompanySearchCoverage, str, str]:
        limit = request.page_size if result_limit is None else result_limit
        if limit < 1:
            raise ValueError("Company search result limit must be positive.")
        companies: dict[str, CompanySummary] = {}
        captured_pages: list[tuple[str, str]] = []
        resolved = _ResolvedCompanyFacets()
        pages_visited = 0
        stop_reason = StopReason.SAFETY_BOUND
        async with self._browser.page() as page:
            if request.filters.location_names or request.filters.industry_names:
                await self._browser.navigate(
                    page,
                    self.build_url(request, page_index=1),
                )
                resolved = await _resolve_named_company_facets(
                    self._browser,
                    page,
                    request.filters,
                )

            for page_index in range(1, self._max_pages + 1):
                target = self.build_url(
                    request,
                    page_index=page_index,
                    resolved=resolved,
                )
                await self._browser.navigate(page, target)
                await _expand_and_scroll(page)
                rendered_state = await _wait_for_company_search_state(page)
                visible_text = (await page.locator("main").inner_text()).strip()
                if not visible_text:
                    raise ParserDriftError("LinkedIn Company search returned no visible text.")
                pages_visited += 1
                captured_pages.append((target, visible_text))
                before = len(companies)
                for company in await _extract_company_results(page):
                    companies[company.company_slug] = company
                    if len(companies) >= limit:
                        stop_reason = StopReason.RESULT_LIMIT
                        break
                if len(companies) >= limit:
                    break
                if len(companies) == before:
                    if rendered_state is CollectionSettleOutcome.EXPLICIT_END:
                        stop_reason = StopReason.NO_NEW_RESULTS
                    break
                if page_index == self._max_pages:
                    stop_reason = StopReason.SAFETY_BOUND

        captured_at = datetime.now(UTC)
        values = tuple(companies.values())[:limit]
        coverage = CompanySearchCoverage(
            query=request.query,
            filters=request.filters,
            pages_visited=pages_visited,
            result_count=len(values),
            max_results=limit,
            stop_reason=stop_reason,
            captured_at=captured_at,
        )
        combined_text = "\n\n".join(
            f"--- source: {source_url} ---\n{text}" for source_url, text in captured_pages
        )
        source_url = captured_pages[0][0]
        return values, coverage, combined_text, source_url


async def _company_heading(main: Locator, page: Page) -> str:
    heading = await _first_visible_text(main.get_by_role("heading", level=1))
    if heading:
        return _unique_lines(heading)[0]
    title = await page.title()
    candidate = re.split(r"\s*[|·]\s*LinkedIn", title, maxsplit=1)[0].strip()
    main_text = (await main.inner_text()).strip()
    if not candidate or candidate not in {line.strip() for line in main_text.splitlines()}:
        raise ParserDriftError("LinkedIn company profile has no exact visible company name.")
    return candidate


async def _top_company_region(main: Locator, name: str) -> Locator:
    headings = main.get_by_role(
        "heading",
        name=re.compile(rf"^{re.escape(name)}$"),
    )
    for index in range(await headings.count()):
        heading = headings.nth(index)
        if not await heading.is_visible():
            continue
        region = heading.locator("..")
        for _ in range(8):
            lines = _unique_lines((await region.inner_text()).strip())
            if name in lines and any(line != name for line in lines):
                return region
            region = region.locator("..")
    raise ParserDriftError("LinkedIn company profile has no unique visible introduction.")


def _line_after_label(lines: list[str], label: str) -> str | None:
    for index, line in enumerate(lines):
        if line.casefold().rstrip(":") == label.casefold():
            return lines[index + 1] if index + 1 < len(lines) else None
    return None


async def _about_region(main: Locator) -> Locator:
    candidates = main.get_by_role(
        "heading",
        name=re.compile(r"^(?:About|Overview)$", re.IGNORECASE),
    )
    for attempt in range(_INITIAL_RESULTS_POLL_ATTEMPTS):
        regions: dict[
            tuple[str, tuple[float, float, float, float] | None],
            tuple[Locator, bool],
        ] = {}
        for index in range(await candidates.count()):
            heading = candidates.nth(index)
            if not await heading.is_visible():
                continue
            ancestor = heading.locator("xpath=ancestor::section[1]")
            region = ancestor.first if await ancestor.count() else heading.locator("..")
            if not await region.is_visible():
                continue
            text = (await region.inner_text()).strip()
            if not text:
                continue
            lines = _unique_lines(text)
            labels = {line.casefold().rstrip(":") for line in lines}
            contains_about_field = any(label.casefold() in labels for label in _ABOUT_FIELD_LABELS)
            box = await region.bounding_box()
            bounds = (
                (
                    box["x"],
                    box["y"],
                    box["width"],
                    box["height"],
                )
                if box is not None
                else None
            )
            regions.setdefault(("\n".join(lines), bounds), (region, contains_about_field))
        if len(regions) == 1:
            return next(iter(regions.values()))[0]
        qualified = [region for region, has_field in regions.values() if has_field]
        if len(qualified) == 1:
            return qualified[0]
        if attempt + 1 < _INITIAL_RESULTS_POLL_ATTEMPTS:
            await main.page.wait_for_timeout(_INITIAL_RESULTS_POLL_DELAY_MS)
    raise ParserDriftError("LinkedIn company About page has no unique visible About section.")


def _about_description(visible_text: str) -> str | None:
    lines = visible_text.strip().splitlines()
    while lines and lines[0].strip().casefold() in {"about", "overview"}:
        lines.pop(0)
    value = "\n".join(lines).strip()
    boundaries = tuple(
        match.start()
        for label in _ABOUT_FIELD_LABELS
        if (
            match := re.search(
                rf"(?im)^\s*{re.escape(label)}:?\s*$",
                value,
            )
        )
        is not None
    )
    if boundaries:
        value = value[: min(boundaries)]
    value = value.strip()
    return value or None


async def _about_website_url(region: Locator) -> HttpUrl | None:
    anchors = region.locator("a[href]")
    values: list[HttpUrl] = []
    for index in range(min(await anchors.count(), 100)):
        link = anchors.nth(index)
        if not await link.is_visible():
            continue
        href = await link.get_attribute("href")
        label = (await link.inner_text()).strip()
        if not href:
            continue
        absolute_url = urljoin("https://www.linkedin.com", href)
        parsed = urlsplit(absolute_url)
        host = (parsed.hostname or "").casefold()
        if host in {"linkedin.com", "www.linkedin.com"} and parsed.path.startswith(
            "/redir/redirect"
        ):
            redirect_targets = parse_qs(parsed.query).get("url", ())
            if len(redirect_targets) == 1:
                absolute_url = redirect_targets[0]
                parsed = urlsplit(absolute_url)
                host = (parsed.hostname or "").casefold()
        if "website" not in label.casefold() and host in {"linkedin.com", "www.linkedin.com"}:
            continue
        value = HttpUrl(absolute_url)
        if value not in values:
            values.append(value)
    if len(values) > 1:
        raise ParserDriftError("LinkedIn company About page exposes multiple website targets.")
    return values[0] if values else None


def _evidence_source_url(
    captures: list[CompanyProfilePageCapture],
    *,
    field: str,
    quote: str,
    preferred_url: HttpUrl,
) -> HttpUrl:
    preferred = next(
        (
            capture.source_url
            for capture in captures
            if str(capture.source_url) == str(preferred_url) and quote in capture.captured_text
        ),
        None,
    )
    if preferred is not None:
        return preferred
    matching = next(
        (capture.source_url for capture in captures if quote in capture.captured_text),
        None,
    )
    if matching is None:
        raise ParserDriftError(f"Company field {field!r} has no exact captured-source quote.")
    return matching


class CompanyProfilePage:
    def __init__(self, browser: BrowserManager) -> None:
        self._browser = browser

    async def read(
        self,
        request: CompanyGetInput,
    ) -> tuple[CompanyProfileObservation, tuple[CompanyProfilePageCapture, ...]]:
        captures: list[CompanyProfilePageCapture] = []
        async with self._browser.page() as page:
            await self._browser.navigate(page, canonical_company_url(request.company_slug))
            await _expand_and_scroll(page)
            overview_main = page.locator("main")
            name = await _company_heading(overview_main, page)
            top = await _top_company_region(overview_main, name)
            top_text = (await top.inner_text()).strip()
            actual_slug = company_slug_from_url(page.url) or request.company_slug
            company_url = canonical_company_url(actual_slug)
            overview_text = (await overview_main.inner_text()).strip()
            captures.append(
                CompanyProfilePageCapture(
                    source_url=HttpUrl(company_url),
                    page_kind="overview",
                    captured_text=overview_text,
                    captured_at=datetime.now(UTC),
                )
            )
            about_url = canonical_company_url(actual_slug, "about")
            await self._browser.navigate(page, about_url)
            await _expand_and_scroll(page)
            about_main = page.locator("main")
            about_name = await _company_heading(about_main, page)
            about_slug = company_slug_from_url(page.url) or actual_slug
            if about_name != name or about_slug != actual_slug:
                raise ParserDriftError(
                    "LinkedIn company About page conflicts with the overview identity."
                )
            about_region = await _about_region(about_main)
            about_region_text = (await about_region.inner_text()).strip()
            about_text = (await about_main.inner_text()).strip()
            website_url = await _about_website_url(about_region)
            captures.append(
                CompanyProfilePageCapture(
                    source_url=HttpUrl(about_url),
                    page_kind="about",
                    captured_text=about_text,
                    captured_at=datetime.now(UTC),
                )
            )

        all_lines = _unique_lines("\n".join(capture.captured_text for capture in captures))
        description = _about_description(about_region_text)
        company_size_line = _line_after_label(all_lines, "Company size")
        company_size_match = _COMPANY_SIZE_PATTERN.search(
            company_size_line or ""
        ) or _COMPANY_SIZE_PATTERN.search("\n".join(all_lines))
        all_text = "\n".join(all_lines)
        member_match = _EXPLICIT_ASSOCIATED_MEMBER_PATTERN.search(
            all_text
        ) or _ASSOCIATED_MEMBER_PATTERN.search(top_text)
        follower_match = _FOLLOWER_COUNT_PATTERN.search(top_text)
        specialties_text = _line_after_label(all_lines, "Specialties")
        specialties = tuple(
            value.strip() for value in (specialties_text or "").split(",") if value.strip()
        )
        captured_at = datetime.now(UTC)
        coverage = CompanyProfileCoverage(captured_at=captured_at)
        combined_text = "\n\n".join(
            f"--- source: {capture.source_url} ---\n{capture.captured_text}" for capture in captures
        )
        main_url = captures[0].source_url
        about_source_url = captures[1].source_url
        tagline = next(
            (
                line
                for line in _unique_lines(top_text)[1:]
                if line != name
                and line.casefold() not in _ACTION_LINES
                and not _FOLLOWER_COUNT_PATTERN.search(line)
                and not _ASSOCIATED_MEMBER_PATTERN.search(line)
            ),
            None,
        )
        values = (
            ("name", name, main_url),
            ("tagline", tagline, main_url),
            ("description", description, about_source_url),
            ("industry", _line_after_label(all_lines, "Industry"), about_source_url),
            (
                "company_size_range",
                company_size_match.group(0) if company_size_match else None,
                about_source_url,
            ),
            (
                "associated_member_count_text",
                member_match.group(0) if member_match else None,
                main_url,
            ),
            (
                "follower_count_text",
                follower_match.group(0) if follower_match else None,
                main_url,
            ),
            ("headquarters", _line_after_label(all_lines, "Headquarters"), about_source_url),
            ("organization_type", _line_after_label(all_lines, "Type"), about_source_url),
            ("founded_text", _line_after_label(all_lines, "Founded"), about_source_url),
        )
        evidence = tuple(
            CompanyProfileEvidence(
                field=field,
                quote=value,
                source_url=_evidence_source_url(
                    captures,
                    field=field,
                    quote=value,
                    preferred_url=source_url,
                ),
            )
            for field, value, source_url in values
            if value
        )
        observation = CompanyProfileObservation(
            company_slug=actual_slug,
            company_url=HttpUrl(company_url),
            name=name,
            tagline=tagline,
            description=description,
            website_url=website_url,
            industry=_line_after_label(all_lines, "Industry"),
            company_size_range=(company_size_match.group(0) if company_size_match else None),
            associated_member_count_text=(member_match.group(0) if member_match else None),
            follower_count_text=(follower_match.group(0) if follower_match else None),
            headquarters=_line_after_label(all_lines, "Headquarters"),
            organization_type=_line_after_label(all_lines, "Type"),
            founded_text=_line_after_label(all_lines, "Founded"),
            specialties=specialties,
            visible_text=combined_text,
            evidence=evidence,
            coverage=coverage,
            captured_at=captured_at,
        )
        return observation, tuple(captures)
