"""Narrow native-confirmation-gated comment, reply, and reaction interactions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import Locator, Page
from pydantic import HttpUrl

from linkedin_mcp.assets import LocalAssetStore
from linkedin_mcp.browser.manager import BrowserManager
from linkedin_mcp.browser.pages.posts import (
    comment_from_region,
    comment_reference,
    comment_regions,
    discussion_post_reference,
    post_summary_from_region,
    region_for_post,
)
from linkedin_mcp.domain.models import (
    ActionDraft,
    ActionOutcome,
    ActionPageResult,
    ActionPreparationCapture,
    ActionTarget,
    CommentAttachmentType,
    CommentCreatePayload,
    CommentGifAttachment,
    CommentObservation,
    CommentPhotoAttachment,
    PostCommentPrepareInput,
    PostMentionInput,
    PostReactionPrepareInput,
    PreparedPostAsset,
    ReactionSetPayload,
    ReactionState,
)
from linkedin_mcp.errors import InvalidTargetError, ParserDriftError
from linkedin_mcp.policy import (
    canonical_post_url,
    canonical_profile_url,
    profile_slug_from_url,
)

_REACTION_LABELS = {
    ReactionState.LIKE: "Like",
    ReactionState.CELEBRATE: "Celebrate",
    ReactionState.SUPPORT: "Support",
    ReactionState.LOVE: "Love",
    ReactionState.INSIGHTFUL: "Insightful",
    ReactionState.FUNNY: "Funny",
}
_COMMENT_ATTACHMENT_SELECTOR = (
    "[data-comment-attachment], [data-test-comment-attachment], "
    '[class*="comments-comment-item__comment-image"], '
    '[class*="comments-comment-item__gif"], '
    '[class*="comments-comment-item__media"]'
)


@dataclass(frozen=True, slots=True)
class _VisibleTarget:
    region: Locator
    actor_slug: str
    actor_name: str
    content_author_name: str
    content_author_url: HttpUrl | None


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


class PostEngagementPage:
    """Personal-member comments/replies and explicit reaction-state changes."""

    def __init__(self, browser: BrowserManager, assets: LocalAssetStore) -> None:
        self._browser = browser
        self._assets = assets

    async def prepare_comment_assets(
        self,
        request: PostCommentPrepareInput,
    ) -> tuple[PreparedPostAsset, ...]:
        return await self._assets.prepare_comment(request)

    async def prepare_comment(
        self,
        request: PostCommentPrepareInput,
    ) -> ActionPreparationCapture:
        target_url = canonical_post_url(request.post_ref)
        async with self._browser.page() as page:
            await self._browser.navigate(page, target_url)
            target = await self._resolve_target(
                page,
                request.post_ref,
                request.parent_comment_ref,
            )
            composer = await self._open_comment_composer(
                page,
                target.region,
                reply=request.parent_comment_ref is not None,
            )
            await self._assert_comment_options(page, composer, request)
            return ActionPreparationCapture(
                target=self._action_target(
                    target,
                    request.post_ref,
                    request.parent_comment_ref,
                ),
                current_state=(
                    "reply_composer_ready"
                    if request.parent_comment_ref is not None
                    else "comment_composer_ready"
                ),
                source_url=HttpUrl(target_url),
                captured_text=await _visible_text(page),
                captured_at=datetime.now(UTC),
            )

    async def execute_comment(self, draft: ActionDraft) -> ActionPageResult:
        if not isinstance(draft.payload, CommentCreatePayload):
            raise InvalidTargetError("The comment action payload is invalid.")
        payload = draft.payload
        paths = await self._assets.verify_assets(payload.assets)
        target_url = canonical_post_url(payload.post_ref)
        async with self._browser.page() as page:
            await self._browser.navigate(page, target_url)
            target = await self._resolve_target(
                page,
                payload.post_ref,
                payload.parent_comment_ref,
            )
            if not self._matches_confirmed_target(draft.target, target):
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "engagement_target_changed",
                    "The active member or visible content target changed after confirmation.",
                )
            composer = await self._open_comment_composer(
                page,
                target.region,
                reply=payload.parent_comment_ref is not None,
            )
            if payload.text is not None:
                maximum = await composer.get_attribute("maxlength")
                if maximum and len(payload.text) > int(maximum):
                    return await self._result(
                        page,
                        ActionOutcome.FAILED,
                        False,
                        "comment_text_too_long",
                        "The exact confirmed comment exceeds LinkedIn's visible field limit.",
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
                paths,
            )
            await self._wait_for_existing_comment_baseline(page, target.region)
            before = await self._matching_comment_refs(
                page,
                payload,
                target.actor_slug,
            )
            final_label = (
                re.compile(r"^reply$", re.I)
                if payload.parent_comment_ref is not None
                else re.compile(r"^comment$", re.I)
            )
            final_text = "Reply" if payload.parent_comment_ref is not None else "Comment"
            submission_scope = composer.locator(
                f"xpath=ancestor::*[.//button[normalize-space(.)='{final_text}']][1]"
            )
            if await submission_scope.count() != 1:
                raise ParserDriftError(
                    "The visible comment composer has no unique submission region."
                )
            final = await _unique_visible(
                submission_scope.get_by_role("button", name=final_label).filter(
                    has_text=final_label
                ),
                "Comment or Reply submission control",
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
            for _ in range(24):
                after = await self._matching_comment_refs(
                    page,
                    payload,
                    target.actor_slug,
                )
                created = tuple(ref for ref in after if ref not in before)
                if len(created) == 1:
                    kind = "reply" if payload.parent_comment_ref else "comment"
                    return await self._result(
                        page,
                        ActionOutcome.VERIFIED,
                        True,
                        f"{kind}_published:{created[0]}",
                        f"One new exact visible {kind} matched the confirmed payload.",
                    )
                await page.wait_for_timeout(250)
            return await self._result(
                page,
                ActionOutcome.UNCERTAIN,
                None,
                "comment_outcome_unknown",
                "No single new exact visible comment matched within the verification bound.",
            )

    async def prepare_reaction(
        self,
        request: PostReactionPrepareInput,
    ) -> ActionPreparationCapture:
        target_url = canonical_post_url(request.post_ref)
        async with self._browser.page() as page:
            await self._browser.navigate(page, target_url)
            target = await self._resolve_target(page, request.post_ref, request.comment_ref)
            existing = await self._reaction_state(target.region)
            if request.desired_reaction is not ReactionState.NONE:
                await self._reaction_option(
                    page,
                    target.region,
                    request.desired_reaction,
                )
            return ActionPreparationCapture(
                target=self._action_target(target, request.post_ref, request.comment_ref),
                current_state=(
                    f"reaction_ready:{'comment' if request.comment_ref else 'post'}:"
                    f"{existing.value}"
                ),
                source_url=HttpUrl(target_url),
                captured_text=await _visible_text(page),
                captured_at=datetime.now(UTC),
                existing_reaction=existing,
            )

    async def execute_reaction(self, draft: ActionDraft) -> ActionPageResult:
        if not isinstance(draft.payload, ReactionSetPayload):
            raise InvalidTargetError("The reaction action payload is invalid.")
        payload = draft.payload
        async with self._browser.page() as page:
            await self._browser.navigate(page, canonical_post_url(payload.post_ref))
            target = await self._resolve_target(page, payload.post_ref, payload.comment_ref)
            if not self._matches_confirmed_target(draft.target, target):
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "engagement_target_changed",
                    "The active member or visible reaction target changed after confirmation.",
                )
            current = await self._reaction_state(target.region)
            if current is not payload.existing_reaction:
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "reaction_state_changed",
                    "The visible reaction changed after confirmation; prepare a new action.",
                )
            if current is payload.desired_reaction:
                return await self._result(
                    page,
                    ActionOutcome.VERIFIED,
                    False,
                    self._reaction_final_state(current),
                    "LinkedIn already shows the exact requested reaction state.",
                )
            if payload.desired_reaction is ReactionState.NONE:
                control = await self._pressed_reaction_control(target.region, current)
            else:
                control = await self._reaction_option(
                    page,
                    target.region,
                    payload.desired_reaction,
                )
            try:
                await self._browser.click_visible_control(page, control)
            except Exception:
                return await self._result(
                    page,
                    ActionOutcome.UNCERTAIN,
                    None,
                    "reaction_outcome_unknown",
                    "The reaction control was invoked, but its outcome is unknown.",
                )
            for _ in range(20):
                current = await self._reaction_state(target.region)
                if current is payload.desired_reaction:
                    return await self._result(
                        page,
                        ActionOutcome.VERIFIED,
                        True,
                        self._reaction_final_state(current),
                        "LinkedIn visibly shows the exact confirmed reaction state.",
                    )
                await page.wait_for_timeout(250)
            return await self._result(
                page,
                ActionOutcome.UNCERTAIN,
                None,
                "reaction_outcome_unknown",
                "LinkedIn exposed no bounded visible reaction postcondition.",
            )

    async def _resolve_target(
        self,
        page: Page,
        post_ref: str,
        comment_ref: str | None,
    ) -> _VisibleTarget:
        post_region = await region_for_post(page, post_ref)
        if comment_ref is None:
            region = post_region
            summary = await post_summary_from_region(post_region)
            if summary is None:
                raise ParserDriftError("The exact post target has no visible author identity.")
            author_name = summary.author.name
            author_url = summary.author.author_url
        else:
            embedded_post_ref = self._post_ref_from_comment_ref(comment_ref)
            region = await self._reveal_comment(
                page,
                post_region,
                comment_ref,
            )
            native_post_ref = await discussion_post_reference(page, post_ref)
            if native_post_ref != embedded_post_ref:
                raise InvalidTargetError(
                    "The exact comment does not belong to the visible LinkedIn discussion."
                )
            comment = await comment_from_region(
                region,
                expected_post_ref=embedded_post_ref,
            )
            if comment is None:
                raise ParserDriftError("The exact comment target has no stable visible identity.")
            author_name = comment.author.name
            author_url = comment.author.author_url
        actor_slug, actor_name = await self._active_actor(page)
        return _VisibleTarget(
            region=region,
            actor_slug=actor_slug,
            actor_name=actor_name,
            content_author_name=author_name,
            content_author_url=author_url,
        )

    @staticmethod
    def _post_ref_from_comment_ref(comment_ref: str) -> str:
        _, kind, post_id, _ = comment_ref.split(":")
        return f"{kind}:{post_id}"

    @staticmethod
    async def _comment_region(page: Page, comment_ref: str) -> Locator | None:
        candidates = comment_regions(page)
        matches: list[Locator] = []
        for index in range(min(await candidates.count(), 1_000)):
            candidate = candidates.nth(index)
            if await candidate.is_visible() and await comment_reference(candidate) == comment_ref:
                matches.append(candidate)
        if len(matches) > 1:
            raise ParserDriftError("Multiple visible comments expose the exact same reference.")
        return matches[0] if matches else None

    async def _reveal_comment(
        self,
        page: Page,
        post_region: Locator,
        comment_ref: str,
    ) -> Locator:
        match = await self._comment_region(page, comment_ref)
        if match is not None:
            return match
        comment_control = post_region.get_by_role(
            "button",
            name=re.compile(r"^(?:[0-9,]+\s+)?comments?$", re.I),
        )
        visible_comment_controls = [
            comment_control.nth(index)
            for index in range(await comment_control.count())
            if await comment_control.nth(index).is_visible()
        ]
        if len(visible_comment_controls) == 1:
            await self._browser.click_visible_control(page, visible_comment_controls[0])
            await page.wait_for_timeout(500)
        elif len(visible_comment_controls) > 1:
            raise ParserDriftError("The exact post has no unique visible Comment control.")
        expansion_name = re.compile(
            r"^(?:load|show|view|see).*(?:comments?|repl(?:y|ies))$",
            re.I,
        )
        quiet_rounds = 0
        for _ in range(25):
            match = await self._comment_region(page, comment_ref)
            if match is not None:
                return match
            controls = post_region.get_by_role("button", name=expansion_name).or_(
                page.get_by_role("button", name=expansion_name)
            )
            visible: list[Locator] = []
            for index in range(min(await controls.count(), 100)):
                candidate = controls.nth(index)
                if await candidate.is_visible():
                    visible.append(candidate)
            if visible:
                await self._browser.click_visible_control(page, visible[0])
                quiet_rounds = 0
            else:
                quiet_rounds += 1
                if quiet_rounds >= 8:
                    break
            await page.wait_for_timeout(500)
        raise InvalidTargetError("No unique visible comment matches the exact reference.")

    @staticmethod
    async def _active_actor(page: Page) -> tuple[str, str]:
        explicit_candidates = page.locator(
            "a[data-active-member][href*='/in/'], "
            "[data-active-member] a[href*='/in/'], "
            "nav a[aria-label*='profile' i][href*='/in/']"
        )
        values: list[tuple[str, str]] = []
        for index in range(min(await explicit_candidates.count(), 20)):
            candidate = explicit_candidates.nth(index)
            if not await candidate.is_visible():
                continue
            href = await candidate.get_attribute("href")
            slug = profile_slug_from_url(urljoin("https://www.linkedin.com", href or ""))
            name = (await candidate.inner_text()).strip().splitlines()
            if slug and name and name[0].strip():
                values.append((slug, name[0].strip()))
        unique = list(dict.fromkeys(values))
        if len(unique) == 1:
            return unique[0]
        if unique:
            raise ParserDriftError("LinkedIn has no unique visible active member identity.")

        # The current post-detail layout exposes the signed-in member's profile
        # card in a visible complementary rail while the top-navigation "Me"
        # control is a button without a profile URL. Bind only when every
        # visible profile link in that rail resolves to one stable member slug.
        rail_candidates = page.locator("aside a[href*='/in/']")
        rail_slugs: set[str] = set()
        named_candidates: list[tuple[int, str, str]] = []
        for index in range(min(await rail_candidates.count(), 50)):
            candidate = rail_candidates.nth(index)
            if not await candidate.is_visible():
                continue
            href = await candidate.get_attribute("href")
            slug = profile_slug_from_url(urljoin("https://www.linkedin.com", href or ""))
            if slug is None:
                continue
            rail_slugs.add(slug)
            text = (await candidate.inner_text()).strip()
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if lines:
                named_candidates.append((len(text), slug, lines[0]))
        if len(rail_slugs) != 1:
            raise ParserDriftError("LinkedIn has no unique visible active member identity.")
        actor_slug = next(iter(rail_slugs))
        names = [candidate for candidate in named_candidates if candidate[1] == actor_slug]
        if not names:
            raise ParserDriftError("LinkedIn has no visible active member display name.")
        _, _, actor_name = max(names, key=lambda candidate: candidate[0])
        return actor_slug, actor_name

    @staticmethod
    def _action_target(
        target: _VisibleTarget,
        post_ref: str,
        comment_ref: str | None,
    ) -> ActionTarget:
        actor_url = HttpUrl(canonical_profile_url(target.actor_slug))
        return ActionTarget(
            profile_slug=target.actor_slug,
            profile_url=actor_url,
            display_name=target.actor_name,
            actor_profile_slug=target.actor_slug,
            actor_profile_url=actor_url,
            actor_display_name=target.actor_name,
            post_ref=post_ref,
            post_url=HttpUrl(canonical_post_url(post_ref)),
            comment_ref=comment_ref,
            content_author_name=target.content_author_name,
            content_author_url=target.content_author_url,
        )

    @staticmethod
    def _matches_confirmed_target(
        confirmed: ActionTarget,
        current: _VisibleTarget,
    ) -> bool:
        return (
            (confirmed.actor_profile_slug or confirmed.profile_slug) == current.actor_slug
            and (confirmed.actor_display_name or confirmed.display_name).casefold()
            == current.actor_name.casefold()
            and confirmed.content_author_name is not None
            and confirmed.content_author_name.casefold() == current.content_author_name.casefold()
            and (
                confirmed.content_author_url is None
                or (
                    current.content_author_url is not None
                    and str(confirmed.content_author_url) == str(current.content_author_url)
                )
            )
        )

    async def _open_comment_composer(
        self,
        page: Page,
        region: Locator,
        *,
        reply: bool,
    ) -> Locator:
        scoped_label = (
            re.compile(r"add a reply|write a reply|text editor for creating (?:a )?reply", re.I)
            if reply
            else re.compile(
                r"add a comment|leave your thoughts|text editor for creating (?:a )?comment",
                re.I,
            )
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
                    name=(
                        re.compile(r"^reply$", re.I) if reply else re.compile(r"^comment$", re.I)
                    ),
                ),
                "Reply or Comment opener",
            )
            await self._browser.click_visible_control(page, action)
            for _ in range(20):
                composer = region.get_by_role("textbox", name=scoped_label)
                visible = [
                    composer.nth(index)
                    for index in range(await composer.count())
                    if await composer.nth(index).is_visible()
                ]
                if not visible and reply:
                    current_reply = page.get_by_role(
                        "textbox",
                        name=re.compile(
                            r"text editor for creating (?:a )?(?:comment|reply)",
                            re.I,
                        ),
                    ).and_(page.locator(":focus"))
                    visible = [
                        current_reply.nth(index)
                        for index in range(await current_reply.count())
                        if await current_reply.nth(index).is_visible()
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
        request: PostCommentPrepareInput,
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
        paths: dict[str, Path],
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
                await chooser.set_files(str(paths[payload.attachment.asset_ref]))
            except Exception as error:
                raise ParserDriftError(
                    "The current comment Share photo control exposed no file chooser."
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
                and comment.parent_comment_ref == payload.parent_comment_ref
                and PostEngagementPage._comment_matches_payload(comment, payload)
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
        if payload.text is not None and comment.text != payload.text:
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

    async def _reaction_option(
        self,
        page: Page,
        region: Locator,
        desired: ReactionState,
    ) -> Locator:
        if desired is ReactionState.NONE:
            raise InvalidTargetError("Removal has no reaction-menu option.")
        base = region.locator(
            "[data-reaction-control], button[aria-label^='Reaction button state:' i]"
        )
        if await base.count() == 0:
            base = region.get_by_role(
                "button",
                name=re.compile(
                    r"^(?:like|react|remove (?:like|reaction)|"
                    r"reaction button state: .+)$",
                    re.I,
                ),
            )
        control = await _unique_visible(base, "reaction control")
        await control.hover()
        option_name = re.compile(rf"^{_REACTION_LABELS[desired]}$", re.I)
        explicit = region.get_by_role(
            "button",
            name=option_name,
        ).and_(region.locator("[data-reaction-option]"))
        explicit_visible = [
            explicit.nth(index)
            for index in range(await explicit.count())
            if await explicit.nth(index).is_visible()
        ]
        if len(explicit_visible) == 1:
            return explicit_visible[0]
        if explicit_visible:
            raise ParserDriftError(
                f"LinkedIn has no unique visible {desired.value} reaction option."
            )
        # The current UI portals the six reaction buttons outside the post or
        # comment region after hover. Their exact accessible names remain the
        # binding, and only one visible option is accepted.
        return await _unique_visible(
            page.get_by_role("button", name=option_name),
            f"{desired.value} reaction option",
        )

    @staticmethod
    async def _reaction_state(region: Locator) -> ReactionState:
        explicit = region.locator("[data-current-reaction]")
        for index in range(await explicit.count()):
            item = explicit.nth(index)
            if not await item.is_visible():
                continue
            value = (await item.get_attribute("data-current-reaction") or "").casefold()
            if value in {state.value for state in ReactionState}:
                return ReactionState(value)
        current_controls = region.locator("button[aria-label^='Reaction button state:' i]")
        for index in range(await current_controls.count()):
            item = current_controls.nth(index)
            if not await item.is_visible():
                continue
            label = (await item.get_attribute("aria-label") or "").strip().casefold()
            _, _, value = label.partition(":")
            normalized = value.strip()
            if normalized == "no reaction":
                return ReactionState.NONE
            if normalized in {
                state.value for state in ReactionState if state is not ReactionState.NONE
            }:
                return ReactionState(normalized)
        pressed = region.locator(
            "button[aria-pressed='true'][data-reaction-control], "
            "button[aria-pressed='true'][data-current-reaction]"
        )
        for index in range(await pressed.count()):
            item = pressed.nth(index)
            if not await item.is_visible():
                continue
            label = (
                await item.get_attribute("data-current-reaction")
                or await item.get_attribute("aria-label")
                or await item.inner_text()
            ).casefold()
            for state in ReactionState:
                if state is not ReactionState.NONE and state.value in label:
                    return state
        return ReactionState.NONE

    @staticmethod
    async def _pressed_reaction_control(
        region: Locator,
        current: ReactionState,
    ) -> Locator:
        if current is ReactionState.NONE:
            raise InvalidTargetError("There is no current reaction to remove.")
        control = region.locator(
            "button[data-reaction-control][aria-pressed='true'], "
            "button[data-current-reaction][aria-pressed='true']"
        )
        visible = [
            control.nth(index)
            for index in range(await control.count())
            if await control.nth(index).is_visible()
        ]
        if len(visible) == 1:
            return visible[0]
        if visible:
            raise ParserDriftError(
                "LinkedIn has no unique visible current pressed reaction control."
            )
        current_controls = region.locator("button[aria-label^='Reaction button state:' i]")
        current_matches: list[Locator] = []
        for index in range(await current_controls.count()):
            candidate = current_controls.nth(index)
            if not await candidate.is_visible():
                continue
            label = (await candidate.get_attribute("aria-label") or "").strip().casefold()
            if label.partition(":")[2].strip() == current.value:
                current_matches.append(candidate)
        if len(current_matches) != 1:
            raise ParserDriftError("LinkedIn has no unique visible current reaction control.")
        return current_matches[0]

    @staticmethod
    def _reaction_final_state(value: ReactionState) -> str:
        return "reaction_removed" if value is ReactionState.NONE else f"reaction_set:{value.value}"

    @staticmethod
    async def _result(
        page: Page,
        outcome: ActionOutcome,
        performed: bool | None,
        final_state: str,
        detail: str,
    ) -> ActionPageResult:
        return ActionPageResult(
            outcome=outcome,
            performed=performed,
            final_state=final_state,
            detail=detail,
            source_url=HttpUrl(page.url),
            captured_text=await _visible_text(page),
            captured_at=datetime.now(UTC),
        )
