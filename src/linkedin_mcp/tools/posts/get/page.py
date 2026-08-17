"""Visible LinkedIn page implementation for `linkedin_mcp.tools.posts.get.page`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import HttpUrl

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools._shared.browser import BrowserManager
from linkedin_mcp.tools._shared.urls import (
    canonical_post_url,
)
from linkedin_mcp.tools.posts.get.models.post_detail_coverage import PostDetailCoverage
from linkedin_mcp.tools.posts.get.models.post_evidence import PostEvidence
from linkedin_mcp.tools.posts.get.models.post_get_input import PostGetInput
from linkedin_mcp.tools.posts.get.models.post_observation import PostObservation
from linkedin_mcp.tools.posts.get.models.post_reshared_content import PostResharedContent
from linkedin_mcp.tools.posts.search.models.post_content_type import PostContentType
from linkedin_mcp.tools.posts.surface import (
    POST_MENU_PATTERN,
    PostContentFields,
    PostEngagementFields,
    PostHeaderFields,
    bounded_visible_locators,
    detail_region_for_post,
    post_body_boxes,
    post_body_links,
    post_content_fields,
    post_engagement,
    post_header_fields,
    post_reference_for_region,
    visible_accessible_values,
)


@dataclass(frozen=True, slots=True)
class _ParsedPostDetail:
    source_url: HttpUrl
    displayed_post_ref: str
    header: PostHeaderFields
    text: str | None
    content: PostContentFields
    engagement: PostEngagementFields
    captured_text: str
    text_expanded: bool
    is_repost_wrapper: bool
    original_post_ref: str | None


async def _expand_exact_post_body(
    browser: BrowserManager,
    page: Page,
    body: Locator | None,
) -> bool:
    if body is None:
        return True
    scope = body.locator("..")
    buttons = scope.locator('[data-testid="expandable-text-button"]')
    visible = await bounded_visible_locators(
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
    remaining = await bounded_visible_locators(
        scope.locator('[data-testid="expandable-text-button"]'),
        limit=5,
        description="remaining text-expansion control",
    )
    if remaining:
        raise ParserDriftError("LinkedIn post text remained visibly truncated.")
    return True


async def _embedded_post_region(body: Locator) -> Locator:
    candidate = body
    for _ in range(8):
        candidate = candidate.locator("..")
        identities = candidate.locator('a[href*="/in/"], a[href*="/company/"]')
        menus = candidate.get_by_role("button", name=POST_MENU_PATTERN)
        body_count = await candidate.locator('[data-testid="expandable-text-box"]').count()
        if await identities.count() and not await menus.count() and body_count == 1:
            return candidate
    raise ParserDriftError("LinkedIn repost has no bounded visible original-post region.")


async def _captured_post_text(region: Locator) -> str:
    visible_text = (await region.inner_text()).strip()
    if not visible_text:
        raise ParserDriftError("LinkedIn post detail returned no visible text.")
    accessible = [
        *await visible_accessible_values(
            region,
            "[aria-label]",
            "aria-label",
        ),
        *await visible_accessible_values(
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
    header: PostHeaderFields,
    text: str | None,
    content: PostContentFields,
    engagement: PostEngagementFields | None,
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
    original_post_ref = await post_reference_for_region(embedded_region)
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
    region, displayed_post_ref = await detail_region_for_post(page, requested_post_ref)
    body_boxes = await post_body_boxes(region)
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
    region, stable_displayed_post_ref = await detail_region_for_post(
        page,
        requested_post_ref,
    )
    if stable_displayed_post_ref != displayed_post_ref:
        raise ParserDriftError("LinkedIn post identity changed while expanding visible text.")
    body_boxes = await post_body_boxes(region)
    if (len(body_boxes) == 2) != is_repost_wrapper:
        raise ParserDriftError("LinkedIn post wrapper changed while expanding visible text.")
    top_body = body_boxes[0] if body_boxes else None
    header = await post_header_fields(region)
    text = (await top_body.inner_text()).strip() if top_body is not None else None
    if text == "":
        text = None
    if is_repost_wrapper:
        links, hashtags, mentions = await post_body_links(top_body)
        content = PostContentFields(
            content_type=PostContentType.REPOST,
            attachments=(),
            links=links,
            hashtags=hashtags,
            mentions=mentions,
            poll=None,
        )
    else:
        content = await post_content_fields(region, top_body)
    return _ParsedPostDetail(
        source_url=source_url,
        displayed_post_ref=displayed_post_ref,
        header=header,
        text=text,
        content=content,
        engagement=await post_engagement(region),
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
