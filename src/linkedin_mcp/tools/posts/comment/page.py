"""Visible LinkedIn page implementation for `linkedin_mcp.tools.posts.comment.page`."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from playwright.async_api import Locator, Page
from pydantic import HttpUrl

from linkedin_mcp.errors import InvalidTargetError, ParserDriftError
from linkedin_mcp.tools._shared.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutcome,
    ActionPageResult,
    CommentCreatePayload,
)
from linkedin_mcp.tools._shared.urls import (
    canonical_post_url,
)
from linkedin_mcp.tools.posts.comment.models.comment_gif_attachment import CommentGifAttachment
from linkedin_mcp.tools.posts.comment.models.comment_photo_attachment import CommentPhotoAttachment
from linkedin_mcp.tools.posts.comment.models.post_comment_input import PostCommentInput
from linkedin_mcp.tools.posts.comments.list.models.comment_attachment_type import (
    CommentAttachmentType,
)
from linkedin_mcp.tools.posts.comments.list.models.comment_observation import CommentObservation
from linkedin_mcp.tools.posts.engagement_surface import PostEngagementSurface
from linkedin_mcp.tools.posts.models.post_mention_input import PostMentionInput
from linkedin_mcp.tools.posts.surface import (
    comment_from_region,
    comment_regions,
    discussion_post_reference,
)

_COMMENT_ATTACHMENT_SELECTOR = (
    "[data-comment-attachment], [data-test-comment-attachment], "
    '[class*="comments-comment-item__comment-image"], '
    '[class*="comments-comment-item__gif"], '
    '[class*="comments-comment-item__media"]'
)

_COMMENT_VERIFICATION_ATTEMPTS = 24

_COMMENT_VERIFICATION_DELAY_MS = 250

_COMMENT_EXPANSION_SUFFIX = re.compile(
    r"(?:\r?\n)[ \t]*(?:\N{HORIZONTAL ELLIPSIS}|\.\.\.)[ \t]*more[ \t]*$",
    re.IGNORECASE,
)


async def _visible_text(page: Page) -> str:
    for locator in (page.locator("main"), page.locator("body")):
        if await locator.count() == 0:
            continue
        value = (await locator.first.inner_text()).strip()
        if value:
            attachments = page.locator(_COMMENT_ATTACHMENT_SELECTOR)
            accessible: list[str] = []
            for index in range(min(await attachments.count(), 100)):
                attachment = attachments.nth(index)
                if not await attachment.is_visible():
                    continue
                media = attachment.locator("img, video, a").first
                for candidate in (
                    await attachment.get_attribute("aria-label"),
                    (await media.get_attribute("aria-label") if await media.count() else None),
                    await media.get_attribute("alt") if await media.count() else None,
                ):
                    if candidate and candidate not in value and candidate not in accessible:
                        accessible.append(candidate)
            if accessible:
                value = f"{value}\n\n--- accessible comment attachment evidence ---\n" + "\n".join(
                    accessible
                )
            return value
    raise ParserDriftError("LinkedIn returned no visible engagement text.")


async def _unique_visible(locator: Locator, description: str) -> Locator:
    values: list[Locator] = []
    for index in range(await locator.count()):
        candidate = locator.nth(index)
        if await candidate.is_visible():
            values.append(candidate)
    if len(values) != 1:
        raise ParserDriftError(f"LinkedIn has no unique visible {description}.")
    return values[0]


def _visible_comment_text_matches(actual: str, expected: str) -> bool:
    """Ignore only LinkedIn's trailing visible expansion affordance."""

    return actual == expected or _COMMENT_EXPANSION_SUFFIX.sub("", actual) == expected


