"""Visible post UI parsing shared by post read pages."""

from __future__ import annotations

import re
from contextlib import suppress
from dataclasses import dataclass
from typing import cast
from urllib.parse import urljoin, urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import HttpUrl

from linkedin_mcp.errors import InvalidTargetError, ParserDriftError
from linkedin_mcp.tools._shared.urls import (
    canonical_company_url,
    comment_reference_from_value,
    company_slug_from_url,
    post_reference_from_comment_ref,
    post_reference_from_value,
    profile_slug_from_url,
    validate_linkedin_url,
)
from linkedin_mcp.tools.posts.comments.list.models.comment_attachment_observation import (
    CommentAttachmentObservation,
)
from linkedin_mcp.tools.posts.comments.list.models.comment_attachment_type import (
    CommentAttachmentType,
)
from linkedin_mcp.tools.posts.comments.list.models.comment_observation import CommentObservation
from linkedin_mcp.tools.posts.get.models.post_attachment import PostAttachment
from linkedin_mcp.tools.posts.get.models.post_author_type import PostAuthorType
from linkedin_mcp.tools.posts.get.models.post_link import PostLink
from linkedin_mcp.tools.posts.get.models.post_poll import PostPoll
from linkedin_mcp.tools.posts.get.models.post_poll_option import PostPollOption
from linkedin_mcp.tools.posts.get.models.post_poll_state import PostPollState
from linkedin_mcp.tools.posts.models.post_author import PostAuthor
from linkedin_mcp.tools.posts.react.models.reaction_state import ReactionState
from linkedin_mcp.tools.posts.search.models.post_content_type import PostContentType

COUNT_PATTERNS = {
    "reaction": re.compile(
        r"\b[\d,.+]+\s+(?:reactions?|likes?)\b",
        re.IGNORECASE,
    ),
    "comment": re.compile(r"\b[\d,.+]+\s+comments?\b", re.IGNORECASE),
    "repost": re.compile(r"\b[\d,.+]+\s+reposts?\b", re.IGNORECASE),
    "reply": re.compile(r"\b[\d,.+]+\s+repl(?:y|ies)\b", re.IGNORECASE),
}

