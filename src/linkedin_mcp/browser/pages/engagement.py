"""Narrow direct comment and reaction interactions through visible LinkedIn UI."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from pydantic import HttpUrl

from linkedin_mcp.assets import LocalAssetStore
from linkedin_mcp.browser.manager import BrowserManager
from linkedin_mcp.browser.pages.posts import (
    comment_from_region,
    comment_regions,
    discussion_post_reference,
    post_author_from_region,
    region_for_post,
)
from linkedin_mcp.domain.models import (
    ActionCommand,
    ActionInspection,
    ActionOutcome,
    ActionPageResult,
    ActionTarget,
    CommentAttachmentType,
    CommentCreatePayload,
    CommentGifAttachment,
    CommentObservation,
    CommentPhotoAttachment,
    PostCommentInput,
    PostMentionInput,
    PostReactionInput,
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
_REACTION_STATE_SELECTOR = "[aria-label^='Reaction button state:' i]"
_REACTION_CONTROL_SELECTOR = (
    "[data-reaction-control], "
    "button[aria-label^='Reaction button state:' i], "
    "button[aria-label^='React ' i][aria-pressed], "
    "[role='button'][tabindex='0']:has("
    "[aria-label^='Reaction button state:' i])"
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


def _visible_comment_text_matches(actual: str, expected: str) -> bool:
    """Ignore only LinkedIn's trailing visible expansion affordance."""

    return actual == expected or _COMMENT_EXPANSION_SUFFIX.sub("", actual) == expected


