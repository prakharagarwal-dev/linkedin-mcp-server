"""Visible LinkedIn post search, detail, and discussion page objects."""

from __future__ import annotations

import json
import re
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import HttpUrl

from linkedin_mcp.browser.convergence import (
    CollectionSettleOutcome,
    visible_locator_signature,
    wait_for_collection_change,
    wait_for_collection_initial_state,
)
from linkedin_mcp.browser.manager import BrowserManager
from linkedin_mcp.domain.models import (
    CommentAttachmentObservation,
    CommentAttachmentType,
    CommentObservation,
    CommentSort,
    CommentThread,
    PostAttachment,
    PostAuthor,
    PostAuthorType,
    PostCommentsCoverage,
    PostCommentsListInput,
    PostContentType,
    PostDetailCoverage,
    PostEvidence,
    PostGetInput,
    PostLink,
    PostObservation,
    PostPoll,
    PostPollOption,
    PostPollState,
    PostResharedContent,
    PostSearchContentType,
    PostSearchCoverage,
    PostSearchDate,
    PostSearchFilters,
    PostSearchInput,
    PostSearchPostedBy,
    PostSearchSort,
    PostSummary,
    ReactionState,
    StopReason,
)
from linkedin_mcp.errors import InvalidTargetError, ParserDriftError
from linkedin_mcp.policy import (
    canonical_company_url,
    canonical_post_url,
    comment_reference_from_value,
    company_slug_from_url,
    post_reference_from_comment_ref,
    post_reference_from_value,
    profile_slug_from_url,
    validate_linkedin_url,
)

_CONTENT_SEARCH_URL = "https://www.linkedin.com/search/results/content/"
_COUNT_PATTERNS = {
    "reaction": re.compile(
        r"\b[\d,.+]+\s+(?:reactions?|likes?)\b",
        re.IGNORECASE,
    ),
    "comment": re.compile(r"\b[\d,.+]+\s+comments?\b", re.IGNORECASE),
    "repost": re.compile(r"\b[\d,.+]+\s+reposts?\b", re.IGNORECASE),
    "reply": re.compile(r"\b[\d,.+]+\s+repl(?:y|ies)\b", re.IGNORECASE),
}
_POST_ACTION_LINES = frozenset(
    {
        "like",
        "comment",
        "repost",
        "send",
        "follow",
        "following",
        "connect",
        "more",
    }
)
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
_POST_REGION_SELECTOR = (
    "article, [data-post-urn], [data-urn*='urn:li:activity'], "
    "[data-urn*='urn:li:share'], [data-urn*='urn:li:ugcPost'], "
    "[role='listitem']:has(button[aria-label^='Open control menu for post by '])"
)
_COMMENT_REGION_SELECTOR = "[data-comment-urn], [id^='replaceableComment_urn:li:comment:']"
_POST_SEARCH_END_PATTERN = re.compile(
    r"^(?:no (?:matching )?(?:posts|results)(?: found| to show)?|"
    r"we couldn(?:'|\N{RIGHT SINGLE QUOTATION MARK})t find any results)"
    r"(?:[.!])?$",
    re.IGNORECASE,
)
_COLLECTION_POLL_ATTEMPTS = 8
_COLLECTION_POLL_DELAY_MS = 250
_INITIAL_RESULTS_POLL_ATTEMPTS = 20
_COMMENT_TIME_PATTERN = re.compile(
    r"(?:\d+\s*[smhdw](?:\s*·\s*Edited)?|just now)",
    re.IGNORECASE,
)
_POST_MENU_PATTERN = re.compile(r"^Open control menu for post by (.+)$", re.IGNORECASE)
_POST_AGE_PATTERN = re.compile(
    r"^(?:\d+\s*(?:s|m|h|d|w|mo|yr)s?|just now)"
    r"(?:\s*[•·]\s*(?:Edited(?:\s*[•·])?)?)?$",
    re.IGNORECASE,
)
_POST_RELATIONSHIP_PATTERN = re.compile(
    r"(?:^|[•·]\s*)(1st|2nd|3rd(?:\+)?)(?=$|[\s•·])",
    re.IGNORECASE,
)
_POST_FOLLOWER_PATTERN = re.compile(r"\b[\d,.+]+\s+followers?\b", re.IGNORECASE)
_POST_PERCENTAGE_PATTERN = re.compile(r"^[\d.]+\s*%$")
_POST_VOTE_COUNT_PATTERN = re.compile(r"^[\d,.+]+\s+votes?$", re.IGNORECASE)
_POST_POLL_STATE_PATTERN = re.compile(r"^Poll (?:closed|ended)$", re.IGNORECASE)
_POST_DOCUMENT_PAGE_PATTERN = re.compile(
    r"^Page ([0-9]+) of ([0-9]+)$",
    re.IGNORECASE,
)
_POST_DOCUMENT_TOTAL_PATTERN = re.compile(r"^(?P<total>[0-9]+)\s+pages?$", re.IGNORECASE)
_POST_IMPRESSION_PATTERN = re.compile(r"^[\d,.+]+\s+impressions?$", re.IGNORECASE)
_POST_COUNT_ONLY_PATTERN = re.compile(r"^[\d,.+]+$")
_POST_DETAIL_MAX_MENUS = 20
_POST_DETAIL_MAX_ANCHORS = 300
_POST_DETAIL_MAX_MEDIA = 100
_POST_DETAIL_MAX_ACCESSIBLE_LABELS = 1_000
_POST_DETAIL_MAX_BODY_BOXES = 10
_INSTALL_CLIPBOARD_CAPTURE = """
() => {
  window.__linkedinMcpCopiedPostLink = null;
  const clipboard = navigator.clipboard;
  if (!clipboard || typeof clipboard.writeText !== "function") {
    return false;
  }
  window.__linkedinMcpOriginalClipboardWriteText = clipboard.writeText;
  clipboard.writeText = async (value) => {
    window.__linkedinMcpCopiedPostLink = String(value);
  };
  return clipboard.writeText !== window.__linkedinMcpOriginalClipboardWriteText;
}
"""
_RESTORE_CLIPBOARD_CAPTURE = """
() => {
  const clipboard = navigator.clipboard;
  const original = window.__linkedinMcpOriginalClipboardWriteText;
  if (clipboard && original) {
    clipboard.writeText = original;
  }
  delete window.__linkedinMcpOriginalClipboardWriteText;
  delete window.__linkedinMcpCopiedPostLink;
}
"""


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
class _PostHeaderFields:
    region: Locator
    author: PostAuthor
    posted_at_text: str | None
    edited: bool
    visibility_text: str | None
    promoted: bool


@dataclass(frozen=True, slots=True)
class _PostContentFields:
    content_type: PostContentType
    attachments: tuple[PostAttachment, ...]
    links: tuple[PostLink, ...]
    hashtags: tuple[str, ...]
    mentions: tuple[PostLink, ...]
    poll: PostPoll | None


@dataclass(frozen=True, slots=True)
class _PostEngagementFields:
    viewer_reaction: ReactionState | None
    reaction_count_text: str | None
    comment_count_text: str | None
    repost_count_text: str | None
    impression_count_text: str | None
    comments_enabled: bool
    reaction_evidence_text: str | None


@dataclass(frozen=True, slots=True)
class _ParsedPostDetail:
    source_url: HttpUrl
    displayed_post_ref: str
    header: _PostHeaderFields
    text: str | None
    content: _PostContentFields
    engagement: _PostEngagementFields
    captured_text: str
    text_expanded: bool
    is_repost_wrapper: bool
    original_post_ref: str | None


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


def _unique_lines(value: str) -> list[str]:
    lines: list[str] = []
    for raw_line in value.splitlines():
        line = " ".join(raw_line.split())
        if line and line not in lines:
            lines.append(line)
    return lines


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
        page.locator("main").locator(_POST_REGION_SELECTOR),
        identity_attributes=("data-post-urn", "data-urn", "data-entity-urn"),
    )


async def _visible_comment_signature(page: Page) -> tuple[str, ...]:
    return await visible_locator_signature(
        page.locator(_COMMENT_REGION_SELECTOR),
        identity_attributes=("data-comment-urn", "id", "data-urn"),
        limit=1_000,
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
        delay_ms=_COLLECTION_POLL_DELAY_MS,
    )
    return result.outcome


async def _prepare_visible_content(page: Page) -> None:
    main = page.locator("main")
    try:
        await main.wait_for(state="visible", timeout=10_000)
    except PlaywrightTimeoutError as error:
        raise ParserDriftError("LinkedIn content surface has no visible main region.") from error


async def _expand_search_post_body(page: Page, region: Locator) -> None:
    source_url = page.url
    bodies = await _post_body_boxes(region)
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


async def _expand_visible_content(page: Page) -> None:
    """Preserve bounded best-effort expansion for the discussion collection."""

    await _prepare_visible_content(page)
    main = page.locator("main")
    await page.keyboard.press("End")
    await page.wait_for_timeout(500)
    await page.keyboard.press("Home")
    buttons = main.locator('[data-testid="expandable-text-button"]').or_(
        main.get_by_role(
            "button",
            name=re.compile(r"^(?:see more|show more)(?:\b|$)", re.IGNORECASE),
        )
    )
    for index in range(min(await buttons.count(), 100)):
        button = buttons.nth(index)
        try:
            if not await button.is_visible():
                continue
            button_name = " ".join(
                (
                    (await button.inner_text()).strip(),
                    (await button.get_attribute("aria-label") or "").strip(),
                )
            )
            if re.search(r"\b(?:comments?|repl(?:y|ies))\b", button_name, re.IGNORECASE):
                continue
            source_url = page.url
            await button.click(timeout=1_000)
            if page.url != source_url:
                raise ParserDriftError("A LinkedIn content expansion unexpectedly navigated away.")
        except PlaywrightTimeoutError:
            continue


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
    browser: BrowserManager,
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
    submitted_url = await browser.navigate_via_visible_control(page, show_results.first)
    resolved = _resolved_post_facets_from_url(submitted_url)
    _validate_resolved_post_facets(filters, resolved)
    return resolved