POST_ACTION_LINES = frozenset(
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

COMMENT_AUTHOR_BADGES = frozenset({"author"})

POST_REGION_SELECTOR = (
    "article, [data-post-urn], [data-urn*='urn:li:activity'], "
    "[data-urn*='urn:li:share'], [data-urn*='urn:li:ugcPost'], "
    "[role='listitem']:has(button[aria-label^='Open control menu for post by '])"
)

COMMENT_REGION_SELECTOR = (
    "[data-comment-urn], [data-id^='urn:li:comment:'], [id^='replaceableComment_urn:li:comment:']"
)

COLLECTION_POLL_DELAY_MS = 250

COMMENT_TIME_PATTERN = re.compile(
    r"(?:\d+\s*[smhdw](?:\s*·\s*Edited)?|just now)",
    re.IGNORECASE,
)

POST_MENU_PATTERN = re.compile(r"^Open control menu for post by (.+)$", re.IGNORECASE)

POST_AGE_PATTERN = re.compile(
    r"^(?:\d+\s*(?:s|m|h|d|w|mo|yr)s?|just now)"
    r"(?:\s*[•·]\s*(?:Edited(?:\s*[•·])?)?)?$",
    re.IGNORECASE,
)

POST_RELATIONSHIP_PATTERN = re.compile(
    r"(?:^|[•·]\s*)(1st|2nd|3rd(?:\+)?)(?=$|[\s•·])",
    re.IGNORECASE,
)

POST_FOLLOWER_PATTERN = re.compile(r"\b[\d,.+]+\s+followers?\b", re.IGNORECASE)

POST_PERCENTAGE_PATTERN = re.compile(r"^[\d.]+\s*%$")

POST_VOTE_COUNT_PATTERN = re.compile(r"^[\d,.+]+\s+votes?$", re.IGNORECASE)

POST_POLL_STATE_PATTERN = re.compile(r"^Poll (?:closed|ended)$", re.IGNORECASE)

POST_DOCUMENT_PAGE_PATTERN = re.compile(
    r"^Page ([0-9]+) of ([0-9]+)$",
    re.IGNORECASE,
)

POST_DOCUMENT_TOTAL_PATTERN = re.compile(r"^(?P<total>[0-9]+)\s+pages?$", re.IGNORECASE)

POST_IMPRESSION_PATTERN = re.compile(r"^[\d,.+]+\s+impressions?$", re.IGNORECASE)

POST_COUNT_ONLY_PATTERN = re.compile(r"^[\d,.+]+$")

POST_DETAIL_MAX_MENUS = 20

POST_DETAIL_MAX_ANCHORS = 300

POST_DETAIL_MAX_MEDIA = 100

POST_DETAIL_MAX_ACCESSIBLE_LABELS = 1_000

POST_DETAIL_MAX_BODY_BOXES = 10

LINKEDIN_POST_SHORT_PATH = re.compile(r"^/p/[A-Za-z0-9_-]+/?$")

INSTALL_CLIPBOARD_CAPTURE = """
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

RESTORE_CLIPBOARD_CAPTURE = """
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
class PostHeaderFields:
    region: Locator
    author: PostAuthor
    posted_at_text: str | None
    edited: bool
    visibility_text: str | None
    promoted: bool


class UnsupportedPostAuthorIdentityError(ParserDriftError):
    """A selected post has a LinkedIn identity outside the public slug contract."""


@dataclass(frozen=True, slots=True)
class PostContentFields:
    content_type: PostContentType
    attachments: tuple[PostAttachment, ...]
    links: tuple[PostLink, ...]
    hashtags: tuple[str, ...]
    mentions: tuple[PostLink, ...]
    poll: PostPoll | None


@dataclass(frozen=True, slots=True)
class PostEngagementFields:
    viewer_reaction: ReactionState | None
    reaction_count_text: str | None
    comment_count_text: str | None
    repost_count_text: str | None
    impression_count_text: str | None
    comments_enabled: bool
    reaction_evidence_text: str | None


def unique_lines(value: str) -> list[str]:
    lines: list[str] = []
    for raw_line in value.splitlines():
        line = " ".join(raw_line.split())
        if line and line not in lines:
            lines.append(line)
    return lines


async def prepare_visible_content(page: Page) -> None:
    main = page.locator("main")
    try:
        await main.wait_for(state="visible", timeout=10_000)
    except PlaywrightTimeoutError as error:
        raise ParserDriftError("LinkedIn content surface has no visible main region.") from error


async def post_reference_for_region(region: Locator) -> str | None:
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
        installed = cast(bool, await page.evaluate(INSTALL_CLIPBOARD_CAPTURE))
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
        copied_value: str | None = None
        for _ in range(20):
            await page.wait_for_timeout(100)
            copied_value = cast(
                str | None,
                await page.evaluate("window.__linkedinMcpCopiedPostLink"),
            )
            if copied_value:
                break
        if page.url != source_url:
            raise ParserDriftError("LinkedIn Copy link to post unexpectedly navigated away.")
    except PlaywrightError as error:
        raise ParserDriftError(
            "LinkedIn post link could not be captured from its visible menu."
        ) from error
    finally:
        with suppress(PlaywrightError):
            await page.evaluate(RESTORE_CLIPBOARD_CAPTURE)
        with suppress(PlaywrightError):
            await page.keyboard.press("Escape")
    if not copied_value:
        raise ParserDriftError("LinkedIn Copy link to post returned no stable visible link.")
    parsed_copy = urlsplit(copied_value)
    if (
        parsed_copy.scheme == "https"
        and parsed_copy.hostname == "lnkd.in"
        and parsed_copy.netloc.casefold() == "lnkd.in"
        and not parsed_copy.query
        and not parsed_copy.fragment
        and LINKEDIN_POST_SHORT_PATH.fullmatch(parsed_copy.path)
    ):
        # The visible action now sometimes returns an opaque LinkedIn short
        # link. It contains no stable post URN, and resolving it would broaden
        # this collection beyond the configured LinkedIn hosts. Classify the
        # selected card as unsupported instead of inventing an identity.
        return None
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


async def post_author(region: Locator) -> PostAuthor | None:
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
        lines = unique_lines((await link.inner_text()).strip())
        name = lines[0] if lines else None
        image_only = not lines
        if not name:
            image = link.locator("img[alt]")
            if await image.count():
                name = (await image.first.get_attribute("alt") or "").strip()
        if not name:
            continue
        metadata = lines[1:]
        relationship = post_relationship(metadata)
        headline_candidates = [
            line
            for line in metadata
            if line.casefold() not in COMMENT_AUTHOR_BADGES
            and POST_RELATIONSHIP_PATTERN.search(line) is None
            and POST_FOLLOWER_PATTERN.search(line) is None
        ]
        headline = headline_candidates[-1] if headline_candidates else None
        if profile_slug := profile_slug_from_url(url):
            author = PostAuthor(
                author_type=PostAuthorType.MEMBER,
                name=name,
                profile_slug=profile_slug,
                author_url=HttpUrl(f"https://www.linkedin.com/in/{profile_slug}/"),
                headline=headline,
                relationship_text=relationship,
            )
        elif company_slug := company_slug_from_url(url):
            author = PostAuthor(
                author_type=PostAuthorType.COMPANY,
                name=name,
                company_slug=company_slug,
                author_url=HttpUrl(canonical_company_url(company_slug)),
                headline=headline,
                relationship_text=relationship,
            )
        else:
            continue
        if not image_only:
            return author
        image_only_fallback = image_only_fallback or author
    return image_only_fallback


def first_count(lines: list[str], kind: str) -> str | None:
    pattern = COUNT_PATTERNS[kind]
    return next(
        (match.group(0) for line in lines if (match := pattern.search(line)) is not None),
        None,
    )


async def regions_for_post(page: Page, post_ref: str) -> list[Locator]:
    candidates = page.locator("main").locator(POST_REGION_SELECTOR)
    matches: list[Locator] = []
    for index in range(min(await candidates.count(), 500)):
        candidate = candidates.nth(index)
        if await candidate.is_visible() and await post_reference_for_region(candidate) == post_ref:
            matches.append(candidate)
    return matches


async def bounded_visible_locators(
    locator: Locator,
    *,
    limit: int,
    description: str,
) -> list[Locator]:
    count = await locator.count()
    if count > limit:
        raise ParserDriftError(f"LinkedIn post detail exceeded the bounded {description} limit.")
    return [locator.nth(index) for index in range(count) if await locator.nth(index).is_visible()]


def https_url(value: str | None) -> HttpUrl | None:
    if not value:
        return None
    absolute = urljoin("https://www.linkedin.com", value)
    if urlsplit(absolute).scheme != "https":
        return None
    return HttpUrl(absolute)


async def detail_post_regions(page: Page) -> list[tuple[Locator, str]]:
    menus = await bounded_visible_locators(
        page.locator("main").get_by_role(
            "button",
            name=POST_MENU_PATTERN,
        ),
        limit=POST_DETAIL_MAX_MENUS,
        description="post-menu",
    )
    values: list[tuple[Locator, str]] = []
    for menu in menus:
        region = menu.locator(
            "xpath=ancestor::*[@role='listitem' or @role='article' or self::article][1]"
        )
        if not await region.count():
            continue
        reference = await post_reference_for_region(region.first)
        if reference is not None:
            values.append((region.first, reference))
    return values


async def detail_region_for_post(
    page: Page,
    requested_post_ref: str,
) -> tuple[Locator, str]:
    exact_regions = await regions_for_post(page, requested_post_ref)
    if len(exact_regions) == 1:
        return exact_regions[0], requested_post_ref
    if len(exact_regions) > 1:
        raise ParserDriftError(
            "LinkedIn post detail exposed multiple visible copies of the requested post."
        )
    regions = await detail_post_regions(page)
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


async def post_body_boxes(region: Locator) -> list[Locator]:
    current = await bounded_visible_locators(
        region.locator('[data-testid="expandable-text-box"]'),
        limit=POST_DETAIL_MAX_BODY_BOXES,
        description="post-body",
    )
    if current:
        return current
    return await bounded_visible_locators(
        region.locator(".feed-shared-update-v2__description"),
        limit=POST_DETAIL_MAX_BODY_BOXES,
        description="legacy post-body",
    )


async def post_header_region(region: Locator) -> tuple[Locator, str]:
    menus = await bounded_visible_locators(
        region.get_by_role("button", name=POST_MENU_PATTERN),
        limit=3,
        description="exact post-menu",
    )
    if len(menus) != 1:
        raise ParserDriftError("LinkedIn post detail has no unique visible exact post menu.")
    menu_label = (await menus[0].get_attribute("aria-label") or "").strip()
    match = POST_MENU_PATTERN.fullmatch(menu_label)
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


async def author_from_identity_region(
    region: Locator,
    *,
    expected_name: str | None,
) -> PostAuthor:
    anchors = await bounded_visible_locators(
        region.locator('a[href*="/in/"], a[href*="/company/"]'),
        limit=50,
        description="author-identity link",
    )
    candidates: dict[
        tuple[PostAuthorType, str],
        tuple[int, str, HttpUrl],
    ] = {}
    unsupported_linkedin_identity = False
    normalized_expected = expected_name.casefold() if expected_name else None
    for anchor in anchors:
        href = await anchor.get_attribute("href")
        url = https_url(href)
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
            parsed = urlsplit(absolute)
            if (
                parsed.hostname == "www.linkedin.com"
                and re.match(r"^/(?:in|company)/[^/]+(?:/|$)", parsed.path) is not None
            ):
                unsupported_linkedin_identity = True
            continue
        lines = unique_lines((await anchor.inner_text()).strip())
        alt_values: list[str] = []
        images = await bounded_visible_locators(
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
        if unsupported_linkedin_identity:
            raise UnsupportedPostAuthorIdentityError(
                "LinkedIn post author identity is outside the supported typed slug contract."
            )
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


def post_age(lines: list[str]) -> str | None:
    return next((line for line in lines if POST_AGE_PATTERN.fullmatch(line)), None)


def post_relationship(lines: list[str]) -> str | None:
    for line in lines:
        if match := POST_RELATIONSHIP_PATTERN.search(line):
            return match.group(1)
    return None


def post_follower_count(lines: list[str]) -> str | None:
    for line in lines:
        if match := POST_FOLLOWER_PATTERN.search(line):
            return match.group(0)
    return None


async def visible_accessible_values(
    region: Locator,
    selector: str,
    attribute: str,
    *,
    limit: int = POST_DETAIL_MAX_ACCESSIBLE_LABELS,
) -> tuple[str, ...]:
    values: list[str] = []
    for item in await bounded_visible_locators(
        region.locator(selector),
        limit=limit,
        description="accessible-evidence",
    ):
        value = " ".join((await item.get_attribute(attribute) or "").split())
        if value and value not in values:
            values.append(value)
    return tuple(values)


async def post_header_fields(region: Locator) -> PostHeaderFields:
    header, expected_name = await post_header_region(region)
    lines = unique_lines((await header.inner_text()).strip())
    base_author = await author_from_identity_region(
        header,
        expected_name=expected_name,
    )
    relationship = post_relationship(lines)
    posted_at = post_age(lines)
    follower_count = post_follower_count(lines)
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
        and POST_AGE_PATTERN.fullmatch(line) is None
        and POST_RELATIONSHIP_PATTERN.search(line) is None
        and POST_FOLLOWER_PATTERN.search(line) is None
    ]
    headline = max(headline_candidates, key=len, default=None)
    header_labels = await visible_accessible_values(
        header,
        "[aria-label]",
        "aria-label",
    )
    visibility_values = tuple(
        value
        for value in await visible_accessible_values(
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
    return PostHeaderFields(
        region=header,
        author=author,
        posted_at_text=posted_at,
        edited=any("edited" in line.casefold() for line in lines),
        visibility_text=visibility,
        promoted=any("promoted" in line.casefold() for line in lines),
    )


async def post_body_links(
    body: Locator | None,
) -> tuple[tuple[PostLink, ...], tuple[str, ...], tuple[PostLink, ...]]:
    if body is None:
        return (), (), ()
    anchors = await bounded_visible_locators(
        body.locator("a[href]"),
        limit=POST_DETAIL_MAX_ANCHORS,
        description="post-body link",
    )
    links: list[PostLink] = []
    hashtags: list[str] = []
    mentions: list[PostLink] = []
    for anchor in anchors:
        href = await anchor.get_attribute("href")
        url = https_url(href)
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


async def poll_options_from_region(region: Locator) -> tuple[PostPollOption, ...]:
    radio_options: list[PostPollOption] = []
    for radio in await bounded_visible_locators(
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
        if POST_PERCENTAGE_PATTERN.fullmatch(percentage_text) is None:
            continue
        option_region: Locator | None = None
        candidate = percentage
        for _ in range(2):
            candidate = candidate.locator("..")
            lines = unique_lines((await candidate.inner_text()).strip())
            labels = [
                line
                for line in lines
                if POST_PERCENTAGE_PATTERN.fullmatch(line) is None
                and POST_VOTE_COUNT_PATTERN.fullmatch(line) is None
            ]
            if labels:
                option_region = candidate
                break
        if option_region is None:
            continue
        lines = unique_lines((await option_region.inner_text()).strip())
        labels = [
            line
            for line in lines
            if POST_PERCENTAGE_PATTERN.fullmatch(line) is None
            and POST_VOTE_COUNT_PATTERN.fullmatch(line) is None
        ]
        if not labels:
            continue
        label = labels[0]
        vote_count = next(
            (line for line in lines if POST_VOTE_COUNT_PATTERN.fullmatch(line)),
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


async def post_poll(region: Locator) -> PostPoll | None:
    closed = await bounded_visible_locators(
        region.get_by_text(POST_POLL_STATE_PATTERN),
        limit=5,
        description="poll-state",
    )
    votes = await bounded_visible_locators(
        region.get_by_text(POST_VOTE_COUNT_PATTERN),
        limit=10,
        description="poll-vote-count",
    )
    radios = await bounded_visible_locators(
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
        options = await poll_options_from_region(poll_region)
        if len(options) >= 2:
            break
    if len(options) < 2:
        if closed:
            raise ParserDriftError(
                "LinkedIn exposed a poll state without complete visible poll options."
            )
        return None
    poll_text = (await poll_region.inner_text()).strip()
    lines = unique_lines(poll_text)
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
        and POST_VOTE_COUNT_PATTERN.fullmatch(line) is None
        and POST_POLL_STATE_PATTERN.fullmatch(line) is None
        and line not in {"·", "•"}
    ]
    if not question_candidates:
        raise ParserDriftError("LinkedIn poll has no visible question.")
    total_votes = next(
        (line for line in reversed(lines) if POST_VOTE_COUNT_PATTERN.fullmatch(line)),
        None,
    )
    state_text = next(
        (line for line in lines if POST_POLL_STATE_PATTERN.fullmatch(line)),
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


async def post_document_attachment(region: Locator) -> PostAttachment | None:
    page_controls = await bounded_visible_locators(
        region.get_by_role("button", name=POST_DOCUMENT_PAGE_PATTERN),
        limit=100,
        description="document-page control",
    )
    full_screen = await bounded_visible_locators(
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
        if match := POST_DOCUMENT_PAGE_PATTERN.fullmatch(label):
            totals.append(int(match.group(2)))
    viewer = full_screen[0] if full_screen else page_controls[0]
    for _ in range(8):
        viewer = viewer.locator("..")
        if await viewer.get_by_role(
            "button",
            name=POST_DOCUMENT_PAGE_PATTERN,
        ).count():
            break
    visible_text = (await viewer.inner_text()).strip()
    lines = unique_lines(visible_text)
    for line in lines:
        if match := POST_DOCUMENT_TOTAL_PATTERN.fullmatch(line):
            totals.append(int(match.group("total")))
    page_count = max(totals) if totals else None
    title = next(
        (
            line
            for line in lines
            if POST_DOCUMENT_TOTAL_PATTERN.fullmatch(line) is None
            and POST_DOCUMENT_PAGE_PATTERN.fullmatch(line) is None
            and line not in {"·", "•"}
        ),
        None,
    )
    preview_url: HttpUrl | None = None
    preview_label: str | None = None
    for image in await bounded_visible_locators(
        viewer.locator("img"),
        limit=POST_DETAIL_MAX_MEDIA,
        description="document-preview image",
    ):
        box = await image.bounding_box()
        if box is None or box["width"] < 100 or box["height"] < 100:
            continue
        preview_url = https_url(await image.get_attribute("src"))
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


def card_content_type(url: str, visible_text: str) -> PostContentType:
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


async def card_preview_url(anchor: Locator) -> HttpUrl | None:
    candidate = anchor
    for _ in range(5):
        images = await bounded_visible_locators(
            candidate.locator("img"),
            limit=POST_DETAIL_MAX_MEDIA,
            description="link-card preview",
        )
        for image in images:
            box = await image.bounding_box()
            if box is not None and box["width"] >= 100 and box["height"] >= 70:
                return https_url(await image.get_attribute("src"))
        candidate = candidate.locator("..")
    return None


async def post_link_cards(
    region: Locator,
) -> tuple[PostAttachment, ...]:
    anchors = await bounded_visible_locators(
        region.locator("a[href]"),
        limit=POST_DETAIL_MAX_ANCHORS,
        description="post-card link",
    )
    values: list[PostAttachment] = []
    for anchor in anchors:
        if await anchor.locator("xpath=ancestor::*[@data-testid='expandable-text-box'][1]").count():
            continue
        href = await anchor.get_attribute("href")
        url = https_url(href)
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
        lines = unique_lines(text)
        if box is None or box["width"] < 180 or len(lines) < 2:
            continue
        attachment = PostAttachment(
            content_type=card_content_type(absolute, text),
            label=lines[0][:2_000],
            url=url,
            preview_url=await card_preview_url(anchor),
            visible_text=text,
        )
        if attachment not in values:
            values.append(attachment)
    if len(values) > 5:
        raise ParserDriftError("LinkedIn post detail exposed too many visible link cards.")
    return tuple(values)


async def post_video_attachments(region: Locator) -> tuple[PostAttachment, ...]:
    values: list[PostAttachment] = []
    videos = await bounded_visible_locators(
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
            url=https_url(await video.get_attribute("src")),
            preview_url=https_url(await video.get_attribute("poster")),
            visible_text=label,
        )
        if attachment not in values:
            values.append(attachment)
    return tuple(values)


async def post_image_attachments(
    region: Locator,
    *,
    excluded_preview_urls: frozenset[str],
) -> tuple[PostAttachment, ...]:
    values: list[PostAttachment] = []
    for image in await bounded_visible_locators(
        region.locator("img"),
        limit=POST_DETAIL_MAX_MEDIA,
        description="post-image",
    ):
        box = await image.bounding_box()
        if box is None or box["width"] < 100 or box["height"] < 100:
            continue
        owner = image.locator("xpath=ancestor::a[@href][1]")
        if await owner.count():
            owner_url = https_url(await owner.first.get_attribute("href"))
            if owner_url is not None and (
                profile_slug_from_url(str(owner_url)) or company_slug_from_url(str(owner_url))
            ):
                continue
        source_url = https_url(await image.get_attribute("src"))
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


async def post_content_fields(
    region: Locator,
    body: Locator | None,
) -> PostContentFields:
    links, hashtags, mentions = await post_body_links(body)
    poll = await post_poll(region)
    if poll is not None:
        return PostContentFields(
            content_type=PostContentType.POLL,
            attachments=(),
            links=links,
            hashtags=hashtags,
            mentions=mentions,
            poll=poll,
        )
    document = await post_document_attachment(region)
    if document is not None:
        return PostContentFields(
            content_type=PostContentType.DOCUMENT,
            attachments=(document,),
            links=links,
            hashtags=hashtags,
            mentions=mentions,
            poll=None,
        )
    videos = await post_video_attachments(region)
    if videos:
        return PostContentFields(
            content_type=videos[0].content_type,
            attachments=videos,
            links=links,
            hashtags=hashtags,
            mentions=mentions,
            poll=None,
        )
    cards = await post_link_cards(region)
    if cards:
        return PostContentFields(
            content_type=cards[0].content_type,
            attachments=cards,
            links=links,
            hashtags=hashtags,
            mentions=mentions,
            poll=None,
        )
    images = await post_image_attachments(
        region,
        excluded_preview_urls=frozenset(),
    )
    return PostContentFields(
        content_type=PostContentType.IMAGE if images else PostContentType.TEXT,
        attachments=images,
        links=links,
        hashtags=hashtags,
        mentions=mentions,
        poll=None,
    )


def visible_count_text(value: str) -> str | None:
    normalized = " ".join(value.replace("\u200b", "").split())
    return normalized if POST_COUNT_ONLY_PATTERN.fullmatch(normalized) else None


async def one_visible_button(
    region: Locator,
    pattern: re.Pattern[str],
    *,
    description: str,
) -> Locator | None:
    values = await bounded_visible_locators(
        region.get_by_role("button", name=pattern),
        limit=5,
        description=description,
    )
    if len(values) > 1:
        raise ParserDriftError(f"LinkedIn post detail has an ambiguous visible {description}.")
    return values[0] if values else None


async def post_engagement(region: Locator) -> PostEngagementFields:
    reaction_button = await one_visible_button(
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
        reaction_count = visible_count_text(await reaction_button.inner_text())
    comment_button = await one_visible_button(
        region,
        re.compile(r"^Comment$", re.IGNORECASE),
        description="comment control",
    )
    repost_button = await one_visible_button(
        region,
        re.compile(r"^Repost$", re.IGNORECASE),
        description="repost control",
    )
    impressions: list[str] = []
    for anchor in await bounded_visible_locators(
        region.locator("a[href]"),
        limit=POST_DETAIL_MAX_ANCHORS,
        description="impression link",
    ):
        text = " ".join((await anchor.inner_text()).split())
        if POST_IMPRESSION_PATTERN.fullmatch(text) and text not in impressions:
            impressions.append(text)
    if len(impressions) > 1:
        raise ParserDriftError("LinkedIn post detail exposed multiple visible impression counts.")
    return PostEngagementFields(
        viewer_reaction=viewer_reaction,
        reaction_count_text=reaction_count,
        comment_count_text=(
            visible_count_text(await comment_button.inner_text())
            if comment_button is not None
            else None
        ),
        repost_count_text=(
            visible_count_text(await repost_button.inner_text())
            if repost_button is not None
            else None
        ),
        impression_count_text=impressions[0] if impressions else None,
        comments_enabled=(comment_button is not None and not await comment_button.is_disabled()),
        reaction_evidence_text=reaction_evidence or None,
    )


async def comment_reference(region: Locator) -> str | None:
    for attribute in ("data-comment-urn", "data-urn", "data-id", "id"):
        value = await region.get_attribute(attribute)
        if value and (reference := comment_reference_from_value(value)):
            return reference
    return None


async def belongs_to_comment(candidate: Locator, comment_ref: str) -> bool:
    owner = candidate.locator(
        "xpath=ancestor-or-self::*["
        "@data-comment-urn or starts-with(@data-id, 'urn:li:comment:') or "
        "starts-with(@id, 'replaceableComment_urn:li:comment:')"
        "][1]"
    )
    return bool(await owner.count() and await comment_reference(owner.first) == comment_ref)


async def comment_parent_reference(region: Locator) -> str | None:
    for attribute in ("data-parent-comment-urn", "data-parent-comment"):
        value = await region.get_attribute(attribute)
        if value and (reference := comment_reference_from_value(value)):
            return reference
    parent = region.locator(
        "xpath=ancestor::*["
        "@data-comment-urn or starts-with(@data-id, 'urn:li:comment:') or "
        "starts-with(@id, 'replaceableComment_urn:li:comment:')"
        "][1]"
    )
    if await parent.count():
        return await comment_reference(parent.first)
    return None


async def comment_attachments(
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
        if not await candidate.is_visible() or not await belongs_to_comment(candidate, comment_ref):
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


async def comment_text(
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
        if not await candidate.is_visible() or not await belongs_to_comment(candidate, comment_ref):
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
        and await belongs_to_comment(option_controls.nth(index), comment_ref)
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
        if not await candidate.is_visible() or not await belongs_to_comment(candidate, comment_ref):
            continue
        text = (await candidate.inner_text()).strip()
        normalized = " ".join(text.split())
        if (
            not normalized
            or normalized.casefold() in author_metadata
            or COMMENT_TIME_PATTERN.fullmatch(normalized)
            or normalized.casefold() in POST_ACTION_LINES
            or any(pattern.fullmatch(normalized) for pattern in COUNT_PATTERNS.values())
        ):
            continue
        if text not in values:
            values.append(text)
            if visible_option_controls:
                return text
    return values[0] if len(values) == 1 else None


async def internal_comment_from_region(
    region: Locator,
    *,
    expected_post_ref: str,
) -> CommentObservation | None:
    reference = await comment_reference(region)
    if reference is None:
        return None
    native_post_ref = post_reference_from_comment_ref(reference)
    if native_post_ref != expected_post_ref:
        return None
    parent_reference = await comment_parent_reference(region)
    author = await post_author(region)
    if author is None:
        return None
    text = await comment_text(
        region,
        author=author,
        comment_ref=reference,
    )
    attachments = await comment_attachments(region, comment_ref=reference)
    visible_text = (await region.inner_text()).strip()
    for attachment in attachments:
        if attachment.visible_text not in visible_text:
            visible_text = f"{visible_text}\n{attachment.visible_text}".strip()
    if (not text and not attachments) or not visible_text:
        return None
    lines = unique_lines(visible_text)
    posted_at = next(
        (line for line in lines if COMMENT_TIME_PATTERN.fullmatch(line)),
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
        reaction_count_text=first_count(lines, "reaction"),
        reply_count_text=first_count(lines, "reply"),
        visible_text=visible_text,
    )


async def post_author_from_region(region: Locator) -> PostAuthor:
    """Parse the exact visible author header without parsing post engagement."""

    return (await post_header_fields(region)).author


async def region_for_post(page: Page, post_ref: str) -> Locator:
    """Resolve the sole visible detail region for a requested post reference.

    LinkedIn can keep an activity URL in the address bar while rendering that
    activity's single underlying share or UGC-post reference. Detail reads
    already retain both identities safely; engagement actions must use the
    same bounded alias rule or they reject the exact post they just read.
    """

    region, _ = await detail_region_for_post(page, post_ref)
    return region


def comment_regions(page: Page) -> Locator:
    """Return bounded stable comment containers from the visible discussion."""

    return page.locator("main").locator(COMMENT_REGION_SELECTOR)


async def comment_from_region(
    region: Locator,
    *,
    expected_post_ref: str,
) -> CommentObservation | None:
    """Parse one visible comment region for another narrow page object."""

    return await internal_comment_from_region(region, expected_post_ref=expected_post_ref)


async def discussion_post_reference(page: Page, requested_post_ref: str) -> str:
    """Resolve the single native post reference used by the visible discussion."""

    native_post_refs: set[str] = set()
    regions = comment_regions(page)
    for index in range(min(await regions.count(), 1_000)):
        region = regions.nth(index)
        if not await region.is_visible():
            continue
        reference = await comment_reference(region)
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
