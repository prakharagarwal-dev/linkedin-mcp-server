"""Visible LinkedIn page implementation for `linkedin_mcp.tools.posts.search.page`."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import HttpUrl

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools._shared.models import StopReason
from linkedin_mcp.tools.posts.models.post_author import PostAuthor
from linkedin_mcp.tools.posts.search.models.post_content_type import PostContentType
from linkedin_mcp.tools.posts.search.models.post_search_content_type import PostSearchContentType
from linkedin_mcp.tools.posts.search.models.post_search_coverage import PostSearchCoverage
from linkedin_mcp.tools.posts.search.models.post_search_date import PostSearchDate
from linkedin_mcp.tools.posts.search.models.post_search_filters import PostSearchFilters
from linkedin_mcp.tools.posts.search.models.post_search_input import PostSearchInput
from linkedin_mcp.tools.posts.search.models.post_search_posted_by import PostSearchPostedBy
from linkedin_mcp.tools.posts.search.models.post_search_sort import PostSearchSort
from linkedin_mcp.tools.posts.search.models.post_summary import PostSummary
from linkedin_mcp.tools.posts.surface import (
    COLLECTION_POLL_DELAY_MS,
    COUNT_PATTERNS,
    POST_ACTION_LINES,
    POST_MENU_PATTERN,
    POST_REGION_SELECTOR,
    UnsupportedPostAuthorIdentityError,
    post_body_boxes,
    post_content_fields,
    post_engagement,
    post_header_fields,
    post_reference_for_region,
    prepare_visible_content,
    unique_lines,
)
from linkedin_mcp.ui import LinkedInLocator as Locator
from linkedin_mcp.ui import LinkedInPage as Page
from linkedin_mcp.ui import LinkedInPlaywright
from linkedin_mcp.ui.collections import (
    CollectionSettleOutcome,
    visible_locator_signature,
    wait_for_collection_initial_state,
)
from linkedin_mcp.ui.urls import (
    canonical_post_url,
)

_CONTENT_SEARCH_URL = "https://www.linkedin.com/search/results/content/"

_POST_CONTENT_CODES = {
    PostSearchContentType.VIDEOS: "videos",
    PostSearchContentType.IMAGES: "photos",
    PostSearchContentType.JOB_POSTS: "jobs",
    PostSearchContentType.LIVE_VIDEOS: "liveVideos",
    PostSearchContentType.DOCUMENTS: "documents",
}

_POST_DATE_CODES = {
    PostSearchDate.PAST_24_HOURS: "past-24h",
    PostSearchDate.PAST_WEEK: "past-week",
    PostSearchDate.PAST_MONTH: "past-month",
}

_POSTED_BY_CODES = {
    PostSearchPostedBy.ME: "me",
    PostSearchPostedBy.FIRST_CONNECTIONS: "first",
    PostSearchPostedBy.PEOPLE_YOU_FOLLOW: "following",
}

_POST_SEARCH_END_PATTERN = re.compile(
    r"^(?:no (?:matching )?(?:posts|results)(?: found| to show)?|"
    r"we couldn(?:'|\N{RIGHT SINGLE QUOTATION MARK})t find any results)"
    r"(?:[.!])?$",
    re.IGNORECASE,
)

_INITIAL_RESULTS_POLL_ATTEMPTS = 20


@dataclass(frozen=True, slots=True)
class _ResolvedPostFacets:
    from_member_ids: tuple[str, ...] = ()
    from_company_ids: tuple[str, ...] = ()
    mentioning_member_ids: tuple[str, ...] = ()
    mentioning_company_ids: tuple[str, ...] = ()
    author_industry_ids: tuple[str, ...] = ()
    author_company_ids: tuple[str, ...] = ()


_EMPTY_RESOLVED_POST_FACETS = _ResolvedPostFacets()


@dataclass(frozen=True, slots=True)
class _PostFacetSpec:
    heading: str
    add_button_name: str
    ids_field: str
    names_field: str
    parameter: str


@dataclass(frozen=True, slots=True)
class _VisiblePostBatch:
    posts: tuple[PostSummary, ...]
    unsupported_result_count: int


_POST_FACETS = (
    _PostFacetSpec(
        "From member",
        "Add a person",
        "from_member_ids",
        "from_member_names",
        "fromMember",
    ),
    _PostFacetSpec(
        "From company",
        "Add a company's name",
        "from_company_ids",
        "from_company_names",
        "fromOrganization",
    ),
    _PostFacetSpec(
        "Mentioning member",
        "Add a person",
        "mentioning_member_ids",
        "mentioning_member_names",
        "mentionsMember",
    ),
    _PostFacetSpec(
        "Mentioning company",
        "Add a company's name",
        "mentioning_company_ids",
        "mentioning_company_names",
        "mentionsOrganization",
    ),
    _PostFacetSpec(
        "Author industry",
        "Add an industry",
        "author_industry_ids",
        "author_industry_names",
        "authorIndustry",
    ),
    _PostFacetSpec(
        "Author company",
        "Add a company",
        "author_company_ids",
        "author_company_names",
        "authorCompany",
    ),
)


async def _first_visible_text(locator: Locator) -> str | None:
    for index in range(min(await locator.count(), 100)):
        candidate = locator.nth(index)
        if not await candidate.is_visible():
            continue
        try:
            text = (await candidate.inner_text()).strip()
        except PlaywrightError:
            text = (await candidate.text_content() or "").strip()
        if not text:
            text = (await candidate.get_attribute("aria-label") or "").strip()
        if text:
            return text
    return None


async def _visible_post_signature(page: Page) -> tuple[str, ...]:
    return await visible_locator_signature(
        page.locator("main").locator(POST_REGION_SELECTOR),
        identity_attributes=("data-post-urn", "data-urn", "data-entity-urn"),
    )


async def _content_has_explicit_end(page: Page, pattern: re.Pattern[str]) -> bool:
    main = page.locator("main")
    if await main.count() == 0:
        return False
    text = (await main.first.inner_text()).strip()
    return any(pattern.fullmatch(line.strip()) for line in text.splitlines() if line.strip())


async def _wait_for_post_search_state(page: Page) -> CollectionSettleOutcome:
    result = await wait_for_collection_initial_state(
        page,
        read_signature=lambda: _visible_post_signature(page),
        read_explicit_end=lambda: _content_has_explicit_end(
            page,
            _POST_SEARCH_END_PATTERN,
        ),
        attempts=_INITIAL_RESULTS_POLL_ATTEMPTS,
        delay_ms=COLLECTION_POLL_DELAY_MS,
    )
    return result.outcome


async def _expand_search_post_body(page: Page, region: Locator) -> None:
    source_url = page.url
    bodies = await post_body_boxes(region)
    if len(bodies) > 2:
        raise ParserDriftError("LinkedIn post search exposed too many nested post bodies.")
    for body in bodies:
        for _ in range(5):
            buttons = body.locator('[data-testid="expandable-text-button"]').or_(
                body.get_by_role(
                    "button",
                    name=re.compile(r"^(?:see more|show more)(?:\b|$)", re.IGNORECASE),
                )
            )
            visible = [
                buttons.nth(index)
                for index in range(min(await buttons.count(), 5))
                if await buttons.nth(index).is_visible()
            ]
            if not visible:
                break
            expandable = visible[0]
            button_name = " ".join(
                (
                    (await expandable.inner_text()).strip(),
                    (await expandable.get_attribute("aria-label") or "").strip(),
                )
            )
            if re.search(r"\b(?:comments?|repl(?:y|ies))\b", button_name, re.IGNORECASE):
                break
            before_text = (await body.inner_text()).strip()
            try:
                await expandable.click(timeout=2_000)
                await page.wait_for_timeout(100)
            except PlaywrightTimeoutError:
                if not await expandable.is_visible():
                    continue
                # Current search cards can paint their text layer over the visible
                # expansion button. Keyboard activation preserves the same exact,
                # user-facing control without bypassing its semantics.
                await expandable.focus()
                await expandable.press("Enter")
                await page.wait_for_timeout(100)
            if page.url != source_url:
                raise ParserDriftError("A LinkedIn content expansion unexpectedly navigated away.")
            after_text = (await body.inner_text()).strip()
            remaining = body.locator('[data-testid="expandable-text-button"]').or_(
                body.get_by_role(
                    "button",
                    name=re.compile(r"^(?:see more|show more)(?:\b|$)", re.IGNORECASE),
                )
            )
            remaining_visible = False
            for index in range(min(await remaining.count(), 5)):
                if await remaining.nth(index).is_visible():
                    remaining_visible = True
                    break
            if before_text == after_text and remaining_visible:
                raise ParserDriftError("LinkedIn post-search text could not be fully expanded.")
        else:
            raise ParserDriftError(
                "LinkedIn post search exceeded the per-post text-expansion safety bound."
            )


def _json_array(values: tuple[str, ...]) -> str:
    return json.dumps(values, separators=(",", ":"))


def _add_post_search_filters(
    parameters: dict[str, str],
    filters: PostSearchFilters,
    resolved: _ResolvedPostFacets,
) -> None:
    if filters.sort_by is PostSearchSort.LATEST:
        parameters["sortBy"] = _json_array(("date_posted",))
    if filters.date_posted is not PostSearchDate.ANY_TIME:
        parameters["datePosted"] = _json_array((_POST_DATE_CODES[filters.date_posted],))
    if filters.content_type is not None:
        parameters["contentType"] = _json_array((_POST_CONTENT_CODES[filters.content_type],))
    if filters.posted_by:
        parameters["postedBy"] = _json_array(
            tuple(_POSTED_BY_CODES[value] for value in filters.posted_by)
        )
    if filters.author_keywords:
        parameters["authorJobTitle"] = json.dumps(filters.author_keywords)
    for spec in _POST_FACETS:
        direct = cast(tuple[str, ...], getattr(filters, spec.ids_field))
        resolved_values = cast(tuple[str, ...], getattr(resolved, spec.ids_field))
        values = tuple(dict.fromkeys((*direct, *resolved_values)))
        if values:
            parameters[spec.parameter] = _json_array(values)


def _build_post_search_url(
    request: PostSearchInput,
    *,
    page_index: int,
    resolved: _ResolvedPostFacets = _EMPTY_RESOLVED_POST_FACETS,
) -> str:
    parameters = {
        "origin": "FACETED_SEARCH",
        "page": str(page_index),
    }
    if request.query:
        parameters["keywords"] = request.query
    _add_post_search_filters(parameters, request.filters, resolved)
    return f"{_CONTENT_SEARCH_URL}?{urlencode(parameters)}"


async def _post_filter_panel(page: Page) -> Locator | None:
    show_results = page.get_by_role(
        "link",
        name=re.compile(r"^show results$", re.IGNORECASE),
    )
    for index in range(await show_results.count()):
        control = show_results.nth(index)
        if not await control.is_visible():
            continue
        region = control
        for _ in range(12):
            region = region.locator("..")
            if (
                await region.get_by_text("Author Keywords", exact=True).count()
                and await region.get_by_text("From member", exact=True).count()
            ):
                return region
    return None


async def _post_facet_region(panel: Locator, spec: _PostFacetSpec) -> Locator:
    headings = panel.get_by_text(
        re.compile(rf"^{re.escape(spec.heading)}$", re.IGNORECASE),
        exact=True,
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
                name=spec.add_button_name,
                exact=True,
            )
            visible_count = 0
            for button_index in range(await buttons.count()):
                if await buttons.nth(button_index).is_visible():
                    visible_count += 1
            if visible_count == 1:
                return region
    raise ParserDriftError(
        f"LinkedIn post filters have no unique visible {spec.heading!r} category."
    )


async def _selected_post_facet(
    region: Locator,
    requested_name: str,
) -> Locator | None:
    candidates = region.get_by_role(
        "checkbox",
        name=re.compile(
            rf"^{re.escape(' '.join(requested_name.split()))}$",
            re.IGNORECASE,
        ),
    )
    visible = [
        candidates.nth(index)
        for index in range(await candidates.count())
        if await candidates.nth(index).is_visible()
    ]
    if len(visible) > 1:
        raise ParserDriftError(
            f"LinkedIn returned multiple exact selected matches for {requested_name!r}; "
            "supply an exact facet ID."
        )
    return visible[0] if visible else None


async def _exact_post_option(
    page: Page,
    requested_name: str,
) -> Locator:
    exact_text = page.get_by_text(
        re.compile(
            rf"^{re.escape(' '.join(requested_name.split()))}$",
            re.IGNORECASE,
        ),
        exact=True,
    )
    options = page.get_by_role("option").filter(has=exact_text)
    matches: list[Locator] = []
    previous_count = -1
    stable_rounds = 0
    for _ in range(25):
        matches = [
            options.nth(index)
            for index in range(await options.count())
            if await options.nth(index).is_visible()
        ]
        if matches and len(matches) == previous_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
        previous_count = len(matches)
        if matches and stable_rounds >= 2:
            break
        await page.wait_for_timeout(200)
    if len(matches) != 1:
        qualifier = "no" if not matches else "multiple"
        raise ParserDriftError(
            f"LinkedIn returned {qualifier} exact visible matches for "
            f"{requested_name!r}; supply an exact facet ID."
        )
    return matches[0]


async def _select_post_facet_names(
    page: Page,
    panel: Locator,
    requested_names: tuple[str, ...],
    spec: _PostFacetSpec,
) -> None:
    for requested_name in requested_names:
        region = await _post_facet_region(panel, spec)
        selected = await _selected_post_facet(region, requested_name)
        if selected is not None:
            if not await selected.is_checked():
                await selected.check()
            continue
        add_buttons = region.get_by_role(
            "button",
            name=spec.add_button_name,
            exact=True,
        )
        visible_buttons = [
            add_buttons.nth(index)
            for index in range(await add_buttons.count())
            if await add_buttons.nth(index).is_visible()
        ]
        if len(visible_buttons) != 1:
            raise ParserDriftError(
                f"LinkedIn's visible {spec.add_button_name.lower()} control was ambiguous."
            )
        await visible_buttons[0].click()
        textbox = region.get_by_placeholder(spec.add_button_name, exact=True)
        try:
            await textbox.first.wait_for(state="visible", timeout=5_000)
            await textbox.first.fill(requested_name)
        except PlaywrightTimeoutError as error:
            raise ParserDriftError(
                f"LinkedIn's visible {spec.add_button_name.lower()} input was unavailable."
            ) from error
        await (await _exact_post_option(page, requested_name)).click()
        await page.wait_for_timeout(200)


def _query_array_values(source_url: str, parameter_name: str) -> tuple[str, ...]:
    raw_values = parse_qs(urlsplit(source_url).query).get(parameter_name, ())
    values: list[str] = []
    for raw_value in raw_values:
        try:
            decoded = cast(object, json.loads(raw_value))
        except json.JSONDecodeError as error:
            raise ParserDriftError(
                f"LinkedIn returned an invalid {parameter_name} filter value."
            ) from error
        if not isinstance(decoded, list):
            raise ParserDriftError(f"LinkedIn returned an invalid {parameter_name} filter value.")
        for value in cast(list[object], decoded):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
                raise ParserDriftError(
                    f"LinkedIn returned an invalid {parameter_name} filter value."
                )
            values.append(value)
    return tuple(dict.fromkeys(values))


def _resolved_post_facets_from_url(source_url: str) -> _ResolvedPostFacets:
    values = {
        spec.ids_field: _query_array_values(source_url, spec.parameter) for spec in _POST_FACETS
    }
    return _ResolvedPostFacets(
        from_member_ids=values["from_member_ids"],
        from_company_ids=values["from_company_ids"],
        mentioning_member_ids=values["mentioning_member_ids"],
        mentioning_company_ids=values["mentioning_company_ids"],
        author_industry_ids=values["author_industry_ids"],
        author_company_ids=values["author_company_ids"],
    )


def _validate_resolved_post_facets(
    filters: PostSearchFilters,
    resolved: _ResolvedPostFacets,
) -> None:
    for spec in _POST_FACETS:
        direct = cast(tuple[str, ...], getattr(filters, spec.ids_field))
        requested = cast(tuple[str, ...], getattr(filters, spec.names_field))
        values = cast(tuple[str, ...], getattr(resolved, spec.ids_field))
        if len(values) < len(direct) + len(requested):
            raise ParserDriftError(
                "LinkedIn's submitted Posts search did not retain every requested "
                f"{spec.heading} filter; use {spec.ids_field} for unresolved values."
            )


async def _resolve_post_facets(
    playwright: LinkedInPlaywright,
    page: Page,
    filters: PostSearchFilters,
) -> _ResolvedPostFacets:
    all_filters = page.get_by_role(
        "button",
        name=re.compile(r"all filters", re.IGNORECASE),
    )
    try:
        await all_filters.first.wait_for(state="visible", timeout=10_000)
    except PlaywrightTimeoutError as error:
        raise ParserDriftError(
            "LinkedIn post search has no visible All filters control."
        ) from error
    visible = [
        all_filters.nth(index)
        for index in range(await all_filters.count())
        if await all_filters.nth(index).is_visible()
    ]
    if len(visible) != 1:
        raise ParserDriftError("LinkedIn post search has no unique visible All filters control.")
    await visible[0].click()
    panel: Locator | None = None
    for _ in range(50):
        panel = await _post_filter_panel(page)
        if panel is not None:
            break
        await page.wait_for_timeout(100)
    if panel is None:
        raise ParserDriftError("LinkedIn's visible Posts All-filters panel was unavailable.")
    for spec in _POST_FACETS:
        names = cast(tuple[str, ...], getattr(filters, spec.names_field))
        await _select_post_facet_names(page, panel, names, spec)
    show_results = panel.get_by_role(
        "link",
        name=re.compile(r"^show results$", re.IGNORECASE),
    )
    try:
        await show_results.first.wait_for(state="visible", timeout=5_000)
    except PlaywrightTimeoutError as error:
        raise ParserDriftError(
            "LinkedIn's visible Show results control was unavailable for Posts search."
        ) from error
    submitted_url = await show_results.first.click_and_wait_for_navigation()
    resolved = _resolved_post_facets_from_url(submitted_url)
    _validate_resolved_post_facets(filters, resolved)
    return resolved


def _requires_post_facet_resolution(filters: PostSearchFilters) -> bool:
    return any(getattr(filters, spec.names_field) for spec in _POST_FACETS)


async def _post_text(region: Locator, *, author: PostAuthor) -> str | None:
    for selector in (
        "[data-post-text]",
        '[data-testid="post-text"]',
        '[data-testid="expandable-text-box"]',
        ".update-components-text",
        ".feed-shared-update-v2__description",
    ):
        text = await _first_visible_text(region.locator(selector))
        if text:
            return text
    lines = unique_lines((await region.inner_text()).strip())
    content = [
        line
        for line in lines
        if line != author.name
        and line != author.headline
        and line.casefold() not in POST_ACTION_LINES
        and not any(pattern.search(line) for pattern in COUNT_PATTERNS.values())
        and not re.fullmatch(
            r"(?:\d+\s*[smhdw]|just now|edited)",
            line,
            re.IGNORECASE,
        )
    ]
    return "\n".join(content) if content else None


async def _post_summary_from_region(
    region: Locator,
    *,
    known_reference: str | None = None,
) -> PostSummary | None:
    reference = known_reference or await post_reference_for_region(region)
    visible_text = (await region.inner_text()).strip()
    if reference is None or not visible_text:
        return None
    header = await post_header_fields(region)
    body_boxes = await post_body_boxes(region)
    if len(body_boxes) > 2:
        raise ParserDriftError("LinkedIn post search exposed too many nested post bodies.")
    body = body_boxes[0] if body_boxes else None
    text = (await body.inner_text()).strip() if body is not None else None
    if text == "":
        text = None
    if text is None:
        text = await _post_text(region, author=header.author)
    engagement = await post_engagement(region)
    content_type = PostContentType.REPOST
    if len(body_boxes) < 2:
        content_type = (await post_content_fields(region, body)).content_type
    return PostSummary(
        post_ref=reference,
        post_url=HttpUrl(canonical_post_url(reference)),
        author=header.author,
        text=text,
        posted_at_text=header.posted_at_text,
        content_type=content_type,
        reaction_count_text=engagement.reaction_count_text,
        comment_count_text=engagement.comment_count_text,
        repost_count_text=engagement.repost_count_text,
        visible_text=visible_text,
    )


async def _visible_posts(
    page: Page,
    *,
    result_limit: int,
    excluded_refs: frozenset[str],
) -> _VisiblePostBatch:
    main = page.locator("main")
    candidates = main.locator(POST_REGION_SELECTOR)
    inventory: list[tuple[int, str]] = []
    observed_refs: set[str] = set(excluded_refs)
    unsupported_result_count = 0
    for index in range(min(await candidates.count(), 500)):
        candidate = candidates.nth(index)
        if not await candidate.is_visible():
            continue
        reference = await post_reference_for_region(candidate)
        if reference is None:
            menus = candidate.get_by_role("button", name=POST_MENU_PATTERN)
            has_visible_post_menu = False
            for menu_index in range(min(await menus.count(), 3)):
                if await menus.nth(menu_index).is_visible():
                    has_visible_post_menu = True
                    break
            if has_visible_post_menu:
                unsupported_result_count += 1
            continue
        if reference in observed_refs:
            continue
        observed_refs.add(reference)
        inventory.append((index, reference))
        if len(inventory) >= result_limit:
            break

    # Expanding a high-ranked card makes the virtualized cards below it move and
    # can detach them. Capture the ordered identity prefix first, then parse that
    # prefix bottom-up so each lower card is retained until it has been read.
    values: dict[str, PostSummary] = {}
    for index, reference in reversed(inventory):
        candidate = candidates.nth(index)
        if not await candidate.is_visible():
            raise ParserDriftError(
                "LinkedIn post search changed an inventoried result before extraction."
            )
        await _expand_search_post_body(page, candidate)
        stable_reference = await post_reference_for_region(candidate)
        if stable_reference != reference:
            raise ParserDriftError(
                "LinkedIn post search changed an exact result identity during extraction."
            )
        try:
            summary = await _post_summary_from_region(
                candidate,
                known_reference=reference,
            )
        except UnsupportedPostAuthorIdentityError:
            unsupported_result_count += 1
            continue
        if summary is not None:
            values[reference] = summary
    return _VisiblePostBatch(
        posts=tuple(values[reference] for _, reference in inventory if reference in values),
        unsupported_result_count=unsupported_result_count,
    )


class PostSearchPage:
    def __init__(self, playwright: LinkedInPlaywright, *, max_pages: int) -> None:
        if max_pages < 1:
            raise ValueError("Post search page bound must be positive.")
        self._playwright = playwright
        self._max_pages = max_pages

    @staticmethod
    def build_url(request: PostSearchInput, *, page_index: int) -> str:
        return _build_post_search_url(request, page_index=page_index)

    async def collect(
        self,
        request: PostSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[PostSummary, ...], PostSearchCoverage, str, str]:
        limit = request.page_size if result_limit is None else result_limit
        if limit < 1:
            raise ValueError("Post-search result limit must be positive.")
        posts: dict[str, PostSummary] = {}
        captures: list[tuple[str, str]] = []
        resolved = _ResolvedPostFacets()
        pages_visited = 0
        unsupported_result_count = 0
        stop_reason = StopReason.SAFETY_BOUND
        async with self._playwright.page() as page:
            if _requires_post_facet_resolution(request.filters):
                await page.goto(_build_post_search_url(request, page_index=1))
                resolved = await _resolve_post_facets(
                    self._playwright,
                    page,
                    request.filters,
                )
            for page_index in range(1, self._max_pages + 1):
                target = _build_post_search_url(
                    request,
                    page_index=page_index,
                    resolved=resolved,
                )
                await page.goto(target)
                rendered_state = await _wait_for_post_search_state(page)
                await prepare_visible_content(page)
                visible_batch = await _visible_posts(
                    page,
                    result_limit=limit - len(posts),
                    excluded_refs=frozenset(posts),
                )
                visible_posts = visible_batch.posts
                unsupported_result_count += visible_batch.unsupported_result_count
                captured_text = (await page.locator("main").inner_text()).strip()
                if not captured_text:
                    raise ParserDriftError("LinkedIn post search returned no visible text.")
                missing_snapshots = tuple(
                    post.visible_text
                    for post in visible_posts
                    if post.visible_text not in captured_text
                )
                if missing_snapshots:
                    captured_text = (
                        f"{captured_text}\n\n--- exact visible post-card snapshots ---\n"
                        + "\n\n".join(missing_snapshots)
                    )
                pages_visited += 1
                captures.append((target, captured_text))
                before = len(posts)
                for post in visible_posts:
                    posts.setdefault(post.post_ref, post)
                    if len(posts) >= limit:
                        stop_reason = StopReason.RESULT_LIMIT
                        break
                if len(posts) >= limit:
                    break
                if visible_batch.unsupported_result_count:
                    stop_reason = StopReason.VISIBLE_PAGE_COMPLETE
                    break
                if len(posts) == before:
                    if rendered_state is CollectionSettleOutcome.EXPLICIT_END:
                        stop_reason = StopReason.NO_NEW_RESULTS
                    break
        captured_at = datetime.now(UTC)
        values = tuple(posts.values())[:limit]
        coverage = PostSearchCoverage(
            query=request.query,
            filters=request.filters,
            pages_visited=pages_visited,
            result_count=len(values),
            unsupported_result_count=unsupported_result_count,
            max_results=limit,
            stop_reason=stop_reason,
            captured_at=captured_at,
        )
        text = "\n\n".join(f"--- source: {url} ---\n{value}" for url, value in captures)
        return values, coverage, text, captures[0][0]