def _requires_post_facet_resolution(filters: PostSearchFilters) -> bool:
    return any(getattr(filters, spec.names_field) for spec in _POST_FACETS)


async def _post_reference_for_region(region: Locator) -> str | None:
    for attribute in ("data-post-urn", "data-urn", "data-id", "data-activity-urn"):
        value = await region.get_attribute(attribute)
        if value and (reference := post_reference_from_value(value)):
            return reference
    links = region.locator("a[href]")
    for index in range(min(await links.count(), 200)):
        href = await links.nth(index).get_attribute("href")
        if href and (reference := post_reference_from_value(href)):
            return reference
    menu_openers = region.locator('button[aria-label^="Open control menu for post by "]')
    visible_openers = [
        menu_openers.nth(index)
        for index in range(await menu_openers.count())
        if await menu_openers.nth(index).is_visible()
    ]
    if not visible_openers:
        return None
    if len(visible_openers) != 1:
        raise ParserDriftError("LinkedIn post region has no unique visible post control menu.")
    page = region.page
    source_url = page.url
    try:
        installed = cast(bool, await page.evaluate(_INSTALL_CLIPBOARD_CAPTURE))
        if not installed:
            raise ParserDriftError("LinkedIn post link capture is unavailable in this browser.")
        await visible_openers[0].click()
        copy_control = page.get_by_text(re.compile(r"copy link", re.IGNORECASE))
        visible_copy_controls: list[Locator] = []
        for _ in range(30):
            visible_copy_controls = []
            for index in range(await copy_control.count()):
                candidate = copy_control.nth(index)
                text = " ".join((await candidate.inner_text()).split()).casefold()
                if text in {"copy link", "copy link to post"} and await candidate.is_visible():
                    visible_copy_controls.append(candidate)
            if visible_copy_controls:
                break
            await page.wait_for_timeout(100)
        if not visible_copy_controls:
            return None
        if len(visible_copy_controls) != 1:
            raise ParserDriftError(
                "LinkedIn post menu has no unique visible Copy link to post control."
            )
        await visible_copy_controls[0].click()
        await page.wait_for_timeout(100)
        if page.url != source_url:
            raise ParserDriftError("LinkedIn Copy link to post unexpectedly navigated away.")
        copied_value = cast(
            str | None,
            await page.evaluate("window.__linkedinMcpCopiedPostLink"),
        )
    except PlaywrightError as error:
        raise ParserDriftError(
            "LinkedIn post link could not be captured from its visible menu."
        ) from error
    finally:
        with suppress(PlaywrightError):
            await page.evaluate(_RESTORE_CLIPBOARD_CAPTURE)
        with suppress(PlaywrightError):
            await page.keyboard.press("Escape")
    if not copied_value:
        raise ParserDriftError("LinkedIn Copy link to post returned no stable visible link.")
    try:
        copied_url = validate_linkedin_url(copied_value, ("www.linkedin.com",))
    except InvalidTargetError as error:
        raise ParserDriftError(
            "LinkedIn Copy link to post returned an untrusted target."
        ) from error
    reference = post_reference_from_value(copied_url)
    if reference is None:
        # LinkedIn content search can interleave addressable posts with
        # article/newsletter cards whose visible Copy link resolves to a
        # trusted LinkedIn page but carries no stable post URN. Such a card
        # cannot satisfy this capability's stable-identifier contract, so
        # quarantine it while continuing to collect other exact posts.
        return None
    return reference


async def _post_author(region: Locator) -> PostAuthor | None:
    links = region.locator('a[href*="/in/"], a[href*="/company/"]')
    image_only_fallback: PostAuthor | None = None
    for index in range(min(await links.count(), 100)):
        link = links.nth(index)
        if not await link.is_visible():
            continue
        href = await link.get_attribute("href")
        if not href:
            continue
        url = urljoin("https://www.linkedin.com", href)
        lines = _unique_lines((await link.inner_text()).strip())
        name = lines[0] if lines else None
        image_only = not lines
        if not name:
            image = link.locator("img[alt]")
            if await image.count():
                name = (await image.first.get_attribute("alt") or "").strip()
        if not name:
            continue
        if profile_slug := profile_slug_from_url(url):
            author = PostAuthor(
                author_type=PostAuthorType.MEMBER,
                name=name,
                profile_slug=profile_slug,
                author_url=HttpUrl(f"https://www.linkedin.com/in/{profile_slug}/"),
                headline=lines[1] if len(lines) > 1 else None,
            )
        elif company_slug := company_slug_from_url(url):
            author = PostAuthor(
                author_type=PostAuthorType.COMPANY,
                name=name,
                company_slug=company_slug,
                author_url=HttpUrl(canonical_company_url(company_slug)),
                headline=lines[1] if len(lines) > 1 else None,
            )
        else:
            continue
        if not image_only:
            return author
        image_only_fallback = image_only_fallback or author
    return image_only_fallback


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
    lines = _unique_lines((await region.inner_text()).strip())
    content = [
        line
        for line in lines
        if line != author.name
        and line != author.headline
        and line.casefold() not in _POST_ACTION_LINES
        and not any(pattern.search(line) for pattern in _COUNT_PATTERNS.values())
        and not re.fullmatch(
            r"(?:\d+\s*[smhdw]|just now|edited)",
            line,
            re.IGNORECASE,
        )
    ]
    return "\n".join(content) if content else None


def _first_count(lines: list[str], kind: str) -> str | None:
    pattern = _COUNT_PATTERNS[kind]
    return next(
        (match.group(0) for line in lines if (match := pattern.search(line)) is not None),
        None,
    )


async def _post_summary_from_region(
    region: Locator,
    *,
    known_reference: str | None = None,
) -> PostSummary | None:
    reference = known_reference or await _post_reference_for_region(region)
    visible_text = (await region.inner_text()).strip()
    if reference is None or not visible_text:
        return None
    header = await _post_header_fields(region)
    body_boxes = await _post_body_boxes(region)
    if len(body_boxes) > 2:
        raise ParserDriftError("LinkedIn post search exposed too many nested post bodies.")
    body = body_boxes[0] if body_boxes else None
    text = (await body.inner_text()).strip() if body is not None else None
    if text == "":
        text = None
    if text is None:
        text = await _post_text(region, author=header.author)
    engagement = await _post_engagement(region)
    content_type = PostContentType.REPOST
    if len(body_boxes) < 2:
        content_type = (await _post_content_fields(region, body)).content_type
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
) -> tuple[PostSummary, ...]:
    main = page.locator("main")
    candidates = main.locator(_POST_REGION_SELECTOR)
    inventory: list[tuple[int, str]] = []
    observed_refs: set[str] = set(excluded_refs)
    for index in range(min(await candidates.count(), 500)):
        candidate = candidates.nth(index)
        if not await candidate.is_visible():
            continue
        reference = await _post_reference_for_region(candidate)
        if reference is None or reference in observed_refs:
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
        stable_reference = await _post_reference_for_region(candidate)
        if stable_reference != reference:
            raise ParserDriftError(
                "LinkedIn post search changed an exact result identity during extraction."
            )
        summary = await _post_summary_from_region(
            candidate,
            known_reference=reference,
        )
        if summary is not None:
            values[reference] = summary
    return tuple(values[reference] for _, reference in inventory if reference in values)


async def _region_for_post(page: Page, post_ref: str) -> Locator:
    candidates = page.locator("main").locator(_POST_REGION_SELECTOR)
    matches: list[Locator] = []
    for index in range(min(await candidates.count(), 500)):
        candidate = candidates.nth(index)
        if await candidate.is_visible() and await _post_reference_for_region(candidate) == post_ref:
            matches.append(candidate)
    if len(matches) != 1:
        raise ParserDriftError(
            "LinkedIn post detail did not expose one exact visible requested post."
        )
    return matches[0]


class PostSearchPage:
    def __init__(self, browser: BrowserManager, *, max_pages: int) -> None:
        if max_pages < 1:
            raise ValueError("Post search page bound must be positive.")
        self._browser = browser
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
        stop_reason = StopReason.SAFETY_BOUND
        async with self._browser.page() as page:
            if _requires_post_facet_resolution(request.filters):
                await self._browser.navigate(page, _build_post_search_url(request, page_index=1))
                resolved = await _resolve_post_facets(
                    self._browser,
                    page,
                    request.filters,
                )
            for page_index in range(1, self._max_pages + 1):
                target = _build_post_search_url(
                    request,
                    page_index=page_index,
                    resolved=resolved,
                )
                await self._browser.navigate(page, target)
                rendered_state = await _wait_for_post_search_state(page)
                await _prepare_visible_content(page)
                visible_posts = await _visible_posts(
                    page,
                    result_limit=limit - len(posts),
                    excluded_refs=frozenset(posts),
                )
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
            max_results=limit,
            stop_reason=stop_reason,
            captured_at=captured_at,
        )
        text = "\n\n".join(f"--- source: {url} ---\n{value}" for url, value in captures)
        return values, coverage, text, captures[0][0]


