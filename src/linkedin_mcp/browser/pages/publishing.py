"""Direct personal post publishing through LinkedIn's visible composer."""

from __future__ import annotations

import re
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import HttpUrl

from linkedin_mcp.assets import LocalAssetStore
from linkedin_mcp.browser.manager import BrowserManager
from linkedin_mcp.domain.models import (
    ActionCommand,
    ActionInspection,
    ActionOutcome,
    ActionPageResult,
    ActionTarget,
    CelebrationPostContent,
    CelebrationType,
    DocumentPostContent,
    EventFormat,
    EventPostContent,
    EventType,
    ExpertRequestCategory,
    ExpertRequestPostContent,
    HiringPostContent,
    ImagePostContent,
    PollDuration,
    PollPostContent,
    PostAudience,
    PostCommentControl,
    PostCreateInput,
    PostCreateMode,
    PostCreatePayload,
    PostImageAspectRatio,
    PostImageEditInput,
    PostImageFilter,
    PostImageInput,
    PostImageTagInput,
    PostMentionInput,
    TextPostContent,
    VideoCaptionMode,
    VideoPostContent,
)
from linkedin_mcp.errors import InvalidTargetError, ParserDriftError
from linkedin_mcp.policy import (
    canonical_post_url,
    canonical_profile_url,
    post_reference_from_value,
    profile_slug_from_url,
)

_HOME_URL = "https://www.linkedin.com/feed/"
_AUDIENCE_LABELS = {
    PostAudience.ANYONE: re.compile(r"^anyone$", re.I),
    PostAudience.CONNECTIONS_ONLY: re.compile(r"^connections only$", re.I),
    PostAudience.GROUP: re.compile(r"^group$", re.I),
}
_CURRENT_AUDIENCE_LABELS = {
    PostAudience.ANYONE: re.compile(r"^anyone(?:\s|$)", re.I),
    PostAudience.CONNECTIONS_ONLY: re.compile(r"^connections only(?:\s|$)", re.I),
    PostAudience.GROUP: re.compile(r"^group(?:\s|$)", re.I),
}
_COMMENT_LABELS = {
    PostCommentControl.ANYONE: re.compile(r"^anyone can comment$", re.I),
    PostCommentControl.CONNECTIONS_ONLY: re.compile(
        r"^connections only can comment$",
        re.I,
    ),
    PostCommentControl.NO_ONE: re.compile(r"^no one can comment$", re.I),
}
_CURRENT_COMMENT_LABELS = {
    PostCommentControl.ANYONE: re.compile(r"^anyone(?:\s|$)", re.I),
    PostCommentControl.CONNECTIONS_ONLY: re.compile(r"^connections only(?:\s|$)", re.I),
    PostCommentControl.NO_ONE: re.compile(r"^no one(?:\s|$)", re.I),
}
_POLL_LABELS = {
    PollDuration.ONE_DAY: "1 day",
    PollDuration.THREE_DAYS: "3 days",
    PollDuration.ONE_WEEK: "1 week",
    PollDuration.TWO_WEEKS: "2 weeks",
}
_CELEBRATION_LABELS = {
    CelebrationType.PROJECT_LAUNCH: "Project Launch",
    CelebrationType.WORK_ANNIVERSARY: "Work Anniversary",
    CelebrationType.NEW_POSITION: "New Position",
    CelebrationType.EDUCATIONAL_MILESTONE: "New Educational Milestone",
    CelebrationType.NEW_CERTIFICATION: "New Certification",
}
_IMAGE_ASPECT_LABELS = {
    PostImageAspectRatio.ORIGINAL: "Original",
    PostImageAspectRatio.SQUARE: "Square",
    PostImageAspectRatio.FOUR_TO_ONE: "4:1",
    PostImageAspectRatio.THREE_TO_FOUR: "3:4",
    PostImageAspectRatio.SIXTEEN_TO_NINE: "16:9",
}
_IMAGE_FILTER_LABELS = {
    PostImageFilter.ORIGINAL: "Original",
    PostImageFilter.STUDIO: "Studio",
    PostImageFilter.SPOTLIGHT: "Spotlight",
    PostImageFilter.PRIME: "Prime",
    PostImageFilter.CLASSIC: "Classic",
    PostImageFilter.EDGE: "Edge",
    PostImageFilter.LUMINATE: "Luminate",
}
_EXPERT_CATEGORY_LABELS = {
    ExpertRequestCategory.ACCOUNTING: "Accounting",
    ExpertRequestCategory.COACHING_AND_MENTORING: "Coaching & Mentoring",
    ExpertRequestCategory.DESIGN: "Design",
    ExpertRequestCategory.MARKETING: "Marketing",
    ExpertRequestCategory.OTHER: "Other",
}
_COMPOSER_READY_TIMEOUT_MS = 12_000


async def _visible_text(page: Page) -> str:
    for locator in (page.locator("main"), page.locator("body")):
        if await locator.count() == 0:
            continue
        text = (await locator.first.inner_text()).strip()
        if text:
            return text
    raise ParserDriftError("LinkedIn returned no visible post-composer text.")


async def _unique_visible(locator: Locator, description: str) -> Locator:
    matches: list[Locator] = []
    for index in range(await locator.count()):
        item = locator.nth(index)
        if await item.is_visible():
            matches.append(item)
    if len(matches) != 1:
        raise ParserDriftError(f"The visible post composer has no unique {description}.")
    return matches[0]


async def _unique_visible_or_hidden(locator: Locator, description: str) -> Locator:
    """Resolve one exact semantic input even when LinkedIn renders it visually hidden."""

    if await locator.count() != 1:
        raise ParserDriftError(f"The visible post composer has no unique {description}.")
    item = locator.first
    if await item.is_visible():
        return item
    parent = item.locator("xpath=..")
    if await parent.count() != 1 or not await parent.is_visible():
        raise ParserDriftError(f"The visible post composer has no operable {description}.")
    return item