class PostCommentPage(PostEngagementSurface):
    async def inspect_comment(
        self,
        request: PostCommentInput,
    ) -> ActionInspection:
        target_url = canonical_post_url(request.post_ref)
        async with self._browser.page() as page:
            await self._browser.navigate(page, target_url)
            target = await self._resolve_target(page, request.post_ref)
            composer = await self._open_comment_composer(page, target.region)
            await self._assert_comment_options(page, composer, request)
            return ActionInspection(
                target=self._action_target(target, request.post_ref),
                current_state="comment_composer_ready",
                source_url=HttpUrl(target_url),
                captured_text=await _visible_text(page),
                captured_at=datetime.now(UTC),
            )

    async def perform_comment(self, command: ActionCommand) -> ActionPageResult:
        if not isinstance(command.payload, CommentCreatePayload):
            raise InvalidTargetError("The comment action payload is invalid.")
        payload = command.payload
        target_url = canonical_post_url(payload.post_ref)
        async with self._browser.page() as page:
            await self._browser.navigate(page, target_url)
            target = await self._resolve_target(page, payload.post_ref)
            if not self._matches_inspected_target(command.target, target):
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "engagement_target_changed",
                    "The active member or visible content target changed after inspection.",
                )
            composer = await self._open_comment_composer(page, target.region)
            if payload.text is not None:
                maximum = await composer.get_attribute("maxlength")
                if maximum and len(payload.text) > int(maximum):
                    return await self._result(
                        page,
                        ActionOutcome.FAILED,
                        False,
                        "comment_text_too_long",
                        "The exact requested comment exceeds LinkedIn's visible field limit.",
                    )
                await self._fill_text_with_mentions(
                    page,
                    composer,
                    payload.text,
                    payload.mentions,
                )
            await self._add_comment_attachment(
                page,
                composer,
                payload,
            )
            await self._wait_for_existing_comment_baseline(page, target.region)
            before = await self._matching_comment_refs(
                page,
                payload,
                target.actor_slug,
            )
            submission_scope = composer.locator(
                "xpath=ancestor::*[.//button[normalize-space(.)='Comment']][1]"
            )
            if await submission_scope.count() != 1:
                raise ParserDriftError(
                    "The visible comment composer has no unique submission region."
                )
            final = await _unique_visible(
                submission_scope.get_by_role("button", name=re.compile(r"^comment$", re.I)).filter(
                    has_text=re.compile(r"^comment$", re.I)
                ),
                "Comment submission control",
            )
            try:
                await self._browser.click_visible_control(page, final)
            except Exception:
                return await self._result(
                    page,
                    ActionOutcome.UNCERTAIN,
                    None,
                    "comment_outcome_unknown",
                    "The final comment control was invoked, but its outcome is unknown.",
                )
            for _ in range(_COMMENT_VERIFICATION_ATTEMPTS):
                after = await self._matching_comment_refs(
                    page,
                    payload,
                    target.actor_slug,
                )
                created = tuple(ref for ref in after if ref not in before)
                if len(created) == 1:
                    return await self._result(
                        page,
                        ActionOutcome.VERIFIED,
                        True,
                        f"comment_published:{created[0]}",
                        "One new exact visible comment matched the requested payload.",
                    )
                await page.wait_for_timeout(_COMMENT_VERIFICATION_DELAY_MS)
            return await self._result(
                page,
                ActionOutcome.UNCERTAIN,
                None,
                "comment_outcome_unknown",
                (
                    "No single new stable comment reference matched the exact requested "
                    "payload within the verification bound."
                ),
            )

    async def _open_comment_composer(
        self,
        page: Page,
        region: Locator,
    ) -> Locator:
        scoped_label = re.compile(
            r"add a comment|leave your thoughts|"
            r"text editor for creating (?:(?:a )?comment|content)",
            re.I,
        )
        composer = region.get_by_role("textbox", name=scoped_label)
        visible = [
            composer.nth(index)
            for index in range(await composer.count())
            if await composer.nth(index).is_visible()
        ]
        if not visible:
            action = await _unique_visible(
                region.get_by_role(
                    "button",
                    name=re.compile(r"^comment$", re.I),
                ),
                "Comment opener",
            )
            await self._browser.click_visible_control(page, action)
            for _ in range(20):
                composer = region.get_by_role("textbox", name=scoped_label)
                visible = [
                    composer.nth(index)
                    for index in range(await composer.count())
                    if await composer.nth(index).is_visible()
                ]
                if visible:
                    break
                await page.wait_for_timeout(250)
        if len(visible) != 1:
            raise InvalidTargetError("The target has no unique visible comment composer.")
        return visible[0]

    async def _assert_comment_options(
        self,
        page: Page,
        composer: Locator,
        request: PostCommentInput,
    ) -> None:
        region = await self._comment_composer_region(composer)
        if isinstance(request.attachment, CommentPhotoAttachment):
            await _unique_visible(
                region.get_by_role(
                    "button",
                    name=re.compile(r"^share photo$", re.I),
                ),
                "comment Share photo control",
            )
        elif isinstance(request.attachment, CommentGifAttachment):
            gif = await _unique_visible(
                region.get_by_role(
                    "button",
                    name=re.compile(r"^open gif picker$", re.I),
                ),
                "comment Open GIF picker control",
            )
            await self._browser.click_visible_control(page, gif)
            await self._resolve_gif(page, request.attachment, choose=False)

    async def _add_comment_attachment(
        self,
        page: Page,
        composer: Locator,
        payload: CommentCreatePayload,
    ) -> None:
        region = await self._comment_composer_region(composer)
        if isinstance(payload.attachment, CommentPhotoAttachment):
            photo = await _unique_visible(
                region.get_by_role(
                    "button",
                    name=re.compile(r"^share photo$", re.I),
                ),
                "comment Share photo control",
            )
            try:
                async with page.expect_file_chooser(timeout=3_000) as chooser_info:
                    await self._browser.click_visible_control(page, photo)
                chooser = await chooser_info.value
                await chooser.set_files(payload.attachment.asset_ref)
            except Exception as error:
                raise ParserDriftError(
                    "The client-selected path could not be uploaded through the current "
                    "comment Share photo control."
                ) from error
        elif isinstance(payload.attachment, CommentGifAttachment):
            gif = await _unique_visible(
                region.get_by_role(
                    "button",
                    name=re.compile(r"^open gif picker$", re.I),
                ),
                "comment Open GIF picker control",
            )
            await self._browser.click_visible_control(page, gif)
            await self._resolve_gif(page, payload.attachment, choose=True)

    async def _resolve_gif(
        self,
        page: Page,
        attachment: CommentGifAttachment,
        *,
        choose: bool,
    ) -> Locator:
        search = await _unique_visible(
            page.get_by_role(
                "textbox",
                name=re.compile(r"^search for gifs$", re.I),
            ).or_(
                page.get_by_placeholder(
                    re.compile(r"^search klipy$", re.I),
                )
            ),
            "GIF search field",
        )
        picker = search.locator(
            "xpath=ancestor::*[@role='dialog' or @role='listbox' or @data-gif-picker][1]"
        )
        if await picker.count() != 1 or not await picker.is_visible():
            raise ParserDriftError("LinkedIn has no unique visible GIF picker.")
        await search.fill(attachment.search_query)
        image = await _unique_visible(
            picker.get_by_alt_text(
                re.compile(
                    rf"^{re.escape(attachment.visible_result_label)}$",
                    re.I,
                )
            ),
            "exact GIF result",
        )
        result = image.locator("xpath=ancestor::button[1]")
        if await result.count() != 1 or not await result.is_visible():
            raise ParserDriftError("The exact visible GIF result is not an operable button.")
        if choose:
            await self._browser.click_visible_control(page, result)
        return result

    @staticmethod
    async def _comment_composer_region(composer: Locator) -> Locator:
        region = composer.locator("xpath=ancestor::*[self::form or @data-comment-composer][1]")
        if await region.count() == 1 and await region.is_visible():
            return region
        current = composer.locator(
            "xpath=ancestor::*[.//button[@aria-label='Show Emoji Picker' "
            "or @aria-label='Open GIF picker' or @aria-label='Share photo']][1]"
        )
        if await current.count() == 1 and await current.is_visible():
            return current
        parent = composer.locator("xpath=..")
        if await parent.count() == 1 and await parent.is_visible():
            return parent
        raise ParserDriftError("The visible comment editor has no unique composer region.")

    async def _fill_text_with_mentions(
        self,
        page: Page,
        textbox: Locator,
        text: str,
        mentions: tuple[PostMentionInput, ...],
    ) -> None:
        if not mentions:
            await textbox.fill(text)
            return
        await textbox.fill("")
        position = 0
        for mention in sorted(mentions, key=lambda item: text.index(item.token)):
            start = text.index(mention.token)
            await textbox.press_sequentially(text[position:start])
            await textbox.press_sequentially(mention.token)
            selector = (
                f'a[href*="/in/{mention.profile_slug}/"]'
                if mention.profile_slug is not None
                else f'a[href*="/company/{mention.company_slug}/"]'
            )
            suggestion = page.locator("[role='listbox'], [role='menu']").locator(selector)
            await self._browser.click_visible_control(
                page,
                await _unique_visible(suggestion, "exact comment @mention suggestion"),
            )
            position = start + len(mention.token)
        await textbox.press_sequentially(text[position:])

    @staticmethod
    async def _matching_comment_refs(
        page: Page,
        payload: CommentCreatePayload,
        actor_slug: str,
    ) -> tuple[str, ...]:
        matches: list[str] = []
        native_post_ref = await discussion_post_reference(page, payload.post_ref)
        regions = comment_regions(page)
        for index in range(min(await regions.count(), 1_000)):
            region = regions.nth(index)
            if not await region.is_visible():
                continue
            comment = await comment_from_region(
                region,
                expected_post_ref=native_post_ref,
            )
            if (
                comment is not None
                and comment.author.profile_slug == actor_slug
                and comment.parent_comment_ref is None
                and PostCommentPage._comment_matches_payload(comment, payload)
                and comment.comment_ref not in matches
            ):
                matches.append(comment.comment_ref)
        return tuple(matches)

    @staticmethod
    async def _wait_for_existing_comment_baseline(
        page: Page,
        region: Locator,
    ) -> None:
        controls = region.get_by_role(
            "button",
            name=re.compile(r"^comment$", re.I),
        )
        visible_count_control = False
        for index in range(min(await controls.count(), 20)):
            control = controls.nth(index)
            if not await control.is_visible():
                continue
            text = " ".join((await control.inner_text()).split())
            count = re.search(r"\b([1-9][\d,]*)\b", text)
            if count is not None:
                visible_count_control = True
                break
        if not visible_count_control:
            return
        for _ in range(20):
            regions = comment_regions(page)
            if any(
                [
                    await regions.nth(index).is_visible()
                    for index in range(min(await regions.count(), 1_000))
                ]
            ):
                return
            await page.wait_for_timeout(250)
        raise ParserDriftError(
            "LinkedIn shows existing comments but did not expose a stable visible baseline."
        )

    @staticmethod
    def _comment_matches_payload(
        comment: CommentObservation,
        payload: CommentCreatePayload,
    ) -> bool:
        if payload.text is not None and (
            comment.text is None or not _visible_comment_text_matches(comment.text, payload.text)
        ):
            return False
        if payload.attachment is None:
            return not comment.attachments
        if isinstance(payload.attachment, CommentPhotoAttachment):
            return any(
                attachment.attachment_type is CommentAttachmentType.PHOTO
                for attachment in comment.attachments
            )
        expected = payload.attachment.visible_result_label.casefold()
        return any(
            attachment.attachment_type is CommentAttachmentType.GIF
            and expected
            in {
                value.casefold()
                for value in (
                    attachment.accessible_label,
                    attachment.visible_text,
                )
                if value is not None
            }
            for attachment in comment.attachments
        )