async def _bounded_visible_locators(
    locator: Locator,
    *,
    limit: int,
    description: str,
) -> list[Locator]:
    count = await locator.count()
    if count > limit:
        raise ParserDriftError(f"LinkedIn post detail exceeded the bounded {description} limit.")
    return [locator.nth(index) for index in range(count) if await locator.nth(index).is_visible()]


def _https_url(value: str | None) -> HttpUrl | None:
    if not value:
        return None
    absolute = urljoin("https://www.linkedin.com", value)
    if urlsplit(absolute).scheme != "https":
        return None
    return HttpUrl(absolute)


async def _detail_post_regions(page: Page) -> list[tuple[Locator, str]]:
    menus = await _bounded_visible_locators(
        page.locator("main").get_by_role(
            "button",
            name=_POST_MENU_PATTERN,
        ),
        limit=_POST_DETAIL_MAX_MENUS,
        description="post-menu",
    )
    values: list[tuple[Locator, str]] = []
    for menu in menus:
        region = menu.locator("xpath=ancestor::*[@role='listitem' or self::article][1]")
        if not await region.count():
            continue
        reference = await _post_reference_for_region(region.first)
        if reference is not None:
            values.append((region.first, reference))
    return values


async def _detail_region_for_post(
    page: Page,
    requested_post_ref: str,
) -> tuple[Locator, str]:
    regions = await _detail_post_regions(page)
    exact = [
        (region, reference) for region, reference in regions if reference == requested_post_ref
    ]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ParserDriftError(
            "LinkedIn post detail exposed multiple visible copies of the requested post."
        )
    # LinkedIn currently renders some activity URLs as one exact underlying share or
    # UGC post. The requested URL remains unchanged and the page exposes exactly one
    # post menu, so both identities are retained rather than silently conflated.
    if len(regions) == 1 and post_reference_from_value(page.url) == requested_post_ref:
        return regions[0]
    raise ParserDriftError("LinkedIn post detail did not expose one exact visible requested post.")


async def _expand_exact_post_body(
    browser: BrowserManager,
    page: Page,
    body: Locator | None,
) -> bool:
    if body is None:
        return True
    scope = body.locator("..")
    buttons = scope.locator('[data-testid="expandable-text-button"]')
    visible = await _bounded_visible_locators(
        buttons,
        limit=5,
        description="text-expansion control",
    )
    source_url = page.url
    for button in visible:
        if not await button.is_visible():
            continue
        label = " ".join(
            (
                (await button.inner_text()).strip(),
                (await button.get_attribute("aria-label") or "").strip(),
            )
        )
        if re.search(r"\b(?:comments?|repl(?:y|ies))\b", label, re.IGNORECASE):
            continue
        try:
            await button.click(timeout=2_000)
            await page.wait_for_timeout(100)
        except PlaywrightTimeoutError as error:
            if not await button.is_visible():
                continue
            raise ParserDriftError("LinkedIn post text could not be fully expanded.") from error
        if page.url != source_url:
            raise ParserDriftError("LinkedIn post text expansion unexpectedly navigated away.")
        await browser.assert_safe(page)
    remaining = await _bounded_visible_locators(
        scope.locator('[data-testid="expandable-text-button"]'),
        limit=5,
        description="remaining text-expansion control",
    )
    if remaining:
        raise ParserDriftError("LinkedIn post text remained visibly truncated.")
    return True


async def _post_body_boxes(region: Locator) -> list[Locator]:
    return await _bounded_visible_locators(
        region.locator('[data-testid="expandable-text-box"]'),
        limit=_POST_DETAIL_MAX_BODY_BOXES,
        description="post-body",
    )


async def _post_header_region(region: Locator) -> tuple[Locator, str]:
    menus = await _bounded_visible_locators(
        region.get_by_role("button", name=_POST_MENU_PATTERN),
        limit=3,
        description="exact post-menu",
    )
    if len(menus) != 1:
        raise ParserDriftError("LinkedIn post detail has no unique visible exact post menu.")
    menu_label = (await menus[0].get_attribute("aria-label") or "").strip()
    match = _POST_MENU_PATTERN.fullmatch(menu_label)
    if match is None:
        raise ParserDriftError("LinkedIn post detail has an invalid visible author control.")
    candidate = menus[0]
    for _ in range(8):
        candidate = candidate.locator("..")
        identities = candidate.locator('a[href*="/in/"], a[href*="/company/"]')
        if (
            await identities.count()
            and not await candidate.locator('[data-testid="expandable-text-box"]').count()
        ):
            return candidate, " ".join(match.group(1).split())
    raise ParserDriftError("LinkedIn post detail has no bounded visible author header.")


async def _author_from_identity_region(
    region: Locator,
    *,
    expected_name: str | None,
) -> PostAuthor:
    anchors = await _bounded_visible_locators(
        region.locator('a[href*="/in/"], a[href*="/company/"]'),
        limit=50,
        description="author-identity link",
    )
    candidates: dict[
        tuple[PostAuthorType, str],
        tuple[int, str, HttpUrl],
    ] = {}
    normalized_expected = expected_name.casefold() if expected_name else None
    for anchor in anchors:
        href = await anchor.get_attribute("href")
        url = _https_url(href)
        if url is None:
            continue
        absolute = str(url)
        profile_slug = profile_slug_from_url(absolute)
        company_slug = company_slug_from_url(absolute)
        if profile_slug is not None:
            author_type = PostAuthorType.MEMBER
            identity = profile_slug
            canonical_url = HttpUrl(f"https://www.linkedin.com/in/{profile_slug}/")
        elif company_slug is not None:
            author_type = PostAuthorType.COMPANY
            identity = company_slug
            canonical_url = HttpUrl(canonical_company_url(company_slug))
        else:
            continue
        lines = _unique_lines((await anchor.inner_text()).strip())
        alt_values: list[str] = []
        images = await _bounded_visible_locators(
            anchor.locator("img[alt]"),
            limit=5,
            description="author-image",
        )
        for image in images:
            alt = (await image.get_attribute("alt") or "").strip()
            if alt:
                alt_values.append(alt)
        visible_names = (*lines, *alt_values)
        score = 0
        if normalized_expected is not None:
            if any(value.casefold() == normalized_expected for value in visible_names):
                score = 3
            elif any(normalized_expected in value.casefold() for value in visible_names):
                score = 2
        display_name = (
            expected_name or next((value for value in visible_names if value), None) or identity
        )
        key = (author_type, identity)
        existing = candidates.get(key)
        if existing is None or score > existing[0]:
            candidates[key] = (score, display_name, canonical_url)
    if not candidates:
        raise ParserDriftError("LinkedIn post detail exposed no typed visible author identity.")
    selected = list(candidates.items())
    if normalized_expected is not None:
        matched = [item for item in selected if item[1][0] > 0]
        if matched:
            selected = matched
    if len(selected) != 1:
        raise ParserDriftError("LinkedIn post detail exposed an ambiguous visible author identity.")
    (author_type, identity), (_, display_name, canonical_url) = selected[0]
    return PostAuthor(
        author_type=author_type,
        name=display_name,
        profile_slug=identity if author_type is PostAuthorType.MEMBER else None,
        company_slug=identity if author_type is PostAuthorType.COMPANY else None,
        author_url=canonical_url,
    )


def _post_age(lines: list[str]) -> str | None:
    return next((line for line in lines if _POST_AGE_PATTERN.fullmatch(line)), None)


def _post_relationship(lines: list[str]) -> str | None:
    for line in lines:
        if match := _POST_RELATIONSHIP_PATTERN.search(line):
            return match.group(1)
    return None


def _post_follower_count(lines: list[str]) -> str | None:
    for line in lines:
        if match := _POST_FOLLOWER_PATTERN.search(line):
            return match.group(0)
    return None


async def _visible_accessible_values(
    region: Locator,
    selector: str,
    attribute: str,
    *,
    limit: int = _POST_DETAIL_MAX_ACCESSIBLE_LABELS,
) -> tuple[str, ...]:
    values: list[str] = []
    for item in await _bounded_visible_locators(
        region.locator(selector),
        limit=limit,
        description="accessible-evidence",
    ):
        value = " ".join((await item.get_attribute(attribute) or "").split())
        if value and value not in values:
            values.append(value)
    return tuple(values)


async def _post_header_fields(region: Locator) -> _PostHeaderFields:
    header, expected_name = await _post_header_region(region)
    lines = _unique_lines((await header.inner_text()).strip())
    base_author = await _author_from_identity_region(
        header,
        expected_name=expected_name,
    )
    relationship = _post_relationship(lines)
    posted_at = _post_age(lines)
    follower_count = _post_follower_count(lines)
    excluded = {
        expected_name.casefold(),
        "feed post",
        "follow",
        "following",
        "connect",
        "message",
        "promoted",
    }
    headline_candidates = [
        line
        for line in lines
        if line.casefold() not in excluded
        and _POST_AGE_PATTERN.fullmatch(line) is None
        and _POST_RELATIONSHIP_PATTERN.search(line) is None
        and _POST_FOLLOWER_PATTERN.search(line) is None
    ]
    headline = max(headline_candidates, key=len, default=None)
    header_labels = await _visible_accessible_values(
        header,
        "[aria-label]",
        "aria-label",
    )
    visibility_values = tuple(
        value
        for value in await _visible_accessible_values(
            region,
            "[aria-label]",
            "aria-label",
        )
        if value.casefold().startswith("visibility:")
    )
    visibility = visibility_values[0] if visibility_values else None
    author = base_author.model_copy(
        update={
            "headline": headline,
            "relationship_text": relationship,
            "follower_count_text": follower_count,
            "verified": any("verified profile" in value.casefold() for value in header_labels),
            "viewer_is_author": any(
                re.search(r"\byou\b", value, re.IGNORECASE) is not None for value in header_labels
            ),
        }
    )
    return _PostHeaderFields(
        region=header,
        author=author,
        posted_at_text=posted_at,
        edited=any("edited" in line.casefold() for line in lines),
        visibility_text=visibility,
        promoted=any("promoted" in line.casefold() for line in lines),
    )