class PostEngagementPage:
    """Personal-member comments and explicit reaction-state changes."""

    def __init__(self, browser: BrowserManager, assets: LocalAssetStore) -> None:
        self._browser = browser
        self._assets = assets

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
        paths = await self._assets.resolve_comment(payload.attachment)
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
                paths,
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

    async def inspect_reaction(
        self,
        request: PostReactionInput,
    ) -> ActionInspection:
        target_url = canonical_post_url(request.post_ref)
        async with self._browser.page() as page:
            await self._browser.navigate(page, target_url)
            target = await self._resolve_target(page, request.post_ref)
            controls = await self._wait_for_visible_reaction_controls(target.region)
            if len(controls) != 1:
                raise ParserDriftError("LinkedIn has no unique visible reaction control.")
            existing = await self._reaction_state(target.region)
            if request.desired_reaction is not ReactionState.NONE:
                await self._reaction_option(
                    page,
                    target.region,
                    request.desired_reaction,
                )
            return ActionInspection(
                target=self._action_target(target, request.post_ref),
                current_state=f"reaction_ready:post:{existing.value}",
                source_url=HttpUrl(target_url),
                captured_text=await _visible_text(page),
                captured_at=datetime.now(UTC),
                existing_reaction=existing,
            )

    async def perform_reaction(self, command: ActionCommand) -> ActionPageResult:
        if not isinstance(command.payload, ReactionSetPayload):
            raise InvalidTargetError("The reaction action payload is invalid.")
        payload = command.payload
        async with self._browser.page() as page:
            await self._browser.navigate(page, canonical_post_url(payload.post_ref))
            target = await self._resolve_target(page, payload.post_ref)
            if not self._matches_inspected_target(command.target, target):
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "engagement_target_changed",
                    "The active member or visible reaction target changed after inspection.",
                )
            controls = await self._wait_for_visible_reaction_controls(target.region)
            if len(controls) != 1:
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "reaction_not_changed",
                    "The exact visible reaction control did not load before the action.",
                )
            current = await self._reaction_state(target.region)
            if current is not payload.existing_reaction:
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "reaction_state_changed",
                    (
                        "The visible reaction changed during the action; invoke it again "
                        "only after review."
                    ),
                )
            if current is payload.desired_reaction:
                return await self._result(
                    page,
                    ActionOutcome.VERIFIED,
                    False,
                    self._reaction_final_state(current),
                    "LinkedIn already shows the exact requested reaction state.",
                )
            try:
                if payload.desired_reaction is ReactionState.NONE:
                    control = await self._pressed_reaction_control(target.region, current)
                else:
                    control = await self._reaction_option(
                        page,
                        target.region,
                        payload.desired_reaction,
                    )
            except (ParserDriftError, PlaywrightError):
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "reaction_not_changed",
                    (
                        "The exact visible reaction control was unavailable before "
                        "the final state-changing click."
                    ),
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
                try:
                    current = await self._reaction_state(target.region)
                except ParserDriftError:
                    await page.wait_for_timeout(250)
                    continue
                if current is payload.desired_reaction:
                    return await self._result(
                        page,
                        ActionOutcome.VERIFIED,
                        True,
                        self._reaction_final_state(current),
                        "LinkedIn visibly shows the exact requested reaction state.",
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
    ) -> _VisibleTarget:
        post_region = await region_for_post(page, post_ref)
        author = await post_author_from_region(post_region)
        actor_slug, actor_name = await self._active_actor(page)
        return _VisibleTarget(
            region=post_region,
            actor_slug=actor_slug,
            actor_name=actor_name,
            content_author_name=author.name,
            content_author_url=author.author_url,
        )

    @staticmethod
    async def _active_actor(page: Page) -> tuple[str, str]:
        rail_slugs: set[str] = set()
        named_candidates: list[tuple[int, str, str]] = []
        for attempt in range(21):
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

            # The current post-detail layout exposes the signed-in member's
            # profile card in a complementary rail after the post itself. Bind
            # only when every visible profile link in that rail resolves to one
            # stable member slug and a visible display name.
            rail_candidates = page.locator("aside a[href*='/in/']")
            rail_slugs = set()
            named_candidates = []
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
            if len(rail_slugs) == 1:
                actor_slug = next(iter(rail_slugs))
                names = [candidate for candidate in named_candidates if candidate[1] == actor_slug]
                if names:
                    _, _, actor_name = max(names, key=lambda candidate: candidate[0])
                    return actor_slug, actor_name
            if attempt < 20:
                await page.wait_for_timeout(250)

        if len(rail_slugs) == 1 and not named_candidates:
            raise ParserDriftError("LinkedIn has no visible active member display name.")
        raise ParserDriftError("LinkedIn has no unique visible active member identity.")

    @staticmethod
    def _action_target(
        target: _VisibleTarget,
        post_ref: str,
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
            content_author_name=target.content_author_name,
            content_author_url=target.content_author_url,
        )

    @staticmethod
    def _matches_inspected_target(
        requested: ActionTarget,
        current: _VisibleTarget,
    ) -> bool:
        return (
            (requested.actor_profile_slug or requested.profile_slug) == current.actor_slug
            and (requested.actor_display_name or requested.display_name).casefold()
            == current.actor_name.casefold()
            and requested.content_author_name is not None
            and requested.content_author_name.casefold() == current.content_author_name.casefold()
            and (
                requested.content_author_url is None
                or (
                    current.content_author_url is not None
                    and str(requested.content_author_url) == str(current.content_author_url)
                )
            )
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
                and comment.parent_comment_ref is None
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

    async def _reaction_option(
        self,
        page: Page,
        region: Locator,
        desired: ReactionState,
    ) -> Locator:
        if desired is ReactionState.NONE:
            raise InvalidTargetError("Removal has no reaction-menu option.")
        controls = await self._wait_for_visible_reaction_controls(region)
        if not controls:
            fallback = region.get_by_role(
                "button",
                name=re.compile(
                    r"^(?:like|react|remove (?:like|reaction)|"
                    r"reaction button state: .+)$",
                    re.I,
                ),
            )
            controls = [
                fallback.nth(index)
                for index in range(await fallback.count())
                if await fallback.nth(index).is_visible()
            ]
        if len(controls) != 1:
            raise ParserDriftError("LinkedIn has no unique visible reaction control.")
        control = controls[0]
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
        # The current UI portals the six reaction buttons outside the post
        # region after hover and prefixes their accessible names with "React".
        # The trigger shares that name but retains aria-pressed, while menu
        # options do not. Wait only for one exact visible unpressed option.
        portaled_name = re.compile(
            rf"^(?:React\s+)?{re.escape(_REACTION_LABELS[desired])}$",
            re.I,
        )
        portaled = page.get_by_role("button", name=portaled_name).and_(
            page.locator("button:not([aria-pressed])")
        )
        visible: list[Locator] = []
        for attempt in range(20):
            visible = [
                portaled.nth(index)
                for index in range(await portaled.count())
                if await portaled.nth(index).is_visible()
            ]
            if len(visible) == 1:
                return visible[0]
            if attempt < 19:
                await page.wait_for_timeout(250)
        raise ParserDriftError(f"LinkedIn has no unique visible {desired.value} reaction option.")

    @staticmethod
    async def _reaction_control_state(control: Locator) -> ReactionState | None:
        state = control.locator(_REACTION_STATE_SELECTOR)
        state_control = state if await state.count() == 1 else control
        label = (await state_control.get_attribute("aria-label") or "").strip().casefold()
        if label.startswith("reaction button state:"):
            normalized = label.partition(":")[2].strip()
            if normalized == "no reaction":
                return ReactionState.NONE
            if normalized in {
                value.value for value in ReactionState if value is not ReactionState.NONE
            }:
                return ReactionState(normalized)
        match = re.fullmatch(
            r"react\s+(like|celebrate|support|love|insightful|funny)",
            label,
        )
        if match is not None:
            pressed = await control.get_attribute(
                "aria-pressed"
            ) or await state_control.get_attribute("aria-pressed")
            if pressed == "false":
                return ReactionState.NONE
            if pressed == "true":
                return ReactionState(match.group(1))
        return None

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
        current_controls = await PostEngagementPage._visible_reaction_controls(region)
        for item in current_controls:
            if (value := await PostEngagementPage._reaction_control_state(item)) is not None:
                return value
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
        raise ParserDriftError("LinkedIn exposed no visible reaction state.")

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
        current_containers = await PostEngagementPage._visible_reaction_controls(region)
        current_matches: list[Locator] = []
        for candidate in current_containers:
            if await PostEngagementPage._reaction_control_state(candidate) is current:
                current_matches.append(candidate)
        if len(current_matches) != 1:
            raise ParserDriftError("LinkedIn has no unique visible current reaction control.")
        return current_matches[0]

    @staticmethod
    async def _visible_reaction_controls(region: Locator) -> list[Locator]:
        local = region.locator(_REACTION_CONTROL_SELECTOR)
        visible = [
            local.nth(index)
            for index in range(await local.count())
            if await local.nth(index).is_visible()
        ]
        if visible:
            return visible
        region_box = await region.bounding_box()
        if region_box is None:
            return []
        current = region.page.locator(_REACTION_CONTROL_SELECTOR)
        for index in range(await current.count()):
            candidate = current.nth(index)
            if not await candidate.is_visible():
                continue
            box = await candidate.bounding_box()
            if box is None:
                continue
            center_x = box["x"] + box["width"] / 2
            center_y = box["y"] + box["height"] / 2
            if (
                region_box["x"] <= center_x <= region_box["x"] + region_box["width"]
                and region_box["y"] <= center_y <= region_box["y"] + region_box["height"]
            ):
                visible.append(candidate)
        return visible

    @staticmethod
    async def _wait_for_visible_reaction_controls(region: Locator) -> list[Locator]:
        for _ in range(20):
            visible = await PostEngagementPage._visible_reaction_controls(region)
            if visible:
                return visible
            await region.page.wait_for_timeout(250)
        return []

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