class PostPublishingPage:
    """Narrow personal-member composer adapter; it never publishes as a Page."""

    def __init__(self, browser: BrowserManager, assets: LocalAssetStore) -> None:
        self._browser = browser
        self._assets = assets

    async def inspect_post(
        self,
        request: PostCreateInput,
    ) -> ActionInspection:
        self._validate_schedule(request.scheduled_at)
        async with self._browser.page() as page:
            await self._browser.navigate(page, _HOME_URL)
            dialog, slug, name = await self._open_composer(page)
            await self._assert_mode_available(page, dialog, request.content)
            await self._assert_settings_available(dialog, request)
            text = await _visible_text(page)
            return ActionInspection(
                target=ActionTarget(
                    profile_slug=slug,
                    profile_url=HttpUrl(canonical_profile_url(slug)),
                    display_name=name,
                    actor_profile_slug=slug,
                    actor_profile_url=HttpUrl(canonical_profile_url(slug)),
                    actor_display_name=name,
                ),
                current_state=(
                    f"personal_post_composer_ready:{request.content.mode.value}:"
                    f"{request.audience.value}:{request.comment_control.value}:"
                    f"{'scheduled' if request.scheduled_at else 'immediate'}"
                ),
                source_url=HttpUrl(page.url),
                captured_text=text,
                captured_at=datetime.now(UTC),
            )

    async def perform_post(self, command: ActionCommand) -> ActionPageResult:
        if not isinstance(command.payload, PostCreatePayload):
            raise InvalidTargetError("The personal-post action payload is invalid.")
        payload = command.payload
        self._validate_schedule(payload.scheduled_at)
        paths = await self._assets.resolve_post(payload.content)
        async with self._browser.page() as page:
            try:
                await self._browser.navigate(page, _HOME_URL)
                dialog, slug, name = await self._open_composer(page)
                expected_slug = command.target.actor_profile_slug or command.target.profile_slug
                expected_name = command.target.actor_display_name or command.target.display_name
                if slug != expected_slug or name.casefold() != expected_name.casefold():
                    return await self._result(
                        page,
                        ActionOutcome.FAILED,
                        False,
                        "actor_identity_changed",
                        (
                            "The active personal member no longer matches the requested "
                            "publishing actor."
                        ),
                    )

                await self._compose(page, dialog, payload, paths)
                dialog = await self._composer_dialog(page)
                await self._configure_settings(page, dialog, payload)
                if payload.scheduled_at is not None:
                    await self._configure_schedule(page, dialog, payload.scheduled_at)
                    dialog = await self._composer_dialog(page)

                marker = self._verification_marker(payload)
                before_refs = await self._matching_post_refs(page, marker)
                final_name = (
                    re.compile(r"^schedule$", re.I)
                    if payload.scheduled_at is not None
                    else re.compile(r"^post$", re.I)
                )
                final_control = await _unique_visible(
                    dialog.get_by_role("button", name=final_name),
                    "final Post or Schedule control",
                )
            except (ParserDriftError, PlaywrightError):
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "post_not_submitted",
                    (
                        "The visible composer did not reach a safe, operable state before "
                        "the final publishing control; no post was submitted."
                    ),
                )
            try:
                await self._browser.click_visible_control(page, final_control)
            except Exception:
                confirmation = await self._visible_publish_confirmation(page)
                if confirmation is not None:
                    return await self._confirmation_result(page, confirmation)
                return await self._result(
                    page,
                    ActionOutcome.UNCERTAIN,
                    None,
                    "post_outcome_unknown",
                    "The final publishing control was invoked, but its outcome is unknown.",
                )

            if payload.scheduled_at is not None:
                for _ in range(24):
                    text = await _visible_text(page)
                    if re.search(r"\bpost scheduled\b|\bscheduled successfully\b", text, re.I):
                        return await self._result(
                            page,
                            ActionOutcome.VERIFIED,
                            True,
                            "post_scheduled",
                            "LinkedIn visibly verified the exact requested post was scheduled.",
                        )
                    await page.wait_for_timeout(250)
                return await self._result(
                    page,
                    ActionOutcome.UNCERTAIN,
                    None,
                    "post_schedule_outcome_unknown",
                    "LinkedIn exposed no bounded visible scheduling confirmation.",
                )

            for _ in range(32):
                confirmation = await self._visible_publish_confirmation(page)
                if confirmation is not None:
                    return await self._confirmation_result(page, confirmation)
                current_refs = await self._matching_post_refs(page, marker)
                created = tuple(ref for ref in current_refs if ref not in before_refs)
                if len(created) == 1:
                    post_ref = created[0]
                    return await self._result(
                        page,
                        ActionOutcome.VERIFIED,
                        True,
                        f"post_published:{post_ref}",
                        "A single new visible post matched the exact requested content.",
                        source_url=canonical_post_url(post_ref),
                    )
                await page.wait_for_timeout(250)
            return await self._result(
                page,
                ActionOutcome.UNCERTAIN,
                None,
                "post_outcome_unknown",
                "No single newly visible post matched the requested payload within the bound.",
            )

    @staticmethod
    async def _visible_publish_confirmation(
        page: Page,
    ) -> tuple[ActionOutcome, bool, str, str, str | None] | None:
        candidates = page.get_by_role("alert").or_(page.get_by_role("status"))
        for index in range(await candidates.count()):
            candidate = candidates.nth(index)
            if not await candidate.is_visible():
                continue
            text = " ".join((await candidate.inner_text()).split())
            if re.search(r"\bpost successful\b|\bpost published\b", text, re.I):
                source_url: str | None = None
                post_ref: str | None = None
                view_post = candidate.get_by_role(
                    "link",
                    name=re.compile(r"^view post$", re.I),
                )
                visible_links = [
                    view_post.nth(link_index)
                    for link_index in range(await view_post.count())
                    if await view_post.nth(link_index).is_visible()
                ]
                if len(visible_links) == 1:
                    href = await visible_links[0].get_attribute("href")
                    if href:
                        source_url = urljoin(page.url, href)
                        post_ref = post_reference_from_value(source_url)
                final_state = f"post_published:{post_ref}" if post_ref else "post_published"
                return (
                    ActionOutcome.VERIFIED,
                    True,
                    final_state,
                    "LinkedIn visibly verified the exact post was published.",
                    source_url,
                )
            if re.search(
                r"(?:sorry|couldn['\u2019]?t|unable|failed).{0,80}(?:publish|post)"
                r"|(?:publish|post).{0,80}(?:failed|not sent|not published)",
                text,
                re.I,
            ):
                return (
                    ActionOutcome.FAILED,
                    False,
                    "post_not_published",
                    "LinkedIn visibly reported that the post was not published.",
                    None,
                )
        return None

    @staticmethod
    async def _confirmation_result(
        page: Page,
        confirmation: tuple[ActionOutcome, bool, str, str, str | None],
    ) -> ActionPageResult:
        outcome, performed, final_state, detail, source_url = confirmation
        return await PostPublishingPage._result(
            page,
            outcome,
            performed,
            final_state,
            detail,
            source_url=source_url,
        )

    async def _open_composer(self, page: Page) -> tuple[Locator, str, str]:
        start = await _unique_visible(
            page.get_by_role(
                "button",
                name=re.compile(r"^start a post$", re.I),
            ).or_(
                page.get_by_role(
                    "link",
                    name=re.compile(r"^start a post$", re.I),
                )
            ),
            "Start a post control",
        )
        identity_region = start.locator("xpath=ancestor::div[.//a[contains(@href, '/in/')]][1]")
        nearby_slugs = await self._visible_member_slugs(identity_region)
        nearby_identities = [
            identity
            for identity in await self._visible_member_identities(page.locator("body"))
            if identity[0] in nearby_slugs
        ]
        visible_target = await start.get_attribute("href")
        await self._browser.click_visible_control(page, start)
        try:
            dialog = await self._composer_dialog(page)
        except ParserDriftError:
            target = urljoin(_HOME_URL, visible_target or "")
            parsed = urlsplit(target)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "www.linkedin.com"
                or parsed.path != "/preload/sharebox/"
                or parsed.query
                or parsed.fragment
            ):
                raise
            await self._browser.navigate(page, target)
            dialog = await self._composer_dialog(page)
        identities = await self._visible_member_identities(dialog)
        if len(identities) == 1:
            if nearby_identities and identities[0] not in nearby_identities:
                raise ParserDriftError(
                    "The personal post composer actor conflicts with the visible feed actor."
                )
            return dialog, identities[0][0], identities[0][1]
        if not identities and nearby_identities:
            visibly_bound: list[tuple[str, str]] = []
            for slug, name in nearby_identities:
                visible_name = dialog.get_by_text(
                    re.compile(rf"^{re.escape(name)}$", re.I),
                    exact=True,
                )
                if any(
                    [
                        await visible_name.nth(index).is_visible()
                        for index in range(await visible_name.count())
                    ]
                ):
                    visibly_bound.append((slug, name))
            visibly_bound = list(dict.fromkeys(visibly_bound))
            if len(visibly_bound) == 1:
                return dialog, visibly_bound[0][0], visibly_bound[0][1]
        raise ParserDriftError(
            "The personal post composer has no unique visible member actor identity."
        )

    @staticmethod
    async def _visible_member_identities(root: Locator) -> list[tuple[str, str]]:
        if not await root.count():
            return []
        links = root.locator('a[href*="/in/"]')
        identities: list[tuple[str, str]] = []
        for index in range(min(await links.count(), 20)):
            link = links.nth(index)
            if not await link.is_visible():
                continue
            href = await link.get_attribute("href")
            name = (await link.inner_text()).strip()
            if not name:
                image = link.locator("img[alt]")
                if await image.count():
                    name = (await image.first.get_attribute("alt") or "").strip()
            slug = profile_slug_from_url(urljoin("https://www.linkedin.com", href or ""))
            if slug and name:
                identities.append((slug, name.splitlines()[0].strip()))
        return list(dict.fromkeys(identities))

    @staticmethod
    async def _visible_member_slugs(root: Locator) -> set[str]:
        if not await root.count():
            return set()
        slugs: set[str] = set()
        links = root.locator('a[href*="/in/"]')
        for index in range(min(await links.count(), 20)):
            link = links.nth(index)
            if not await link.is_visible():
                continue
            href = await link.get_attribute("href")
            slug = profile_slug_from_url(urljoin("https://www.linkedin.com", href or ""))
            if slug:
                slugs.add(slug)
        return slugs

    @staticmethod
    async def _composer_dialog(page: Page) -> Locator:
        candidates = page.get_by_role(
            "dialog",
            name=re.compile(r"(?:create|share|start).*(?:post)|post composer", re.I),
        )
        with suppress(PlaywrightTimeoutError):
            await candidates.first.wait_for(
                state="visible",
                timeout=_COMPOSER_READY_TIMEOUT_MS,
            )
        return await _unique_visible(candidates, "personal post composer dialog")

    async def _assert_mode_available(
        self,
        page: Page,
        dialog: Locator,
        content: (
            TextPostContent
            | ImagePostContent
            | VideoPostContent
            | DocumentPostContent
            | PollPostContent
            | CelebrationPostContent
            | EventPostContent
            | HiringPostContent
            | ExpertRequestPostContent
        ),
    ) -> None:
        mode = content.mode
        if mode is PostCreateMode.TEXT:
            await self._composer_textbox(dialog)
            return
        names = {
            PostCreateMode.IMAGES: re.compile(r"^add media$", re.I),
            PostCreateMode.VIDEO: re.compile(r"^add media$", re.I),
            PostCreateMode.DOCUMENT: re.compile(r"^(?:add a )?document$", re.I),
            PostCreateMode.POLL: re.compile(r"^(?:create a )?poll$", re.I),
            PostCreateMode.CELEBRATION: re.compile(
                r"^celebrate an occasion$",
                re.I,
            ),
            PostCreateMode.EVENT: re.compile(r"^create an event$", re.I),
            PostCreateMode.HIRING: re.compile(
                r"^share that you(?:'|\u2019)re hiring$",
                re.I,
            ),
            PostCreateMode.EXPERT_REQUEST: re.compile(r"^find an expert$", re.I),
        }
        if mode in {
            PostCreateMode.DOCUMENT,
            PostCreateMode.POLL,
            PostCreateMode.HIRING,
            PostCreateMode.EXPERT_REQUEST,
        }:
            more = await _unique_visible(
                dialog.get_by_role("button", name=re.compile(r"^more$", re.I)),
                "More publishing-options control",
            )
            await self._browser.click_visible_control(page, more)
        await _unique_visible(
            page.get_by_role("button", name=names[mode]),
            f"{mode.value} publishing option",
        )

    async def _assert_settings_available(
        self,
        dialog: Locator,
        request: PostCreateInput,
    ) -> None:
        page = dialog.page
        if request.collaborators:
            await _unique_visible(
                dialog.get_by_role(
                    "button",
                    name=re.compile(r"^add collaborators$", re.I),
                ),
                "Add collaborators control for this rollout-eligible account",
            )
        settings_control = dialog.get_by_role(
            "button",
            name=re.compile(r"^post settings", re.I),
        ).or_(
            dialog.get_by_role(
                "button",
                name=re.compile(
                    r"\bpost to (?:anyone|connections only|group)\b",
                    re.I,
                ),
            )
        )
        schedule_control = dialog.get_by_role(
            "button",
            name=re.compile(r"^schedule post$", re.I),
        )
        post_control = dialog.get_by_role("button", name=re.compile(r"^post$", re.I))
        with suppress(PlaywrightTimeoutError):
            await settings_control.first.wait_for(state="visible", timeout=3_000)
            await schedule_control.first.wait_for(state="visible", timeout=3_000)
            await post_control.first.wait_for(state="visible", timeout=3_000)
        settings_control = await _unique_visible(
            settings_control,
            "Post settings control",
        )
        await _unique_visible(
            schedule_control,
            "Schedule post control",
        )
        await _unique_visible(
            post_control,
            "Post control",
        )
        await self._browser.click_visible_control(page, settings_control)
        settings_candidates = page.get_by_role(
            "dialog",
            name=re.compile(r"^post settings$", re.I),
        )
        with suppress(PlaywrightTimeoutError):
            await settings_candidates.first.wait_for(state="visible", timeout=3_000)
        settings = await _unique_visible(
            settings_candidates,
            "Post settings dialog",
        )
        current_comment_control = settings.get_by_role(
            "button",
            name=re.compile(r"^comment control\b", re.I),
        )
        visible_current_controls = [
            current_comment_control.nth(index)
            for index in range(await current_comment_control.count())
            if await current_comment_control.nth(index).is_visible()
        ]
        audience_labels = _CURRENT_AUDIENCE_LABELS if visible_current_controls else _AUDIENCE_LABELS
        requested_audience = await _unique_visible(
            settings.get_by_role(
                "radio",
                name=audience_labels[request.audience],
            ),
            "requested audience option",
        )
        if request.audience is PostAudience.GROUP:
            await self._browser.click_visible_control(page, requested_audience)
            assert request.group_target is not None
            await self._select_exact_group_target(
                page,
                request.group_target.group_id,
                request.group_target.display_name,
            )
            settings = await _unique_visible(
                settings_candidates,
                "Post settings dialog",
            )
        if request.brand_partnership:
            await self._brand_partnership_control(settings)
        if visible_current_controls:
            if len(visible_current_controls) != 1:
                raise ParserDriftError("The visible post composer has no unique Comment control.")
            await self._browser.click_visible_control(page, visible_current_controls[0])
            comment_dialog_candidates = page.get_by_role(
                "dialog",
                name=re.compile(r"^comment control$", re.I),
            )
            with suppress(PlaywrightTimeoutError):
                await comment_dialog_candidates.first.wait_for(
                    state="visible",
                    timeout=3_000,
                )
            comment_dialog = await _unique_visible(
                comment_dialog_candidates,
                "Comment control dialog",
            )
            await _unique_visible(
                comment_dialog.get_by_role(
                    "radio",
                    name=_CURRENT_COMMENT_LABELS[request.comment_control],
                ),
                "requested comment-control option",
            )
        else:
            await _unique_visible(
                settings.get_by_role(
                    "radio",
                    name=_COMMENT_LABELS[request.comment_control],
                ),
                "requested comment-control option",
            )

    async def _compose(
        self,
        page: Page,
        dialog: Locator,
        payload: PostCreatePayload,
        paths: dict[str, Path],
    ) -> None:
        content = payload.content
        if isinstance(content, ImagePostContent):
            await self._compose_images(page, dialog, content, paths)
        elif isinstance(content, VideoPostContent):
            await self._compose_video(page, dialog, content, paths)
        elif isinstance(content, DocumentPostContent):
            await self._compose_document(page, dialog, content, paths)
        elif isinstance(content, PollPostContent):
            await self._compose_poll(page, dialog, content)
        elif isinstance(content, CelebrationPostContent):
            await self._compose_celebration(page, dialog, content, paths)
        elif isinstance(content, EventPostContent):
            await self._compose_event(page, dialog, content, paths)
        elif isinstance(content, HiringPostContent):
            await self._compose_hiring(page, dialog, content)
        elif isinstance(content, ExpertRequestPostContent):
            await self._compose_expert_request(page, dialog, content)

        dialog = await self._composer_dialog(page)
        if content.text is not None:
            textbox = await self._composer_textbox(dialog)
            maximum = await textbox.get_attribute("maxlength")
            if maximum and len(content.text) > int(maximum):
                raise InvalidTargetError(
                    "The requested post text exceeds LinkedIn's visible composer limit."
                )
            await self._fill_text_with_mentions(page, textbox, content.text, content.mentions)
        if isinstance(content, TextPostContent) and content.link_url is not None:
            preview = dialog.locator("[data-link-preview], [data-testid='link-preview']")
            try:
                await preview.first.wait_for(state="visible", timeout=5_000)
            except PlaywrightTimeoutError as error:
                raise ParserDriftError(
                    "The requested link did not produce a visible composer preview."
                ) from error
            if not content.show_link_preview:
                remove = await _unique_visible(
                    dialog.get_by_role(
                        "button",
                        name=re.compile(r"^(?:remove|remove preview)$", re.I),
                    ),
                    "Remove link preview control",
                )
                await self._browser.click_visible_control(page, remove)
        if payload.collaborators:
            dialog = await self._composer_dialog(page)
            await self._configure_collaborators(page, dialog, payload)

    async def _compose_images(
        self,
        page: Page,
        dialog: Locator,
        content: ImagePostContent,
        paths: dict[str, Path],
    ) -> None:
        control = await _unique_visible(
            dialog.get_by_role("button", name=re.compile(r"^add media$", re.I)),
            "Add media control",
        )
        await self._browser.click_visible_control(page, control)
        editor = await self._media_editor(page)
        upload = await _unique_visible(
            editor.locator('input[type="file"]'),
            "media file input",
        )
        await upload.set_input_files([str(paths[image.asset_ref]) for image in content.images])
        selection_controls = editor.get_by_role(
            "button",
            name=re.compile(r"^select .+", re.I),
        )
        with suppress(PlaywrightTimeoutError):
            await selection_controls.first.wait_for(state="visible", timeout=10_000)
        visible_selections = [
            selection_controls.nth(index)
            for index in range(await selection_controls.count())
            if await selection_controls.nth(index).is_visible()
        ]
        if len(visible_selections) != len(content.images):
            raise ParserDriftError(
                "LinkedIn's media editor did not expose one selectable photo per upload."
            )
        for index, image in enumerate(content.images):
            await self._browser.click_visible_control(page, visible_selections[index])
            if image.edit is not None:
                await self._edit_image(page, editor, image.edit)
                editor = await self._media_editor(page)
            if image.alt_text is not None:
                await self._add_image_alt_text(page, editor, image.alt_text)
                editor = await self._media_editor(page)
            if image.tags:
                await self._tag_image(page, editor, image)
                editor = await self._media_editor(page)
        next_control = await _unique_visible(
            editor.get_by_role("button", name=re.compile(r"^next$", re.I)),
            "media editor Next control",
        )
        await self._browser.click_visible_control(page, next_control)

    @staticmethod
    async def _media_editor(page: Page) -> Locator:
        dialogs = page.get_by_role("dialog").filter(
            has=page.locator('input[type="file"][accept*="image"]')
        )
        with suppress(PlaywrightTimeoutError):
            await dialogs.first.wait_for(state="visible", timeout=10_000)
        return await _unique_visible(dialogs, "current media editor")

    async def _edit_image(
        self,
        page: Page,
        editor: Locator,
        edit: PostImageEditInput,
    ) -> None:
        open_control = await _unique_visible(
            editor.get_by_role("button", name=re.compile(r"^edit$", re.I)),
            "image Edit control",
        )
        await self._browser.click_visible_control(page, open_control)
        image_editor = await _unique_visible(
            page.get_by_role("dialog").filter(
                has=page.get_by_role("tab", name=re.compile(r"^crop$", re.I))
            ),
            "image-edit dialog",
        )
        aspect = await _unique_visible(
            image_editor.get_by_role(
                "radio",
                name=re.compile(
                    rf"^{re.escape(_IMAGE_ASPECT_LABELS[edit.aspect_ratio])}$",
                    re.I,
                ),
            ),
            "image aspect-ratio option",
        )
        if not await aspect.is_checked():
            await self._browser.click_visible_control(page, aspect)
        rotation_name = (
            re.compile(r"^rotate clockwise$", re.I)
            if edit.clockwise_quarter_turns > 0
            else re.compile(r"^rotate (?:anti|counter)clockwise$", re.I)
        )
        for _ in range(abs(edit.clockwise_quarter_turns)):
            await self._browser.click_visible_control(
                page,
                await _unique_visible(
                    image_editor.get_by_role("button", name=rotation_name),
                    "image rotation control",
                ),
            )
        if edit.flip_horizontal:
            await self._browser.click_visible_control(
                page,
                await _unique_visible(
                    image_editor.get_by_role(
                        "button",
                        name=re.compile(r"flip.*(?:horizontal|x)", re.I),
                    ),
                    "horizontal image-flip control",
                ),
            )
        if edit.flip_vertical:
            await self._browser.click_visible_control(
                page,
                await _unique_visible(
                    image_editor.get_by_role(
                        "button",
                        name=re.compile(r"flip.*(?:vertical|y)", re.I),
                    ),
                    "vertical image-flip control",
                ),
            )
        await self._set_slider(image_editor, "zoom", edit.zoom)
        await self._set_slider(
            image_editor,
            "straighten",
            edit.straighten_degrees,
        )
        if edit.image_filter is not PostImageFilter.ORIGINAL:
            await self._browser.click_visible_control(
                page,
                await _unique_visible(
                    image_editor.get_by_role("tab", name=re.compile(r"^filter$", re.I)),
                    "Filter tab",
                ),
            )
            filter_control = await _unique_visible(
                image_editor.get_by_role(
                    "radio",
                    name=re.compile(
                        rf"^{re.escape(_IMAGE_FILTER_LABELS[edit.image_filter])}$",
                        re.I,
                    ),
                ).or_(
                    image_editor.get_by_role(
                        "button",
                        name=re.compile(
                            rf"^{re.escape(_IMAGE_FILTER_LABELS[edit.image_filter])}$",
                            re.I,
                        ),
                    )
                ),
                "image filter option",
            )
            await self._browser.click_visible_control(page, filter_control)
        adjustments = {
            "brightness": edit.brightness,
            "contrast": edit.contrast,
            "saturation": edit.saturation,
            "vignette": edit.vignette,
        }
        if any(adjustments.values()):
            await self._browser.click_visible_control(
                page,
                await _unique_visible(
                    image_editor.get_by_role("tab", name=re.compile(r"^adjust$", re.I)),
                    "Adjust tab",
                ),
            )
            for name, value in adjustments.items():
                await self._set_slider(image_editor, name, value)
        apply_control = await _unique_visible(
            image_editor.get_by_role(
                "button",
                name=re.compile(r"^(?:apply|save|done)$", re.I),
            ),
            "image edit Apply control",
        )
        await self._browser.click_visible_control(page, apply_control)

    @staticmethod
    async def _set_slider(root: Locator, label: str, value: int | float) -> None:
        sliders = root.get_by_role("slider", name=re.compile(label, re.I)).or_(
            root.locator(
                f'input[type="range"][aria-labelledby*="{label}" i], '
                f'input[type="range"][aria-label*="{label}" i]'
            )
        )
        slider = await _unique_visible(sliders, f"{label} slider")
        minimum = float(await slider.get_attribute("min") or "0")
        maximum = float(await slider.get_attribute("max") or "100")
        numeric = float(value)
        if not minimum <= numeric <= maximum:
            raise InvalidTargetError(
                f"The requested {label} value is outside LinkedIn's visible control range."
            )
        await slider.fill(str(value))

    async def _add_image_alt_text(
        self,
        page: Page,
        editor: Locator,
        alt_text: str,
    ) -> None:
        control = await _unique_visible(
            editor.get_by_role(
                "button",
                name=re.compile(r"^alternative text$", re.I),
            ),
            "Alternative text control",
        )
        await self._browser.click_visible_control(page, control)
        alt_dialog = await _unique_visible(
            page.get_by_role("dialog").filter(
                has=page.get_by_placeholder(re.compile(r"how would you describe this image", re.I))
            ),
            "alternative-text dialog",
        )
        field = await _unique_visible(
            alt_dialog.get_by_placeholder(re.compile(r"how would you describe this image", re.I)),
            "alternative-text field",
        )
        maximum = await field.get_attribute("maxlength")
        if maximum != "1000":
            raise ParserDriftError(
                "LinkedIn's current alternative-text field no longer has the verified limit."
            )
        await field.fill(alt_text)
        await self._browser.click_visible_control(
            page,
            await _unique_visible(
                alt_dialog.get_by_role("button", name=re.compile(r"^add$", re.I)),
                "alternative-text Add control",
            ),
        )

    async def _tag_image(
        self,
        page: Page,
        editor: Locator,
        image: PostImageInput,
    ) -> None:
        await self._browser.click_visible_control(
            page,
            await _unique_visible(
                editor.get_by_role("button", name=re.compile(r"^tag$", re.I)),
                "image Tag control",
            ),
        )
        tag_dialog = await _unique_visible(
            page.get_by_role("dialog").filter(
                has=page.get_by_placeholder(re.compile(r"type a name or names", re.I))
            ),
            "image-tag dialog",
        )
        search = await _unique_visible(
            tag_dialog.get_by_placeholder(re.compile(r"type a name or names", re.I)),
            "image-tag search field",
        )
        for identity in image.tags:
            await search.fill(identity.display_name)
            target = self._image_tag_result(tag_dialog, identity)
            await self._browser.click_visible_control(
                page,
                await _unique_visible(target, "exact image-tag result"),
            )
        await self._browser.click_visible_control(
            page,
            await _unique_visible(
                tag_dialog.get_by_role("button", name=re.compile(r"^add$", re.I)),
                "image-tag Add control",
            ),
        )

    @staticmethod
    def _image_tag_result(root: Locator, identity: PostImageTagInput) -> Locator:
        if identity.profile_slug is not None:
            return root.locator(f'a[href*="/in/{identity.profile_slug}/"]')
        assert identity.company_slug is not None
        return root.locator(f'a[href*="/company/{identity.company_slug}/"]')

    async def _compose_video(
        self,
        page: Page,
        dialog: Locator,
        content: VideoPostContent,
        paths: dict[str, Path],
    ) -> None:
        control = await _unique_visible(
            dialog.get_by_role("button", name=re.compile(r"^add media$", re.I)),
            "Add media control",
        )
        await self._browser.click_visible_control(page, control)
        editor = await self._media_editor(page)
        upload = await _unique_visible(editor.locator('input[type="file"]'), "media file input")
        await upload.set_input_files(str(paths[content.video_asset_ref]))
        play = editor.get_by_role("button", name=re.compile(r"^play$", re.I))
        with suppress(PlaywrightTimeoutError):
            await play.first.wait_for(state="visible", timeout=15_000)
        await _unique_visible(play, "uploaded-video Play control")
        if content.thumbnail_asset_ref is not None:
            thumbnail = await _unique_visible(
                editor.get_by_role("button", name=re.compile(r"^video thumbnail$", re.I)),
                "video thumbnail control",
            )
            await self._browser.click_visible_control(page, thumbnail)
            thumbnail_dialog = await _unique_visible(
                page.get_by_role("dialog").filter(
                    has=page.locator('input[type="file"][aria-label="Add video thumbnail"]')
                ),
                "video-thumbnail dialog",
            )
            input_control = await _unique_visible(
                thumbnail_dialog.locator('input[type="file"][aria-label="Add video thumbnail"]'),
                "video thumbnail file input",
            )
            await input_control.set_input_files(str(paths[content.thumbnail_asset_ref]))
            await self._browser.click_visible_control(
                page,
                await _unique_visible(
                    thumbnail_dialog.get_by_role(
                        "button",
                        name=re.compile(r"^add$", re.I),
                    ),
                    "video-thumbnail Add control",
                ),
            )
            editor = await self._media_editor(page)
        captions = await _unique_visible(
            editor.get_by_role("button", name=re.compile(r"^captions$", re.I)),
            "video captions control",
        )
        await self._browser.click_visible_control(page, captions)
        caption_dialog = await _unique_visible(
            page.get_by_role("dialog").filter(
                has=page.get_by_role(
                    "checkbox",
                    name=re.compile(r"add auto captions", re.I),
                )
            ),
            "video-captions dialog",
        )
        auto = await _unique_visible(
            caption_dialog.get_by_role(
                "checkbox",
                name=re.compile(r"add auto captions", re.I),
            ),
            "automatic captions option",
        )
        should_auto = content.caption_mode is VideoCaptionMode.AUTO
        if await auto.is_checked() != should_auto:
            await self._browser.click_visible_control(page, auto)
        review = await _unique_visible(
            caption_dialog.get_by_role(
                "checkbox",
                name=re.compile(r"review captions", re.I),
            ),
            "caption review option",
        )
        should_review = should_auto and content.review_auto_captions
        if await review.is_checked() != should_review:
            await self._browser.click_visible_control(page, review)
        if content.caption_mode is VideoCaptionMode.FILE:
            upload_caption = await _unique_visible(
                caption_dialog.locator('input[type="file"][accept*=".srt"]'),
                "caption file input",
            )
            assert content.caption_asset_ref is not None
            await upload_caption.set_input_files(str(paths[content.caption_asset_ref]))
        await self._browser.click_visible_control(
            page,
            await _unique_visible(
                caption_dialog.get_by_role("button", name=re.compile(r"^apply$", re.I)),
                "captions Apply control",
            ),
        )
        editor = await self._media_editor(page)
        next_control = await _unique_visible(
            editor.get_by_role("button", name=re.compile(r"^next$", re.I)),
            "video editor Next control",
        )
        await self._browser.click_visible_control(page, next_control)

    async def _compose_document(
        self,
        page: Page,
        dialog: Locator,
        content: DocumentPostContent,
        paths: dict[str, Path],
    ) -> None:
        more = await _unique_visible(
            dialog.get_by_role("button", name=re.compile(r"^more$", re.I)),
            "More publishing-options control",
        )
        await self._browser.click_visible_control(page, more)
        add = await _unique_visible(
            page.get_by_role("button", name=re.compile(r"^(?:add a )?document$", re.I)),
            "Document publishing option",
        )
        await self._browser.click_visible_control(page, add)
        editor = await _unique_visible(
            page.get_by_role("dialog").filter(
                has=page.get_by_text(
                    re.compile(r"^share a document$", re.I),
                    exact=True,
                )
            ),
            "Share a document dialog",
        )
        upload = await _unique_visible(editor.locator('input[type="file"]'), "document file input")
        await upload.set_input_files(str(paths[content.document_asset_ref]))
        title = await _unique_visible(
            editor.get_by_placeholder(
                re.compile(r"add a descriptive title to your document", re.I)
            ),
            "document title field",
        )
        await title.fill(content.document_title)
        done = await _unique_visible(
            editor.get_by_role("button", name=re.compile(r"^done$", re.I)),
            "document Done control",
        )
        await self._browser.click_visible_control(page, done)

    async def _compose_poll(
        self,
        page: Page,
        dialog: Locator,
        content: PollPostContent,
    ) -> None:
        more = await _unique_visible(
            dialog.get_by_role("button", name=re.compile(r"^more$", re.I)),
            "More publishing-options control",
        )
        await self._browser.click_visible_control(page, more)
        add = await _unique_visible(
            page.get_by_role("button", name=re.compile(r"^(?:create a )?poll$", re.I)),
            "Poll publishing option",
        )
        await self._browser.click_visible_control(page, add)
        editor = await _unique_visible(
            page.get_by_role("dialog", name=re.compile(r"create a poll", re.I)),
            "poll editor",
        )
        question = await _unique_visible(
            editor.locator("textarea[maxlength='140']"),
            "poll question field",
        )
        await question.fill(content.question)
        for index, option in enumerate(content.options, start=1):
            fields = editor.locator("input[maxlength='30']")
            if await fields.count() < index:
                add_option = await _unique_visible(
                    editor.get_by_role("button", name=re.compile(r"^add option$", re.I)),
                    "Add poll option control",
                )
                await self._browser.click_visible_control(page, add_option)
            field = fields.nth(index - 1)
            if not await field.is_visible():
                raise ParserDriftError(
                    f"LinkedIn's poll editor has no visible option {index} field."
                )
            await field.fill(option)
        duration = await _unique_visible(
            editor.get_by_role("combobox", name=re.compile(r"poll duration", re.I)),
            "poll duration control",
        )
        await duration.select_option(label=_POLL_LABELS[content.duration])
        done = await _unique_visible(
            editor.get_by_role("button", name=re.compile(r"^done$", re.I)),
            "poll Done control",
        )
        await self._browser.click_visible_control(page, done)

    async def _compose_celebration(
        self,
        page: Page,
        dialog: Locator,
        content: CelebrationPostContent,
        paths: dict[str, Path],
    ) -> None:
        open_control = await _unique_visible(
            dialog.get_by_role(
                "button",
                name=re.compile(r"^celebrate an occasion$", re.I),
            ),
            "Celebrate an occasion control",
        )
        await self._browser.click_visible_control(page, open_control)
        chooser = await _unique_visible(
            page.get_by_role("dialog").filter(
                has=page.get_by_text(
                    re.compile(
                        rf"^{re.escape(_CELEBRATION_LABELS[content.celebration_type])}$",
                        re.I,
                    ),
                    exact=True,
                )
            ),
            "celebration chooser",
        )
        await self._browser.click_visible_control(
            page,
            await _unique_visible(
                chooser.get_by_role(
                    "button",
                    name=re.compile(
                        rf"^{re.escape(_CELEBRATION_LABELS[content.celebration_type])}$",
                        re.I,
                    ),
                ),
                "exact celebration type",
            ),
        )
        editor = await _unique_visible(
            page.get_by_role("dialog").filter(
                has=page.get_by_role(
                    "button",
                    name=re.compile(r"^template 1$", re.I),
                )
            ),
            "celebration image editor",
        )
        if content.image_asset_ref is not None:
            upload = await _unique_visible(
                editor.locator('input[type="file"][accept*="image"]'),
                "celebration custom-image input",
            )
            await upload.set_input_files(str(paths[content.image_asset_ref]))
            if content.image_alt_text is not None:
                await self._add_image_alt_text(page, editor, content.image_alt_text)
                editor = await _unique_visible(
                    page.get_by_role("dialog").filter(
                        has=page.get_by_role(
                            "button",
                            name=re.compile(r"^template 1$", re.I),
                        )
                    ),
                    "celebration image editor",
                )
        else:
            assert content.template_index is not None
            await self._browser.click_visible_control(
                page,
                await _unique_visible(
                    editor.get_by_role(
                        "button",
                        name=re.compile(
                            rf"^template {content.template_index}$",
                            re.I,
                        ),
                    ),
                    "exact celebration template",
                ),
            )
        await self._browser.click_visible_control(
            page,
            await _unique_visible(
                editor.get_by_role("button", name=re.compile(r"^next$", re.I)),
                "celebration Next control",
            ),
        )

    async def _compose_event(
        self,
        page: Page,
        dialog: Locator,
        content: EventPostContent,
        paths: dict[str, Path],
    ) -> None:
        await self._browser.click_visible_control(
            page,
            await _unique_visible(
                dialog.get_by_role(
                    "button",
                    name=re.compile(r"^create an event$", re.I),
                ),
                "Create an event control",
            ),
        )
        editor = await _unique_visible(
            page.get_by_role("dialog").filter(
                has=page.get_by_role(
                    "textbox",
                    name=re.compile(r"event name", re.I),
                )
            ),
            "event editor",
        )
        if content.cover_asset_ref is not None:
            cover = await _unique_visible(
                editor.locator('input[type="file"][accept*="image"]'),
                "event cover-image input",
            )
            await cover.set_input_files(str(paths[content.cover_asset_ref]))
            if content.cover_alt_text is not None:
                await self._set_optional_alt_text(
                    page,
                    editor,
                    content.cover_alt_text,
                    "event cover",
                )
        event_type = await _unique_visible(
            editor.get_by_role(
                "radio",
                name=re.compile(
                    r"^online$" if content.event_type is EventType.ONLINE else r"^in person$",
                    re.I,
                ),
            ),
            "event type option",
        )
        if not await event_type.is_checked():
            await self._browser.click_visible_control(page, event_type)
        if content.event_type is EventType.ONLINE:
            assert content.event_format is not None
            format_label = (
                "LinkedIn Live"
                if content.event_format is EventFormat.LINKEDIN_LIVE
                else "External event link"
            )
            event_format = await _unique_visible(
                editor.get_by_role(
                    "radio",
                    name=re.compile(rf"^{re.escape(format_label)}$", re.I),
                ),
                "event format option",
            )
            if not await event_format.is_checked():
                await self._browser.click_visible_control(page, event_format)
        name = await _unique_visible(
            editor.get_by_role("textbox", name=re.compile(r"event name", re.I)),
            "event name field",
        )
        if await name.get_attribute("maxlength") != "75":
            raise ParserDriftError(
                "LinkedIn's current event-name field no longer has the verified limit."
            )
        await name.fill(content.event_name)
        await self._set_event_timezone(page, editor, content.timezone_label)
        await self._fill_event_times(editor, content)
        description = await _unique_visible(
            editor.locator("textarea[maxlength='5000']"),
            "event description field",
        )
        await description.fill(content.description)
        if content.event_type is EventType.ONLINE:
            if content.external_url is not None:
                await self._fill_exact_url_field(editor, str(content.external_url))
        else:
            assert content.venue_location is not None
            location = await _unique_visible(
                editor.get_by_placeholder(
                    re.compile(r"street, city, pincode", re.I),
                ),
                "event location field",
            )
            await location.fill(content.venue_location)
            if content.venue_details is not None:
                details = await _unique_visible(
                    editor.get_by_placeholder(
                        re.compile(r"floor number, room number", re.I),
                    ),
                    "event venue-details field",
                )
                await details.fill(content.venue_details)
            if content.external_url is not None:
                await self._fill_exact_url_field(editor, str(content.external_url))
        if content.speakers:
            speaker_field = await _unique_visible(
                editor.get_by_role(
                    "combobox",
                    name=re.compile(r"speaker", re.I),
                ),
                "event speaker field",
            )
            for speaker in content.speakers:
                await speaker_field.fill(speaker.display_name)
                await self._browser.click_visible_control(
                    page,
                    await _unique_visible(
                        page.get_by_role("listbox").locator(
                            f'a[href*="/in/{speaker.profile_slug}/"]'
                        ),
                        "exact first-degree event speaker",
                    ),
                )
        await self._browser.click_visible_control(
            page,
            await _unique_visible(
                editor.get_by_role(
                    "button",
                    name=re.compile(r"^(?:done|next)$", re.I),
                ),
                "event Done control",
            ),
        )

    async def _set_optional_alt_text(
        self,
        page: Page,
        root: Locator,
        alt_text: str,
        description: str,
    ) -> None:
        control = root.get_by_role(
            "button",
            name=re.compile(r"alternative text", re.I),
        )
        if await control.count() == 0:
            raise ParserDriftError(
                f"LinkedIn's current {description} editor exposes no alternative-text control."
            )
        await self._browser.click_visible_control(
            page,
            await _unique_visible(control, f"{description} alternative-text control"),
        )
        field = await _unique_visible(
            page.get_by_placeholder(
                re.compile(r"how would you describe this image", re.I),
            ),
            f"{description} alternative-text field",
        )
        await field.fill(alt_text)
        parent_dialog = await _unique_visible(
            page.get_by_role("dialog").filter(has=field),
            f"{description} alternative-text dialog",
        )
        await self._browser.click_visible_control(
            page,
            await _unique_visible(
                parent_dialog.get_by_role(
                    "button",
                    name=re.compile(r"^(?:add|save)$", re.I),
                ),
                f"{description} alternative-text Save control",
            ),
        )

    async def _set_event_timezone(
        self,
        page: Page,
        editor: Locator,
        timezone_label: str,
    ) -> None:
        timezone = await _unique_visible(
            editor.get_by_role(
                "button",
                name=re.compile(r"time ?zone", re.I),
            ).or_(
                editor.get_by_role(
                    "combobox",
                    name=re.compile(r"time ?zone", re.I),
                )
            ),
            "event timezone control",
        )
        await self._browser.click_visible_control(page, timezone)
        option = page.get_by_role(
            "option",
            name=re.compile(rf"^{re.escape(timezone_label)}$", re.I),
        ).or_(
            page.get_by_role(
                "button",
                name=re.compile(rf"^{re.escape(timezone_label)}$", re.I),
            )
        )
        await self._browser.click_visible_control(
            page,
            await _unique_visible(option, "exact event timezone option"),
        )

    @staticmethod
    async def _fill_event_times(editor: Locator, content: EventPostContent) -> None:
        dates = editor.get_by_role("textbox", name=re.compile(r"date", re.I))
        times = editor.get_by_role("textbox", name=re.compile(r"time", re.I))
        visible_dates = [
            dates.nth(index)
            for index in range(await dates.count())
            if await dates.nth(index).is_visible()
        ]
        visible_times = [
            times.nth(index)
            for index in range(await times.count())
            if await times.nth(index).is_visible()
        ]
        if not visible_dates or not visible_times:
            raise ParserDriftError("LinkedIn's event editor has no unique start date and time.")
        await visible_dates[0].fill(content.start_at.strftime("%Y-%m-%d"))
        await visible_times[0].fill(content.start_at.strftime("%H:%M"))
        if content.end_at is None:
            return
        end_toggle = await _unique_visible(
            editor.get_by_role(
                "checkbox",
                name=re.compile(r"end date|end time", re.I),
            ),
            "event end-date option",
        )
        if not await end_toggle.is_checked():
            await end_toggle.click()
        visible_dates = [
            dates.nth(index)
            for index in range(await dates.count())
            if await dates.nth(index).is_visible()
        ]
        visible_times = [
            times.nth(index)
            for index in range(await times.count())
            if await times.nth(index).is_visible()
        ]
        if len(visible_dates) != 2 or len(visible_times) != 2:
            raise ParserDriftError(
                "LinkedIn's event editor has no unique end date and time fields."
            )
        await visible_dates[1].fill(content.end_at.strftime("%Y-%m-%d"))
        await visible_times[1].fill(content.end_at.strftime("%H:%M"))

    @staticmethod
    async def _fill_exact_url_field(editor: Locator, value: str) -> None:
        fields = editor.locator('input[maxlength="1024"][type="url"], input[maxlength="1024"]')
        visible = [
            fields.nth(index)
            for index in range(await fields.count())
            if await fields.nth(index).is_visible()
        ]
        if len(visible) != 1:
            raise ParserDriftError("LinkedIn's event editor has no unique event URL field.")
        await visible[0].fill(value)

    async def _compose_hiring(
        self,
        page: Page,
        dialog: Locator,
        content: HiringPostContent,
    ) -> None:
        await self._open_more_option(
            page,
            dialog,
            re.compile(r"^share that you(?:'|\u2019)re hiring$", re.I),
            "Share that you're hiring",
        )
        chooser = await _unique_visible(
            page.get_by_role("dialog").filter(
                has=page.get_by_text(
                    re.compile(rf"^{re.escape(content.company_name)}$", re.I),
                    exact=True,
                )
            ),
            "hiring company chooser",
        )
        companies = chooser.get_by_role(
            "button",
            name=re.compile(rf"^{re.escape(content.company_name)}$", re.I),
        )
        if await companies.count() == 0:
            companies = chooser.get_by_text(
                re.compile(rf"^{re.escape(content.company_name)}$", re.I),
                exact=True,
            )
        visible_companies = [
            companies.nth(index)
            for index in range(await companies.count())
            if await companies.nth(index).is_visible()
        ]
        if not visible_companies:
            raise InvalidTargetError(
                "The exact requested employer is not visible in LinkedIn's hiring chooser."
            )
        selected = False
        for company in visible_companies:
            await self._browser.click_visible_control(page, company)
            exact_job = page.locator(f'[data-job-id="{content.job_id}"]')
            with suppress(PlaywrightTimeoutError):
                await exact_job.first.wait_for(state="visible", timeout=2_000)
            if await exact_job.count() and await exact_job.first.is_visible():
                selected = True
                break
        if not selected:
            raise InvalidTargetError(
                "The exact requested existing job is not visible for the selected employer."
            )
        exact_job = await _unique_visible(
            page.locator(f'[data-job-id="{content.job_id}"]'),
            "exact existing job",
        )
        job_region = exact_job.locator("xpath=ancestor::*[@role='option' or self::button][1]")
        if await job_region.count() == 0:
            job_region = exact_job
        if content.job_title.casefold() not in (await job_region.inner_text()).casefold():
            raise InvalidTargetError(
                "The visible job title no longer matches the requested existing job."
            )
        await self._browser.click_visible_control(page, job_region)
        await self._click_done_or_next(page, "hiring")

    async def _compose_expert_request(
        self,
        page: Page,
        dialog: Locator,
        content: ExpertRequestPostContent,
    ) -> None:
        await self._open_more_option(
            page,
            dialog,
            re.compile(r"^find an expert$", re.I),
            "Find an expert",
        )
        editor = await _unique_visible(
            page.get_by_role("dialog").filter(
                has=page.get_by_text(
                    re.compile(
                        rf"^{re.escape(_EXPERT_CATEGORY_LABELS[content.category])}$",
                        re.I,
                    ),
                    exact=True,
                )
            ),
            "expert-request editor",
        )
        await self._browser.click_visible_control(
            page,
            await _unique_visible(
                editor.get_by_role(
                    "button",
                    name=re.compile(
                        rf"^{re.escape(_EXPERT_CATEGORY_LABELS[content.category])}$",
                        re.I,
                    ),
                ),
                "exact expert category",
            ),
        )
        location = await _unique_visible(
            editor.get_by_role(
                "combobox",
                name=re.compile(r"location", re.I),
            ),
            "expert-request location field",
        )
        await location.fill(content.location_label)
        await self._browser.click_visible_control(
            page,
            await _unique_visible(
                page.get_by_role(
                    "option",
                    name=re.compile(rf"^{re.escape(content.location_label)}$", re.I),
                ),
                "exact expert-request location",
            ),
        )
        description = await _unique_visible(
            editor.locator("textarea[maxlength='750']"),
            "expert-request description field",
        )
        minimum = await description.get_attribute("minlength")
        if minimum not in {None, "25"}:
            raise ParserDriftError(
                "LinkedIn's expert-request description limit no longer matches the contract."
            )
        assert content.text is not None
        await description.fill(content.text)
        await self._click_done_or_next(page, "expert-request")

    async def _open_more_option(
        self,
        page: Page,
        dialog: Locator,
        name: re.Pattern[str],
        description: str,
    ) -> None:
        more = await _unique_visible(
            dialog.get_by_role("button", name=re.compile(r"^more$", re.I)),
            "More publishing-options control",
        )
        await self._browser.click_visible_control(page, more)
        await self._browser.click_visible_control(
            page,
            await _unique_visible(
                page.get_by_role("button", name=name),
                f"{description} option",
            ),
        )

    async def _click_done_or_next(self, page: Page, description: str) -> None:
        visible_dialogs = page.get_by_role("dialog")
        candidates: list[Locator] = []
        for index in range(await visible_dialogs.count()):
            item = visible_dialogs.nth(index)
            if await item.is_visible():
                candidates.append(item)
        if not candidates:
            raise ParserDriftError(f"LinkedIn exposed no visible {description} dialog.")
        controls = candidates[-1].get_by_role(
            "button",
            name=re.compile(r"^(?:done|next)$", re.I),
        )
        await self._browser.click_visible_control(
            page,
            await _unique_visible(controls, f"{description} Done control"),
        )

    @staticmethod
    async def _composer_textbox(dialog: Locator) -> Locator:
        candidates = dialog.get_by_role(
            "textbox",
            name=re.compile(
                r"what do you want to talk about|text editor for creating content",
                re.I,
            ),
        ).or_(dialog.page.locator('[data-test-ql-editor-contenteditable="true"][role="textbox"]'))
        with suppress(PlaywrightTimeoutError):
            await candidates.first.wait_for(state="visible", timeout=3_000)
        return await _unique_visible(
            candidates,
            "post text field",
        )

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
                await _unique_visible(suggestion, "exact @mention suggestion"),
            )
            position = start + len(mention.token)
        await textbox.press_sequentially(text[position:])

    async def _configure_collaborators(
        self,
        page: Page,
        dialog: Locator,
        payload: PostCreatePayload,
    ) -> None:
        control = dialog.get_by_role(
            "button",
            name=re.compile(r"^add collaborators$", re.I),
        )
        with suppress(PlaywrightTimeoutError):
            await control.first.wait_for(state="visible", timeout=2_000)
        await self._browser.click_visible_control(
            page,
            await _unique_visible(
                control,
                "Add collaborators control for this rollout-eligible account",
            ),
        )
        collaborator_dialog = await _unique_visible(
            page.get_by_role("dialog").filter(
                has=page.get_by_role(
                    "combobox",
                    name=re.compile(r"collaborator|search", re.I),
                )
            ),
            "collaborator picker",
        )
        search = await _unique_visible(
            collaborator_dialog.get_by_role(
                "combobox",
                name=re.compile(r"collaborator|search", re.I),
            ),
            "collaborator search field",
        )
        for collaborator in payload.collaborators:
            await search.fill(collaborator.display_name)
            if collaborator.profile_slug is not None:
                result = collaborator_dialog.locator(f'a[href*="/in/{collaborator.profile_slug}/"]')
            else:
                assert collaborator.company_slug is not None
                result = collaborator_dialog.locator(
                    f'a[href*="/company/{collaborator.company_slug}/"]'
                )
            await self._browser.click_visible_control(
                page,
                await _unique_visible(result, "exact collaborator identity"),
            )
        await self._browser.click_visible_control(
            page,
            await _unique_visible(
                collaborator_dialog.get_by_role(
                    "button",
                    name=re.compile(r"^(?:add|done)$", re.I),
                ),
                "collaborator Add control",
            ),
        )

    async def _configure_settings(
        self,
        page: Page,
        dialog: Locator,
        payload: PostCreatePayload,
    ) -> None:
        controls = dialog.get_by_role(
            "button",
            name=re.compile(r"^post settings", re.I),
        ).or_(
            dialog.get_by_role(
                "button",
                name=re.compile(
                    r"\bpost to (?:anyone|connections only|group)\b",
                    re.I,
                ),
            )
        )
        with suppress(PlaywrightTimeoutError):
            await controls.first.wait_for(state="visible", timeout=3_000)
        control = await _unique_visible(
            controls,
            "Post settings control",
        )
        await self._browser.click_visible_control(page, control)
        settings_candidates = page.get_by_role(
            "dialog",
            name=re.compile(r"^post settings$", re.I),
        )
        with suppress(PlaywrightTimeoutError):
            await settings_candidates.first.wait_for(state="visible", timeout=3_000)
        settings = await _unique_visible(
            settings_candidates,
            "Post settings dialog",
        )
        current_comment_control = settings.get_by_role(
            "button",
            name=re.compile(r"^comment control\b", re.I),
        )
        visible_current_controls = [
            current_comment_control.nth(index)
            for index in range(await current_comment_control.count())
            if await current_comment_control.nth(index).is_visible()
        ]
        audience_labels = _CURRENT_AUDIENCE_LABELS if visible_current_controls else _AUDIENCE_LABELS
        audience = await _unique_visible(
            settings.get_by_role("radio", name=audience_labels[payload.audience]),
            "requested audience option",
        )
        if not await audience.is_checked():
            await self._browser.click_visible_control(page, audience)
        if payload.audience is PostAudience.GROUP:
            assert payload.group_target is not None
            await self._select_exact_group_target(
                page,
                payload.group_target.group_id,
                payload.group_target.display_name,
            )
            settings = await _unique_visible(
                settings_candidates,
                "Post settings dialog",
            )
        if visible_current_controls:
            if len(visible_current_controls) != 1:
                raise ParserDriftError("The visible post composer has no unique Comment control.")
            await self._browser.click_visible_control(page, visible_current_controls[0])
            comment_dialog_candidates = page.get_by_role(
                "dialog",
                name=re.compile(r"^comment control$", re.I),
            )
            with suppress(PlaywrightTimeoutError):
                await comment_dialog_candidates.first.wait_for(
                    state="visible",
                    timeout=3_000,
                )
            comment_dialog = await _unique_visible(
                comment_dialog_candidates,
                "Comment control dialog",
            )
            comments = await _unique_visible(
                comment_dialog.get_by_role(
                    "radio",
                    name=_CURRENT_COMMENT_LABELS[payload.comment_control],
                ),
                "requested comment-control option",
            )
            if not await comments.is_checked():
                await self._browser.click_visible_control(page, comments)
                if not await comments.is_checked():
                    raise ParserDriftError(
                        "LinkedIn did not retain the exact requested comment-control state."
                    )
                save = await _unique_visible(
                    comment_dialog.get_by_role(
                        "button",
                        name=re.compile(r"^save$", re.I),
                    ),
                    "Comment control Save control",
                )
                if not await save.is_enabled():
                    raise ParserDriftError(
                        "LinkedIn did not enable the changed Comment control Save action."
                    )
                await self._browser.click_visible_control(page, save)
            else:
                back = await _unique_visible(
                    comment_dialog.get_by_role(
                        "button",
                        name=re.compile(r"^back$", re.I),
                    ),
                    "unchanged Comment control Back control",
                )
                await self._browser.click_visible_control(page, back)
            with suppress(PlaywrightTimeoutError):
                await settings_candidates.first.wait_for(state="visible", timeout=3_000)
            settings = await _unique_visible(
                settings_candidates,
                "Post settings dialog",
            )
        else:
            comments = await _unique_visible(
                settings.get_by_role(
                    "radio",
                    name=_COMMENT_LABELS[payload.comment_control],
                ),
                "requested comment-control option",
            )
            if not await comments.is_checked():
                await self._browser.click_visible_control(page, comments)
        brand = await self._brand_partnership_control(settings)
        if await brand.is_checked() != payload.brand_partnership:
            target = brand
            if (
                await brand.get_attribute("data-artdeco-toggle-button") == "true"
                or not await brand.is_visible()
            ):
                target = brand.locator("xpath=..")
            await self._browser.click_visible_control(page, target)
            if await brand.is_checked() != payload.brand_partnership:
                raise ParserDriftError(
                    "LinkedIn did not retain the exact requested brand-partnership state."
                )
        done = await _unique_visible(
            settings.get_by_role("button", name=re.compile(r"^done$", re.I)),
            "Post settings Done control",
        )
        if await done.is_enabled():
            await self._browser.click_visible_control(page, done)
        else:
            back = await _unique_visible(
                settings.get_by_role("button", name=re.compile(r"^back$", re.I)),
                "unchanged Post settings Back control",
            )
            await self._browser.click_visible_control(page, back)

    @staticmethod
    async def _brand_partnership_control(settings: Locator) -> Locator:
        controls = (
            settings.get_by_role(
                "checkbox",
                name=re.compile(r"brand partnership", re.I),
            )
            .or_(
                settings.get_by_role(
                    "switch",
                    name=re.compile(r"brand partnership", re.I),
                )
            )
            .or_(
                settings.locator(
                    'input[type="checkbox"][aria-label*="Brand partnership" i], '
                    'input[type="checkbox"][data-artdeco-toggle-button="true"]'
                )
            )
        )
        return await _unique_visible_or_hidden(
            controls,
            "Brand partnership toggle",
        )

    async def _select_exact_group_target(
        self,
        page: Page,
        group_id: str,
        display_name: str,
    ) -> None:
        picker = await self._group_picker(page)
        target = await _unique_visible(
            picker.locator(f'a[href*="/groups/{group_id}/"], [data-group-id="{group_id}"]'),
            "exact requested group",
        )
        region = target.locator("xpath=ancestor::*[@role='radio' or @role='option'][1]")
        if await region.count() == 0:
            region = target
        if display_name.casefold() not in (await region.inner_text()).casefold():
            raise InvalidTargetError(
                "The exact visible group name no longer matches the requested target."
            )
        await self._browser.click_visible_control(page, region)
        done = picker.get_by_role(
            "button",
            name=re.compile(r"^(?:done|save)$", re.I),
        )
        if await done.count():
            await self._browser.click_visible_control(
                page,
                await _unique_visible(done, "group picker Done control"),
            )

    @staticmethod
    async def _group_picker(page: Page) -> Locator:
        candidates = page.get_by_role("dialog").filter(
            has=page.locator('a[href*="/groups/"], [data-group-id]')
        )
        with suppress(PlaywrightTimeoutError):
            await candidates.first.wait_for(state="visible", timeout=3_000)
        return await _unique_visible(candidates, "group picker")

    async def _configure_schedule(
        self,
        page: Page,
        dialog: Locator,
        scheduled_at: datetime,
    ) -> None:
        schedule = await _unique_visible(
            dialog.get_by_role("button", name=re.compile(r"^schedule post$", re.I)),
            "Schedule post control",
        )
        await self._browser.click_visible_control(page, schedule)
        schedule_dialog = await _unique_visible(
            page.get_by_role("dialog", name=re.compile(r"schedule post", re.I)),
            "Schedule post dialog",
        )
        local = scheduled_at.astimezone()
        date = await _unique_visible(
            schedule_dialog.get_by_role("textbox", name=re.compile(r"^date$", re.I)),
            "schedule date field",
        )
        time = await _unique_visible(
            schedule_dialog.get_by_role("textbox", name=re.compile(r"^time$", re.I)),
            "schedule time field",
        )
        await date.fill(local.strftime("%Y-%m-%d"))
        await time.fill(local.strftime("%H:%M"))
        next_control = await _unique_visible(
            schedule_dialog.get_by_role("button", name=re.compile(r"^next$", re.I)),
            "schedule Next control",
        )
        await self._browser.click_visible_control(page, next_control)

    @staticmethod
    def _verification_marker(payload: PostCreatePayload) -> str:
        content = payload.content
        if content.text is not None:
            return content.text
        if isinstance(content, PollPostContent):
            return content.question
        if isinstance(content, DocumentPostContent):
            return content.document_title
        if isinstance(content, ImagePostContent):
            alt = next((image.alt_text for image in content.images if image.alt_text), None)
            if alt:
                return alt
        return content.mode.value

    @staticmethod
    async def _matching_post_refs(page: Page, marker: str) -> tuple[str, ...]:
        refs: list[str] = []
        cards = page.locator(
            'article[data-urn*="urn:li:"], [data-urn*="urn:li:activity:"], '
            '[data-urn*="urn:li:share:"], '
            '[data-urn*="urn:li:ugcPost:"]'
        )
        for index in range(min(await cards.count(), 100)):
            card = cards.nth(index)
            if not await card.is_visible():
                continue
            visible = (await card.inner_text()).strip()
            if marker.casefold() not in visible.casefold():
                continue
            values = (
                await card.get_attribute("data-urn"),
                await card.get_attribute("data-id"),
            )
            reference = next(
                (
                    post_reference_from_value(value)
                    for value in values
                    if value is not None and post_reference_from_value(value) is not None
                ),
                None,
            )
            if reference is not None and reference not in refs:
                refs.append(reference)
        return tuple(refs)

    @staticmethod
    def _validate_schedule(scheduled_at: datetime | None) -> None:
        if scheduled_at is None:
            return
        now = datetime.now(UTC)
        value = scheduled_at.astimezone(UTC)
        if value < now + timedelta(minutes=10) or value > now + timedelta(days=92):
            raise InvalidTargetError(
                "A scheduled LinkedIn post must be 10 minutes to 3 months in the future."
            )

    @staticmethod
    async def _result(
        page: Page,
        outcome: ActionOutcome,
        performed: bool | None,
        final_state: str,
        detail: str,
        *,
        source_url: str | None = None,
    ) -> ActionPageResult:
        return ActionPageResult(
            outcome=outcome,
            performed=performed,
            final_state=final_state,
            detail=detail,
            source_url=HttpUrl(source_url or page.url),
            captured_text=await _visible_text(page),
            captured_at=datetime.now(UTC),
        )