async def _post_body_links(
    body: Locator | None,
) -> tuple[tuple[PostLink, ...], tuple[str, ...], tuple[PostLink, ...]]:
    if body is None:
        return (), (), ()
    anchors = await _bounded_visible_locators(
        body.locator("a[href]"),
        limit=_POST_DETAIL_MAX_ANCHORS,
        description="post-body link",
    )
    links: list[PostLink] = []
    hashtags: list[str] = []
    mentions: list[PostLink] = []
    for anchor in anchors:
        href = await anchor.get_attribute("href")
        url = _https_url(href)
        label = " ".join((await anchor.inner_text()).split())
        if url is None or not label:
            continue
        if label.startswith("#"):
            if label not in hashtags:
                hashtags.append(label[:200])
            continue
        item = PostLink(label=label[:2_000], url=url)
        absolute = str(url)
        if profile_slug_from_url(absolute) or company_slug_from_url(absolute):
            if item not in mentions:
                mentions.append(item)
        elif item not in links:
            links.append(item)
    body_text = (await body.inner_text()).strip()
    for hashtag in re.findall(r"(?<!\w)#[\w-]+", body_text):
        if hashtag not in hashtags:
            hashtags.append(hashtag[:200])
    return tuple(links), tuple(hashtags), tuple(mentions)


async def _poll_options_from_region(region: Locator) -> tuple[PostPollOption, ...]:
    radio_options: list[PostPollOption] = []
    for radio in await _bounded_visible_locators(
        region.get_by_role("radio"),
        limit=10,
        description="poll-option",
    ):
        text = " ".join(
            (
                (await radio.get_attribute("aria-label") or "").strip()
                or (await radio.inner_text()).strip()
            ).split()
        )
        if not text:
            continue
        radio_options.append(
            PostPollOption(
                text=text[:500],
                selected=await radio.is_checked(),
                visible_text=text,
            )
        )
    if len(radio_options) >= 2:
        return tuple(dict.fromkeys(radio_options))

    candidates = region.locator("span, div, p")
    count = await candidates.count()
    if count > 2_000:
        raise ParserDriftError("LinkedIn poll exceeded the bounded option-node limit.")
    options: list[PostPollOption] = []
    for index in range(count):
        percentage = candidates.nth(index)
        if not await percentage.is_visible():
            continue
        percentage_text = " ".join((await percentage.inner_text()).split())
        if _POST_PERCENTAGE_PATTERN.fullmatch(percentage_text) is None:
            continue
        option_region: Locator | None = None
        candidate = percentage
        for _ in range(2):
            candidate = candidate.locator("..")
            lines = _unique_lines((await candidate.inner_text()).strip())
            labels = [
                line
                for line in lines
                if _POST_PERCENTAGE_PATTERN.fullmatch(line) is None
                and _POST_VOTE_COUNT_PATTERN.fullmatch(line) is None
            ]
            if labels:
                option_region = candidate
                break
        if option_region is None:
            continue
        lines = _unique_lines((await option_region.inner_text()).strip())
        labels = [
            line
            for line in lines
            if _POST_PERCENTAGE_PATTERN.fullmatch(line) is None
            and _POST_VOTE_COUNT_PATTERN.fullmatch(line) is None
        ]
        if not labels:
            continue
        label = labels[0]
        vote_count = next(
            (line for line in lines if _POST_VOTE_COUNT_PATTERN.fullmatch(line)),
            None,
        )
        option = PostPollOption(
            text=label[:500],
            percentage_text=percentage_text,
            vote_count_text=vote_count,
            visible_text=(await option_region.inner_text()).strip(),
        )
        if all(existing.text.casefold() != option.text.casefold() for existing in options):
            options.append(option)
    return tuple(options)


async def _post_poll(region: Locator) -> PostPoll | None:
    closed = await _bounded_visible_locators(
        region.get_by_text(_POST_POLL_STATE_PATTERN),
        limit=5,
        description="poll-state",
    )
    votes = await _bounded_visible_locators(
        region.get_by_text(_POST_VOTE_COUNT_PATTERN),
        limit=10,
        description="poll-vote-count",
    )
    radios = await _bounded_visible_locators(
        region.get_by_role("radio"),
        limit=10,
        description="poll-radio",
    )
    seed = closed[0] if closed else votes[0] if votes else radios[0] if radios else None
    if seed is None:
        return None
    poll_region = seed
    options: tuple[PostPollOption, ...] = ()
    for _ in range(8):
        poll_region = poll_region.locator("..")
        options = await _poll_options_from_region(poll_region)
        if len(options) >= 2:
            break
    if len(options) < 2:
        if closed:
            raise ParserDriftError(
                "LinkedIn exposed a poll state without complete visible poll options."
            )
        return None
    poll_text = (await poll_region.inner_text()).strip()
    lines = _unique_lines(poll_text)
    option_values = {
        value.casefold()
        for option in options
        for value in (
            option.text,
            option.percentage_text,
            option.vote_count_text,
        )
        if value
    }
    question_candidates = [
        line
        for line in lines
        if line.casefold() not in option_values
        and _POST_VOTE_COUNT_PATTERN.fullmatch(line) is None
        and _POST_POLL_STATE_PATTERN.fullmatch(line) is None
        and line not in {"·", "•"}
    ]
    if not question_candidates:
        raise ParserDriftError("LinkedIn poll has no visible question.")
    total_votes = next(
        (line for line in reversed(lines) if _POST_VOTE_COUNT_PATTERN.fullmatch(line)),
        None,
    )
    state_text = next(
        (line for line in lines if _POST_POLL_STATE_PATTERN.fullmatch(line)),
        None,
    )
    selected_values = [option.selected for option in options if option.selected is not None]
    return PostPoll(
        question=question_candidates[0][:500],
        options=options,
        total_votes_text=total_votes,
        state=PostPollState.CLOSED if state_text else PostPollState.OPEN,
        state_text=state_text,
        viewer_has_voted=any(selected_values) if selected_values else None,
        visible_text=poll_text,
    )


async def _post_document_attachment(region: Locator) -> PostAttachment | None:
    page_controls = await _bounded_visible_locators(
        region.get_by_role("button", name=_POST_DOCUMENT_PAGE_PATTERN),
        limit=100,
        description="document-page control",
    )
    full_screen = await _bounded_visible_locators(
        region.get_by_role(
            "button",
            name=re.compile(r"^Full screen$", re.IGNORECASE),
        ),
        limit=5,
        description="document-fullscreen control",
    )
    if not page_controls and not full_screen:
        return None
    totals: list[int] = []
    for control in page_controls:
        label = (await control.get_attribute("aria-label") or "").strip()
        if match := _POST_DOCUMENT_PAGE_PATTERN.fullmatch(label):
            totals.append(int(match.group(2)))
    viewer = full_screen[0] if full_screen else page_controls[0]
    for _ in range(8):
        viewer = viewer.locator("..")
        if await viewer.get_by_role(
            "button",
            name=_POST_DOCUMENT_PAGE_PATTERN,
        ).count():
            break
    visible_text = (await viewer.inner_text()).strip()
    lines = _unique_lines(visible_text)
    for line in lines:
        if match := _POST_DOCUMENT_TOTAL_PATTERN.fullmatch(line):
            totals.append(int(match.group("total")))
    page_count = max(totals) if totals else None
    title = next(
        (
            line
            for line in lines
            if _POST_DOCUMENT_TOTAL_PATTERN.fullmatch(line) is None
            and _POST_DOCUMENT_PAGE_PATTERN.fullmatch(line) is None
            and line not in {"·", "•"}
        ),
        None,
    )
    preview_url: HttpUrl | None = None
    preview_label: str | None = None
    for image in await _bounded_visible_locators(
        viewer.locator("img"),
        limit=_POST_DETAIL_MAX_MEDIA,
        description="document-preview image",
    ):
        box = await image.bounding_box()
        if box is None or box["width"] < 100 or box["height"] < 100:
            continue
        preview_url = _https_url(await image.get_attribute("src"))
        preview_label = (await image.get_attribute("alt") or "").strip() or None
        break
    label = (
        title
        or preview_label
        or (f"{page_count} page document" if page_count is not None else "Document")
    )
    return PostAttachment(
        content_type=PostContentType.DOCUMENT,
        label=label[:2_000],
        preview_url=preview_url,
        page_count=page_count,
        visible_text=visible_text or label,
    )


def _card_content_type(url: str, visible_text: str) -> PostContentType:
    value = f"{urlsplit(url).path} {visible_text}".casefold()
    if "newsletter" in value:
        return PostContentType.NEWSLETTER
    if "/pulse/" in value or "/blog/" in value or "article" in value:
        return PostContentType.ARTICLE
    if "/events/" in value or "view event" in value:
        return PostContentType.EVENT
    if "/jobs/" in value or "view job" in value:
        return PostContentType.JOB
    return PostContentType.LINK


