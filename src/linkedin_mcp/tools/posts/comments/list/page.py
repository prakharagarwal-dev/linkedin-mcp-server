"""Visible LinkedIn page implementation for `linkedin_mcp.tools.posts.comments.list.page`."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools._shared.browser import BrowserManager
from linkedin_mcp.tools._shared.collections import (
    visible_locator_signature,
    wait_for_collection_change,
)
from linkedin_mcp.tools._shared.urls import (
    canonical_post_url,
    post_reference_from_comment_ref,
)
from linkedin_mcp.tools.posts.comments.list.models.comment_observation import CommentObservation
from linkedin_mcp.tools.posts.comments.list.models.comment_sort import CommentSort
from linkedin_mcp.tools.posts.comments.list.models.comment_thread import CommentThread
from linkedin_mcp.tools.posts.comments.list.models.post_comments_coverage import (
    PostCommentsCoverage,
)
from linkedin_mcp.tools.posts.comments.list.models.post_comments_list_input import (
    PostCommentsListInput,
)
from linkedin_mcp.tools.posts.surface import (
    COLLECTION_POLL_DELAY_MS,
    COMMENT_REGION_SELECTOR,
    comment_reference,
    comment_regions,
    detail_region_for_post,
    discussion_post_reference,
    internal_comment_from_region,
    prepare_visible_content,
)

_COLLECTION_POLL_ATTEMPTS = 8


async def _visible_comment_signature(page: Page) -> tuple[str, ...]:
    return await visible_locator_signature(
        page.locator(COMMENT_REGION_SELECTOR),
        identity_attributes=("data-comment-urn", "id", "data-urn"),
        limit=1_000,
    )


async def _expand_visible_content(page: Page) -> None:
    """Preserve bounded best-effort expansion for the discussion collection."""

    await prepare_visible_content(page)
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


def _bind_flattened_comment_parents(
    comments: list[tuple[CommentObservation, float | None]],
) -> list[CommentObservation]:
    """Bind visually indented flat replies to their nearest preceding root."""

    positions = [position for _, position in comments if position is not None]
    if not positions:
        return [comment for comment, _ in comments]
    root_x = min(positions)
    indentation_threshold = root_x + 12
    current_root: str | None = None
    bound: list[CommentObservation] = []
    for comment, position in comments:
        if comment.parent_comment_ref is not None:
            bound.append(comment)
            continue
        if position is None or position <= indentation_threshold:
            current_root = comment.comment_ref
            bound.append(comment)
            continue
        if current_root is None:
            raise ParserDriftError(
                "LinkedIn discussion began with an indented reply whose root is not visible."
            )
        bound.append(comment.model_copy(update={"parent_comment_ref": current_root}))
    return bound


async def _visible_comment_regions(page: Page) -> tuple[Locator, ...]:
    regions = comment_regions(page)
    visible: list[Locator] = []
    for index in range(min(await regions.count(), 1_000)):
        region = regions.nth(index)
        if await region.is_visible():
            visible.append(region)
    return tuple(visible)


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
            post_region, displayed_post_ref = await detail_region_for_post(
                page,
                request.post_ref,
            )
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
                    delay_ms=COLLECTION_POLL_DELAY_MS,
                )
            regions = comment_regions(page)
            native_post_ref = await discussion_post_reference(page, displayed_post_ref)
            comments_with_layout: list[tuple[CommentObservation, float | None]] = []
            comment_refs: set[str] = set()
            for index in range(min(await regions.count(), 1_000)):
                region = regions.nth(index)
                if not await region.is_visible():
                    continue
                reference = await comment_reference(region)
                if (
                    reference is None
                    or post_reference_from_comment_ref(reference) != native_post_ref
                ):
                    continue
                comment = await internal_comment_from_region(
                    region,
                    expected_post_ref=native_post_ref,
                )
                if comment is None:
                    raise ParserDriftError(
                        "A stable visible LinkedIn comment has no unambiguous content."
                    )
                if comment.comment_ref not in comment_refs:
                    comments_with_layout.append((comment, await _comment_identity_x(region)))
                    comment_refs.add(comment.comment_ref)
            comments = _bind_flattened_comment_parents(comments_with_layout)
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