async def _card_preview_url(anchor: Locator) -> HttpUrl | None:
    candidate = anchor
    for _ in range(5):
        images = await _bounded_visible_locators(
            candidate.locator("img"),
            limit=_POST_DETAIL_MAX_MEDIA,
            description="link-card preview",
        )
        for image in images:
            box = await image.bounding_box()
            if box is not None and box["width"] >= 100 and box["height"] >= 70:
                return _https_url(await image.get_attribute("src"))
        candidate = candidate.locator("..")
    return None


async def _post_link_cards(
    region: Locator,
) -> tuple[PostAttachment, ...]:
    anchors = await _bounded_visible_locators(
        region.locator("a[href]"),
        limit=_POST_DETAIL_MAX_ANCHORS,
        description="post-card link",
    )
    values: list[PostAttachment] = []
    for anchor in anchors:
        if await anchor.locator("xpath=ancestor::*[@data-testid='expandable-text-box'][1]").count():
            continue
        href = await anchor.get_attribute("href")
        url = _https_url(href)
        if url is None:
            continue
        absolute = str(url)
        if (
            profile_slug_from_url(absolute)
            or company_slug_from_url(absolute)
            or post_reference_from_value(absolute)
        ):
            continue
        if (await anchor.get_attribute("aria-label") or "").strip().casefold() == "send":
            continue
        box = await anchor.bounding_box()
        text = (await anchor.inner_text()).strip()
        lines = _unique_lines(text)
        if box is None or box["width"] < 180 or len(lines) < 2:
            continue
        attachment = PostAttachment(
            content_type=_card_content_type(absolute, text),
            label=lines[0][:2_000],
            url=url,
            preview_url=await _card_preview_url(anchor),
            visible_text=text,
        )
        if attachment not in values:
            values.append(attachment)
    if len(values) > 5:
        raise ParserDriftError("LinkedIn post detail exposed too many visible link cards.")
    return tuple(values)


async def _post_video_attachments(region: Locator) -> tuple[PostAttachment, ...]:
    values: list[PostAttachment] = []
    videos = await _bounded_visible_locators(
        region.locator("video"),
        limit=20,
        description="post-video",
    )
    live_text = bool(
        re.search(r"(?:^|\n)\s*Live\s*(?:\n|$)", await region.inner_text(), re.IGNORECASE)
    )
    for video in videos:
        box = await video.bounding_box()
        if box is None or box["width"] < 100 or box["height"] < 100:
            continue
        label = (
            await video.get_attribute("aria-label")
            or await video.get_attribute("title")
            or ("Live video" if live_text else "Video")
        )
        attachment = PostAttachment(
            content_type=(PostContentType.LIVE_VIDEO if live_text else PostContentType.VIDEO),
            label=label[:2_000],
            url=_https_url(await video.get_attribute("src")),
            preview_url=_https_url(await video.get_attribute("poster")),
            visible_text=label,
        )
        if attachment not in values:
            values.append(attachment)
    return tuple(values)


async def _post_image_attachments(
    region: Locator,
    *,
    excluded_preview_urls: frozenset[str],
) -> tuple[PostAttachment, ...]:
    values: list[PostAttachment] = []
    for image in await _bounded_visible_locators(
        region.locator("img"),
        limit=_POST_DETAIL_MAX_MEDIA,
        description="post-image",
    ):
        box = await image.bounding_box()
        if box is None or box["width"] < 100 or box["height"] < 100:
            continue
        owner = image.locator("xpath=ancestor::a[@href][1]")
        if await owner.count():
            owner_url = _https_url(await owner.first.get_attribute("href"))
            if owner_url is not None and (
                profile_slug_from_url(str(owner_url)) or company_slug_from_url(str(owner_url))
            ):
                continue
        source_url = _https_url(await image.get_attribute("src"))
        if source_url is not None and str(source_url) in excluded_preview_urls:
            continue
        label = (
            await image.get_attribute("alt") or await image.get_attribute("aria-label") or "Image"
        ).strip()
        attachment = PostAttachment(
            content_type=PostContentType.IMAGE,
            label=label[:2_000],
            url=source_url,
            visible_text=label,
        )
        if attachment not in values:
            values.append(attachment)
    return tuple(values)


async def _post_content_fields(
    region: Locator,
    body: Locator | None,
) -> _PostContentFields:
    links, hashtags, mentions = await _post_body_links(body)
    poll = await _post_poll(region)
    if poll is not None:
        return _PostContentFields(
            content_type=PostContentType.POLL,
            attachments=(),
            links=links,
            hashtags=hashtags,
            mentions=mentions,
            poll=poll,
        )
    document = await _post_document_attachment(region)
    if document is not None:
        return _PostContentFields(
            content_type=PostContentType.DOCUMENT,
            attachments=(document,),
            links=links,
            hashtags=hashtags,
            mentions=mentions,
            poll=None,
        )
    videos = await _post_video_attachments(region)
    if videos:
        return _PostContentFields(
            content_type=videos[0].content_type,
            attachments=videos,
            links=links,
            hashtags=hashtags,
            mentions=mentions,
            poll=None,
        )
    cards = await _post_link_cards(region)
    if cards:
        return _PostContentFields(
            content_type=cards[0].content_type,
            attachments=cards,
            links=links,
            hashtags=hashtags,
            mentions=mentions,
            poll=None,
        )
    images = await _post_image_attachments(
        region,
        excluded_preview_urls=frozenset(),
    )
    return _PostContentFields(
        content_type=PostContentType.IMAGE if images else PostContentType.TEXT,
        attachments=images,
        links=links,
        hashtags=hashtags,
        mentions=mentions,
        poll=None,
    )


async def _embedded_post_region(body: Locator) -> Locator:
    candidate = body
    for _ in range(8):
        candidate = candidate.locator("..")
        identities = candidate.locator('a[href*="/in/"], a[href*="/company/"]')
        menus = candidate.get_by_role("button", name=_POST_MENU_PATTERN)
        body_count = await candidate.locator('[data-testid="expandable-text-box"]').count()
        if await identities.count() and not await menus.count() and body_count == 1:
            return candidate
    raise ParserDriftError("LinkedIn repost has no bounded visible original-post region.")


def _visible_count_text(value: str) -> str | None:
    normalized = " ".join(value.replace("\u200b", "").split())
    return normalized if _POST_COUNT_ONLY_PATTERN.fullmatch(normalized) else None


async def _one_visible_button(
    region: Locator,
    pattern: re.Pattern[str],
    *,
    description: str,
) -> Locator | None:
    values = await _bounded_visible_locators(
        region.get_by_role("button", name=pattern),
        limit=5,
        description=description,
    )
    if len(values) > 1:
        raise ParserDriftError(f"LinkedIn post detail has an ambiguous visible {description}.")
    return values[0] if values else None


async def _post_engagement(region: Locator) -> _PostEngagementFields:
    reaction_button = await _one_visible_button(
        region,
        re.compile(r"^Reaction button state:", re.IGNORECASE),
        description="reaction control",
    )
    viewer_reaction: ReactionState | None = None
    reaction_count: str | None = None
    reaction_evidence: str | None = None
    if reaction_button is not None:
        viewer_reaction = ReactionState.NONE
        reaction_evidence = (await reaction_button.get_attribute("aria-label") or "").strip()
        state = reaction_evidence.partition(":")[2].strip().casefold()
        if state and state != "no reaction":
            try:
                viewer_reaction = ReactionState(state)
            except ValueError as error:
                raise ParserDriftError(
                    "LinkedIn post detail exposed an unknown visible reaction state."
                ) from error
        reaction_count = _visible_count_text(await reaction_button.inner_text())
    comment_button = await _one_visible_button(
        region,
        re.compile(r"^Comment$", re.IGNORECASE),
        description="comment control",
    )
    repost_button = await _one_visible_button(
        region,
        re.compile(r"^Repost$", re.IGNORECASE),
        description="repost control",
    )
    impressions: list[str] = []
    for anchor in await _bounded_visible_locators(
        region.locator("a[href]"),
        limit=_POST_DETAIL_MAX_ANCHORS,
        description="impression link",
    ):
        text = " ".join((await anchor.inner_text()).split())
        if _POST_IMPRESSION_PATTERN.fullmatch(text) and text not in impressions:
            impressions.append(text)
    if len(impressions) > 1:
        raise ParserDriftError("LinkedIn post detail exposed multiple visible impression counts.")
    return _PostEngagementFields(
        viewer_reaction=viewer_reaction,
        reaction_count_text=reaction_count,
        comment_count_text=(
            _visible_count_text(await comment_button.inner_text())
            if comment_button is not None
            else None
        ),
        repost_count_text=(
            _visible_count_text(await repost_button.inner_text())
            if repost_button is not None
            else None
        ),
        impression_count_text=impressions[0] if impressions else None,
        comments_enabled=(comment_button is not None and not await comment_button.is_disabled()),
        reaction_evidence_text=reaction_evidence or None,
    )


async def _captured_post_text(region: Locator) -> str:
    visible_text = (await region.inner_text()).strip()
    if not visible_text:
        raise ParserDriftError("LinkedIn post detail returned no visible text.")
    accessible = [
        *await _visible_accessible_values(
            region,
            "[aria-label]",
            "aria-label",
        ),
        *await _visible_accessible_values(
            region,
            "img[alt]",
            "alt",
        ),
    ]
    retained = [value for value in dict.fromkeys(accessible) if value and value not in visible_text]
    if retained:
        return f"{visible_text}\n\n--- accessible labels ---\n" + "\n".join(retained)
    return visible_text


def _post_evidence(
    *,
    source_url: HttpUrl,
    captured_at: datetime,
    captured_text: str,
    header: _PostHeaderFields,
    text: str | None,
    content: _PostContentFields,
    engagement: _PostEngagementFields | None,
    field_prefix: str = "",
) -> tuple[PostEvidence, ...]:
    def format_field(name: str) -> str:
        return f"{field_prefix}{name}"

    values: list[tuple[str, str | None]] = [
        (format_field("author.name"), header.author.name),
        (format_field("author.headline"), header.author.headline),
        (format_field("author.relationship_text"), header.author.relationship_text),
        (format_field("author.follower_count_text"), header.author.follower_count_text),
        (format_field("text"), text),
        (format_field("posted_at_text"), header.posted_at_text),
    ]
    if header.author.verified:
        values.append((format_field("author.verified"), "Verified profile"))
    if header.edited:
        values.append((format_field("edited"), "Edited"))
    if header.promoted:
        values.append((format_field("promoted"), "Promoted"))
    if not field_prefix:
        values.append(("visibility_text", header.visibility_text))
    if engagement is not None:
        values.extend(
            (
                (format_field("reaction_count_text"), engagement.reaction_count_text),
                (format_field("comment_count_text"), engagement.comment_count_text),
                (format_field("repost_count_text"), engagement.repost_count_text),
                (format_field("impression_count_text"), engagement.impression_count_text),
                (format_field("viewer_reaction"), engagement.reaction_evidence_text),
                (
                    format_field("comments_enabled"),
                    "Comment" if engagement.comments_enabled else None,
                ),
            )
        )
    for index, attachment in enumerate(content.attachments):
        values.append((format_field(f"attachments[{index}].label"), attachment.label))
        values.append(
            (
                format_field(f"attachments[{index}].visible_text"),
                attachment.visible_text,
            )
        )
        values.append(
            (
                format_field(f"attachments[{index}].page_count"),
                (f"{attachment.page_count} pages" if attachment.page_count is not None else None),
            )
        )
        values.append(
            (
                format_field(f"attachments[{index}].duration_text"),
                attachment.duration_text,
            )
        )
    for index, link in enumerate(content.links):
        values.append((format_field(f"links[{index}]"), link.label))
    for index, mention in enumerate(content.mentions):
        values.append((format_field(f"mentions[{index}]"), mention.label))
    for index, hashtag in enumerate(content.hashtags):
        values.append((format_field(f"hashtags[{index}]"), hashtag))
    if content.poll is not None:
        values.extend(
            (
                (format_field("poll.question"), content.poll.question),
                (format_field("poll.total_votes_text"), content.poll.total_votes_text),
                (format_field("poll.state_text"), content.poll.state_text),
            )
        )
        for index, option in enumerate(content.poll.options):
            values.append((format_field(f"poll.options[{index}].text"), option.text))
            values.append(
                (
                    format_field(f"poll.options[{index}].percentage_text"),
                    option.percentage_text,
                )
            )
    evidence: list[PostEvidence] = []
    seen_fields: set[str] = set()
    for field_name, quote in values:
        if not quote or quote not in captured_text or field_name in seen_fields:
            continue
        evidence.append(
            PostEvidence(
                field=field_name,
                quote=quote,
                source_url=source_url,
                captured_at=captured_at,
            )
        )
        seen_fields.add(field_name)
    return tuple(evidence)


async def _original_post_reference(
    *,
    requested_post_ref: str,
    displayed_post_ref: str,
    embedded_body: Locator,
) -> str:
    if displayed_post_ref != requested_post_ref:
        return displayed_post_ref
    embedded_region = await _embedded_post_region(embedded_body)
    original_post_ref = await _post_reference_for_region(embedded_region)
    if original_post_ref is None or original_post_ref == requested_post_ref:
        raise ParserDriftError(
            "LinkedIn repost has no distinct stable visible original-post reference."
        )
    return original_post_ref


async def _parse_post_detail_page(
    browser: BrowserManager,
    page: Page,
    *,
    requested_post_ref: str,
    source_url: HttpUrl,
    allow_repost_wrapper: bool,
) -> _ParsedPostDetail:
    region, displayed_post_ref = await _detail_region_for_post(page, requested_post_ref)
    body_boxes = await _post_body_boxes(region)
    if len(body_boxes) > 2:
        raise ParserDriftError("LinkedIn post detail exposed more than one bounded repost layer.")
    is_repost_wrapper = len(body_boxes) == 2
    if is_repost_wrapper and not allow_repost_wrapper:
        raise ParserDriftError("LinkedIn repost nesting exceeded the two-page safety bound.")
    original_post_ref = (
        await _original_post_reference(
            requested_post_ref=requested_post_ref,
            displayed_post_ref=displayed_post_ref,
            embedded_body=body_boxes[1],
        )
        if is_repost_wrapper
        else None
    )
    top_body = body_boxes[0] if body_boxes else None
    text_expanded = await _expand_exact_post_body(browser, page, top_body)

    # Expansion can rerender the post. Reacquire exact locators and assert that its
    # stable visible identity and wrapper shape did not change under us.
    region, stable_displayed_post_ref = await _detail_region_for_post(
        page,
        requested_post_ref,
    )
    if stable_displayed_post_ref != displayed_post_ref:
        raise ParserDriftError("LinkedIn post identity changed while expanding visible text.")
    body_boxes = await _post_body_boxes(region)
    if (len(body_boxes) == 2) != is_repost_wrapper:
        raise ParserDriftError("LinkedIn post wrapper changed while expanding visible text.")
    top_body = body_boxes[0] if body_boxes else None
    header = await _post_header_fields(region)
    text = (await top_body.inner_text()).strip() if top_body is not None else None
    if text == "":
        text = None
    if is_repost_wrapper:
        links, hashtags, mentions = await _post_body_links(top_body)
        content = _PostContentFields(
            content_type=PostContentType.REPOST,
            attachments=(),
            links=links,
            hashtags=hashtags,
            mentions=mentions,
            poll=None,
        )
    else:
        content = await _post_content_fields(region, top_body)
    return _ParsedPostDetail(
        source_url=source_url,
        displayed_post_ref=displayed_post_ref,
        header=header,
        text=text,
        content=content,
        engagement=await _post_engagement(region),
        captured_text=await _captured_post_text(region),
        text_expanded=text_expanded,
        is_repost_wrapper=is_repost_wrapper,
        original_post_ref=original_post_ref,
    )


def _reshared_content_from_detail(detail: _ParsedPostDetail) -> PostResharedContent:
    return PostResharedContent(
        post_ref=detail.displayed_post_ref,
        author=detail.header.author,
        text=detail.text,
        posted_at_text=detail.header.posted_at_text,
        edited=detail.header.edited,
        content_type=detail.content.content_type,
        attachments=detail.content.attachments,
        links=detail.content.links,
        hashtags=detail.content.hashtags,
        mentions=detail.content.mentions,
        poll=detail.content.poll,
        visible_text=detail.captured_text,
    )


def _combined_post_capture(details: tuple[_ParsedPostDetail, ...]) -> str:
    return "\n\n".join(
        f"--- source: {detail.source_url} ---\n{detail.captured_text}" for detail in details
    )


class PostDetailPage:
    def __init__(self, browser: BrowserManager) -> None:
        self._browser = browser

    async def read(self, request: PostGetInput) -> PostObservation:
        target = canonical_post_url(request.post_ref)
        async with self._browser.page() as page:
            await self._browser.navigate(page, target)
            requested_detail = await _parse_post_detail_page(
                self._browser,
                page,
                requested_post_ref=request.post_ref,
                source_url=HttpUrl(target),
                allow_repost_wrapper=True,
            )
            details = (requested_detail,)
            original_detail: _ParsedPostDetail | None = None
            reshared: PostResharedContent | None = None
            if requested_detail.original_post_ref is not None:
                original_target = canonical_post_url(requested_detail.original_post_ref)
                await self._browser.navigate(page, original_target)
                original_detail = await _parse_post_detail_page(
                    self._browser,
                    page,
                    requested_post_ref=requested_detail.original_post_ref,
                    source_url=HttpUrl(original_target),
                    allow_repost_wrapper=False,
                )
                details = (requested_detail, original_detail)
                reshared = _reshared_content_from_detail(original_detail)
            captured_text = _combined_post_capture(details)
            captured_at = datetime.now(UTC)
            source_url = HttpUrl(target)
            evidence = list(
                _post_evidence(
                    source_url=requested_detail.source_url,
                    captured_at=captured_at,
                    captured_text=requested_detail.captured_text,
                    header=requested_detail.header,
                    text=requested_detail.text,
                    content=requested_detail.content,
                    engagement=requested_detail.engagement,
                )
            )
            if original_detail is not None:
                evidence.extend(
                    _post_evidence(
                        source_url=original_detail.source_url,
                        captured_at=captured_at,
                        captured_text=original_detail.captured_text,
                        header=original_detail.header,
                        text=original_detail.text,
                        content=original_detail.content,
                        engagement=None,
                        field_prefix="reshared_post.",
                    )
                )
            coverage = PostDetailCoverage(
                requested_post_ref=request.post_ref,
                displayed_post_ref=requested_detail.displayed_post_ref,
                pages_visited=len(details),
                source_urls=tuple(detail.source_url for detail in details),
                text_expanded=all(detail.text_expanded for detail in details),
                attachment_count=len(requested_detail.content.attachments),
                link_count=len(requested_detail.content.links),
                mention_count=len(requested_detail.content.mentions),
                hashtag_count=len(requested_detail.content.hashtags),
                poll_present=requested_detail.content.poll is not None,
                reshared_post_present=reshared is not None,
                captured_at=captured_at,
            )
            return PostObservation(
                post_ref=request.post_ref,
                displayed_post_ref=requested_detail.displayed_post_ref,
                post_url=source_url,
                author=requested_detail.header.author,
                text=requested_detail.text,
                posted_at_text=requested_detail.header.posted_at_text,
                edited=requested_detail.header.edited,
                visibility_text=requested_detail.header.visibility_text,
                promoted=requested_detail.header.promoted,
                content_type=requested_detail.content.content_type,
                attachments=requested_detail.content.attachments,
                links=requested_detail.content.links,
                hashtags=requested_detail.content.hashtags,
                mentions=requested_detail.content.mentions,
                poll=requested_detail.content.poll,
                reshared_post=reshared,
                viewer_reaction=requested_detail.engagement.viewer_reaction,
                reaction_count_text=requested_detail.engagement.reaction_count_text,
                comment_count_text=requested_detail.engagement.comment_count_text,
                repost_count_text=requested_detail.engagement.repost_count_text,
                impression_count_text=requested_detail.engagement.impression_count_text,
                comments_enabled=requested_detail.engagement.comments_enabled,
                visible_text=captured_text,
                evidence=tuple(evidence),
                coverage=coverage,
                captured_at=captured_at,
            )


async def _comment_reference(region: Locator) -> str | None:
    for attribute in ("data-comment-urn", "data-urn", "data-id", "id"):
        value = await region.get_attribute(attribute)
        if value and (reference := comment_reference_from_value(value)):
            return reference
    return None


async def _belongs_to_comment(candidate: Locator, comment_ref: str) -> bool:
    owner = candidate.locator(
        "xpath=ancestor-or-self::*["
        "@data-comment-urn or starts-with(@id, 'replaceableComment_urn:li:comment:')"
        "][1]"
    )
    return bool(await owner.count() and await _comment_reference(owner.first) == comment_ref)


async def _comment_parent_reference(region: Locator) -> str | None:
    for attribute in ("data-parent-comment-urn", "data-parent-comment"):
        value = await region.get_attribute(attribute)
        if value and (reference := comment_reference_from_value(value)):
            return reference
    parent = region.locator(
        "xpath=ancestor::*["
        "@data-comment-urn or starts-with(@id, 'replaceableComment_urn:li:comment:')"
        "][1]"
    )
    if await parent.count():
        return await _comment_reference(parent.first)
    current_reference = await _comment_reference(region)
    current_x = await _comment_identity_x(region)
    if current_reference is None or current_x is None:
        return None
    ancestor = region.locator("xpath=..")
    for _ in range(10):
        if await ancestor.count() != 1:
            break
        descendants = ancestor.locator(_COMMENT_REGION_SELECTOR)
        visible: list[Locator] = []
        references: list[str] = []
        for index in range(min(await descendants.count(), 100)):
            candidate = descendants.nth(index)
            if not await candidate.is_visible():
                continue
            reference = await _comment_reference(candidate)
            if reference is None or reference in references:
                continue
            visible.append(candidate)
            references.append(reference)
        if len(visible) > 1:
            if references[0] == current_reference:
                return None
            if current_reference not in references:
                return None
            root_x = await _comment_identity_x(visible[0])
            if root_x is None or current_x <= root_x + 1:
                return None
            return references[0]
        ancestor = ancestor.locator("xpath=..")
    return None


async def _comment_identity_x(region: Locator) -> float | None:
    links = region.locator('a[href*="/in/"], a[href*="/company/"]')
    positions: list[float] = []
    for index in range(min(await links.count(), 20)):
        link = links.nth(index)
        if not await link.is_visible():
            continue
        box = await link.bounding_box()
        if box is not None:
            positions.append(box["x"])
    return min(positions) if positions else None


async def _comment_attachments(
    region: Locator,
    *,
    comment_ref: str,
) -> tuple[CommentAttachmentObservation, ...]:
    candidates = region.locator(
        "[data-comment-attachment], [data-test-comment-attachment], "
        '[class*="comments-comment-item__comment-image"], '
        '[class*="comments-comment-item__gif"], '
        '[class*="comments-comment-item__media"]'
    )
    attachments: list[CommentAttachmentObservation] = []
    for index in range(min(await candidates.count(), 10)):
        candidate = candidates.nth(index)
        if not await candidate.is_visible() or not await _belongs_to_comment(
            candidate, comment_ref
        ):
            continue
        media = candidate
        tag_name = cast(str, await candidate.evaluate("element => element.tagName"))
        if tag_name not in {"A", "IMG", "VIDEO"}:
            descendants = candidate.locator("img, video, a")
            visible_descendants = [
                descendants.nth(descendant_index)
                for descendant_index in range(min(await descendants.count(), 10))
                if await descendants.nth(descendant_index).is_visible()
            ]
            if len(visible_descendants) == 1:
                media = visible_descendants[0]
        label = next(
            (
                value.strip()
                for value in (
                    await candidate.get_attribute("aria-label"),
                    await media.get_attribute("aria-label"),
                    await media.get_attribute("alt"),
                    await candidate.get_attribute("title"),
                    await media.get_attribute("title"),
                )
                if value and value.strip()
            ),
            None,
        )
        text = (await candidate.inner_text()).strip()
        visible_text = text or label
        if visible_text is None:
            continue
        raw_url = next(
            (
                value
                for value in (
                    await media.get_attribute("href"),
                    await media.get_attribute("src"),
                    await media.get_attribute("poster"),
                )
                if value
            ),
            None,
        )
        resource_url: HttpUrl | None = None
        if raw_url is not None:
            try:
                resource_url = HttpUrl(urljoin("https://www.linkedin.com", raw_url))
            except ValueError:
                resource_url = None
        if label is None and resource_url is None:
            continue
        raw_kind = " ".join(
            value.casefold()
            for value in (
                await candidate.get_attribute("data-kind"),
                await candidate.get_attribute("data-attachment-type"),
                label,
                raw_url,
            )
            if value
        )
        attachment = CommentAttachmentObservation(
            attachment_type=(
                CommentAttachmentType.GIF if "gif" in raw_kind else CommentAttachmentType.PHOTO
            ),
            accessible_label=label,
            resource_url=resource_url,
            visible_text=visible_text,
        )
        if attachment not in attachments:
            attachments.append(attachment)
    return tuple(attachments)


async def _comment_text(
    region: Locator,
    *,
    author: PostAuthor,
    comment_ref: str,
) -> str | None:
    explicit = region.locator(
        "[data-comment-text], .comments-comment-item__main-content, "
        ".comments-comment-item-content-body"
    )
    explicit_values: list[str] = []
    for index in range(min(await explicit.count(), 100)):
        candidate = explicit.nth(index)
        if not await candidate.is_visible() or not await _belongs_to_comment(
            candidate, comment_ref
        ):
            continue
        text = (await candidate.inner_text()).strip()
        if text and text not in explicit_values:
            explicit_values.append(text)
    if len(explicit_values) == 1:
        return explicit_values[0]
    if explicit_values:
        return None

    option_controls = region.get_by_role(
        "button",
        name=re.compile(
            r"(?:view|open).*\boptions?\b.*\bcomment\b|"
            r"\bcomment\b.*\boptions?\b",
            re.IGNORECASE,
        ),
    )
    visible_option_controls = [
        option_controls.nth(index)
        for index in range(min(await option_controls.count(), 20))
        if await option_controls.nth(index).is_visible()
        and await _belongs_to_comment(option_controls.nth(index), comment_ref)
    ]
    if len(visible_option_controls) > 1:
        return None

    # LinkedIn's current post-detail surface renders the comment body as an
    # otherwise unlabelled paragraph immediately after the accessible comment
    # options control. Starting from that control avoids mistaking the visible
    # author card for body text; ownership checks exclude nested replies.
    paragraphs = (
        visible_option_controls[0].locator("xpath=following::p")
        if visible_option_controls
        else region.locator("p")
    )
    values: list[str] = []
    author_metadata = {
        value.casefold() for value in (author.name, author.headline) if value is not None
    }
    for index in range(min(await paragraphs.count(), 100)):
        candidate = paragraphs.nth(index)
        if not await candidate.is_visible() or not await _belongs_to_comment(
            candidate, comment_ref
        ):
            continue
        text = (await candidate.inner_text()).strip()
        normalized = " ".join(text.split())
        if (
            not normalized
            or normalized.casefold() in author_metadata
            or _COMMENT_TIME_PATTERN.fullmatch(normalized)
            or normalized.casefold() in _POST_ACTION_LINES
            or any(pattern.fullmatch(normalized) for pattern in _COUNT_PATTERNS.values())
        ):
            continue
        if text not in values:
            values.append(text)
            if visible_option_controls:
                return text
    return values[0] if len(values) == 1 else None


async def _comment_from_region(
    region: Locator,
    *,
    expected_post_ref: str,
) -> CommentObservation | None:
    reference = await _comment_reference(region)
    if reference is None:
        return None
    native_post_ref = post_reference_from_comment_ref(reference)
    if native_post_ref != expected_post_ref:
        return None
    parent_reference = await _comment_parent_reference(region)
    author = await _post_author(region)
    if author is None:
        return None
    text = await _comment_text(
        region,
        author=author,
        comment_ref=reference,
    )
    attachments = await _comment_attachments(region, comment_ref=reference)
    visible_text = (await region.inner_text()).strip()
    for attachment in attachments:
        if attachment.visible_text not in visible_text:
            visible_text = f"{visible_text}\n{attachment.visible_text}".strip()
    if (not text and not attachments) or not visible_text:
        return None
    lines = _unique_lines(visible_text)
    posted_at = next(
        (line for line in lines if _COMMENT_TIME_PATTERN.fullmatch(line)),
        None,
    )
    return CommentObservation(
        comment_ref=reference,
        post_ref=native_post_ref,
        parent_comment_ref=parent_reference,
        author=author,
        text=text,
        attachments=attachments,
        posted_at_text=posted_at,
        edited=bool(posted_at and "edited" in posted_at.casefold()),
        reaction_count_text=_first_count(lines, "reaction"),
        reply_count_text=_first_count(lines, "reply"),
        visible_text=visible_text,
    )


async def post_summary_from_region(region: Locator) -> PostSummary | None:
    """Parse one visible post region for another narrow page object."""

    return await _post_summary_from_region(region)


async def region_for_post(page: Page, post_ref: str) -> Locator:
    """Resolve one exact visible post region by its stable reference."""

    return await _region_for_post(page, post_ref)


async def comment_reference(region: Locator) -> str | None:
    """Return the stable reference exposed by one visible comment region."""

    return await _comment_reference(region)


def comment_regions(page: Page) -> Locator:
    """Return bounded stable comment containers from the visible discussion."""

    return page.locator("main").locator(_COMMENT_REGION_SELECTOR)


async def _visible_comment_regions(page: Page) -> tuple[Locator, ...]:
    regions = comment_regions(page)
    visible: list[Locator] = []
    for index in range(min(await regions.count(), 1_000)):
        region = regions.nth(index)
        if await region.is_visible():
            visible.append(region)
    return tuple(visible)


async def comment_from_region(
    region: Locator,
    *,
    expected_post_ref: str,
) -> CommentObservation | None:
    """Parse one visible comment region for another narrow page object."""

    return await _comment_from_region(region, expected_post_ref=expected_post_ref)


async def discussion_post_reference(page: Page, requested_post_ref: str) -> str:
    """Resolve the single native post reference used by the visible discussion."""

    native_post_refs: set[str] = set()
    regions = comment_regions(page)
    for index in range(min(await regions.count(), 1_000)):
        region = regions.nth(index)
        if not await region.is_visible():
            continue
        reference = await _comment_reference(region)
        if reference is None:
            raise ParserDriftError(
                "A stable visible LinkedIn comment has no valid comment reference."
            )
        native_post_refs.add(post_reference_from_comment_ref(reference))
    if not native_post_refs:
        return requested_post_ref
    if len(native_post_refs) != 1:
        raise ParserDriftError(
            "The visible LinkedIn discussion contains comments from multiple posts."
        )
    return next(iter(native_post_refs))


class PostCommentsPage:
    def __init__(self, browser: BrowserManager, *, max_expansion_rounds: int) -> None:
        if max_expansion_rounds < 0:
            raise ValueError("Comment expansion bound cannot be negative.")
        self._browser = browser
        self._max_expansion_rounds = max_expansion_rounds

    async def collect(
        self,
        request: PostCommentsListInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[
        tuple[CommentThread, ...],
        PostCommentsCoverage,
        str,
        str,
    ]:
        limit = request.page_size if result_limit is None else result_limit
        if limit < 1:
            raise ValueError("Post-comment result limit must be positive.")
        target = canonical_post_url(request.post_ref)
        expansion_rounds = 0
        async with self._browser.page() as page:
            await self._browser.navigate(page, target)
            await _expand_visible_content(page)
            post_region = await _region_for_post(page, request.post_ref)
            visible_regions = await _visible_comment_regions(page)
            if not visible_regions:
                controls = post_region.get_by_role(
                    "button",
                    name=re.compile(r"^Comment(?:\b|$)", re.IGNORECASE),
                )
                visible_controls = [
                    controls.nth(index)
                    for index in range(min(await controls.count(), 20))
                    if await controls.nth(index).is_visible()
                ]
                if len(visible_controls) > 1:
                    raise ParserDriftError(
                        "LinkedIn discussion has no unique visible Comment control."
                    )
                if visible_controls:
                    await self._browser.click_visible_control(page, visible_controls[0])
                    for _ in range(20):
                        visible_regions = await _visible_comment_regions(page)
                        if visible_regions:
                            break
                        await page.wait_for_timeout(250)
            desired_sort = (
                "Most recent" if request.sort_by is CommentSort.MOST_RECENT else "Most relevant"
            )
            sort_buttons = page.get_by_role(
                "button",
                name=re.compile(r"^(?:Most relevant|Most recent)$", re.IGNORECASE),
            )
            if await sort_buttons.count():
                current = sort_buttons.first
                if desired_sort.casefold() not in ((await current.inner_text()).strip().casefold()):
                    await current.click()
                    option = page.get_by_role(
                        "option",
                        name=re.compile(rf"^{re.escape(desired_sort)}$", re.IGNORECASE),
                    )
                    if not await option.count():
                        option = page.get_by_text(
                            re.compile(rf"^{re.escape(desired_sort)}$", re.IGNORECASE),
                            exact=True,
                        )
                    visible_options = [
                        option.nth(index)
                        for index in range(await option.count())
                        if await option.nth(index).is_visible()
                    ]
                    if len(visible_options) != 1:
                        raise ParserDriftError(
                            "LinkedIn comment sorting has no unique requested visible option."
                        )
                    await visible_options[0].click()
                    if visible_regions:
                        # LinkedIn briefly removes the discussion while applying a
                        # new sort. Do not mistake that transient empty DOM for an
                        # empty discussion.
                        await page.wait_for_timeout(250)
                        for _ in range(20):
                            visible_regions = await _visible_comment_regions(page)
                            if visible_regions:
                                break
                            await page.wait_for_timeout(250)
                        else:
                            raise ParserDriftError(
                                "LinkedIn comment sorting did not restore the visible discussion."
                            )
            for _ in range(self._max_expansion_rounds):
                controls = page.get_by_role(
                    "button",
                    name=re.compile(
                        r"(?:load more comments|load previous replies|see previous replies|"
                        r"show more replies|"
                        r"view replies|more replies)",
                        re.IGNORECASE,
                    ),
                )
                visible_controls = [
                    controls.nth(index)
                    for index in range(min(await controls.count(), 100))
                    if await controls.nth(index).is_visible()
                ]
                if not visible_controls:
                    break
                baseline = await _visible_comment_signature(page)
                for control in visible_controls:
                    await control.click()
                expansion_rounds += 1
                await wait_for_collection_change(
                    page,
                    baseline=baseline,
                    read_signature=lambda: _visible_comment_signature(page),
                    attempts=_COLLECTION_POLL_ATTEMPTS,
                    delay_ms=_COLLECTION_POLL_DELAY_MS,
                )
            regions = comment_regions(page)
            native_post_ref = await discussion_post_reference(page, request.post_ref)
            comments: list[CommentObservation] = []
            comment_refs: set[str] = set()
            for index in range(min(await regions.count(), 1_000)):
                region = regions.nth(index)
                if not await region.is_visible():
                    continue
                reference = await _comment_reference(region)
                if (
                    reference is None
                    or post_reference_from_comment_ref(reference) != native_post_ref
                ):
                    continue
                comment = await _comment_from_region(
                    region,
                    expected_post_ref=native_post_ref,
                )
                if comment is None:
                    raise ParserDriftError(
                        "A stable visible LinkedIn comment has no unambiguous content."
                    )
                if comment.comment_ref not in comment_refs:
                    comments.append(comment)
                    comment_refs.add(comment.comment_ref)
            captured_text = (await page.locator("main").inner_text()).strip()
            if not captured_text:
                raise ParserDriftError("LinkedIn discussion returned no visible source text.")
            accessible_attachment_evidence = tuple(
                dict.fromkeys(
                    comment.visible_text
                    for comment in comments
                    if comment.attachments and comment.visible_text not in captured_text
                )
            )
            if accessible_attachment_evidence:
                captured_text = (
                    f"{captured_text}\n\n--- accessible comment attachment evidence ---\n"
                    + "\n".join(accessible_attachment_evidence)
                )

        top_level = [comment for comment in comments if comment.parent_comment_ref is None]
        replies = [comment for comment in comments if comment.parent_comment_ref is not None]
        selected_top = top_level[:limit]
        threads = tuple(
            CommentThread(
                comment=comment,
                replies=tuple(
                    reply for reply in replies if reply.parent_comment_ref == comment.comment_ref
                )[: request.max_replies_per_comment],
            )
            for comment in selected_top
        )
        replies_returned = sum(len(thread.replies) for thread in threads)
        truncated = (
            len(top_level) > len(selected_top)
            or any(
                len(
                    [
                        reply
                        for reply in replies
                        if reply.parent_comment_ref == thread.comment.comment_ref
                    ]
                )
                > len(thread.replies)
                for thread in threads
            )
            or (expansion_rounds == self._max_expansion_rounds and self._max_expansion_rounds > 0)
        )
        coverage = PostCommentsCoverage(
            post_ref=request.post_ref,
            discussion_post_ref=native_post_ref,
            sort_by=request.sort_by,
            expansion_rounds=expansion_rounds,
            top_level_visible=len(top_level),
            top_level_returned=len(threads),
            replies_visible=len(replies),
            replies_returned=replies_returned,
            max_comments=limit,
            max_replies_per_comment=request.max_replies_per_comment,
            truncated=truncated,
            captured_at=datetime.now(UTC),
        )
        return threads, coverage, captured_text, target
