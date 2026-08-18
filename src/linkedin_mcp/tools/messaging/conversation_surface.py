"""Visible conversation mechanics shared by read and send pages."""

from __future__ import annotations

import hashlib
import re
from typing import cast
from urllib.parse import parse_qs, urljoin, urlsplit

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import HttpUrl

from linkedin_mcp.assets import LocalAssetStore
from linkedin_mcp.errors import InvalidTargetError, ParserDriftError
from linkedin_mcp.tools._shared.browser import BrowserManager
from linkedin_mcp.tools._shared.urls import (
    canonical_conversation_url,
    canonical_profile_url,
    conversation_id_from_url,
    profile_slug_from_url,
)
from linkedin_mcp.tools.messaging.conversation.get.models.message_attachment_kind import (
    MessageAttachmentKind,
)
from linkedin_mcp.tools.messaging.conversation.get.models.message_attachment_observation import (
    MessageAttachmentObservation,
)
from linkedin_mcp.tools.messaging.conversation.get.models.message_direction import MessageDirection
from linkedin_mcp.tools.messaging.conversation.get.models.message_observation import (
    MessageObservation,
)
from linkedin_mcp.tools.messaging.search.page import ConversationSearchPage

_COMPOSER_SELECTOR = '[contenteditable]:not([contenteditable="false"]), textarea'


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _visible_name_matches(visible_name: str, expected_name: str) -> bool:
    visible = visible_name.casefold()
    expected = expected_name.casefold()
    if visible == expected:
        return True
    if not visible.startswith(expected):
        return False
    suffix = visible[len(expected) :]
    return bool(suffix) and not suffix[0].isalnum()


async def _visible_text(locator: Locator) -> str:
    if await locator.count() == 0:
        raise ParserDriftError("LinkedIn messaging returned no visible container.")
    value = (await locator.first.inner_text()).strip()
    if not value:
        raise ParserDriftError("LinkedIn messaging returned no visible text.")
    return value


def _message_ref(
    target: str,
    direction: MessageDirection,
    sender: str | None,
    sent_at: str | None,
    text: str | None,
    attachments: tuple[MessageAttachmentObservation, ...],
) -> str:
    del target
    attachment_identity = "\x1e".join(
        "\x1d".join(
            (
                attachment.kind.value,
                attachment.name or "",
                attachment.accessible_label or "",
                str(attachment.resource_url or ""),
            )
        )
        for attachment in attachments
    )
    value = "\x1f".join(
        (direction.value, sender or "", sent_at or "", text or "", attachment_identity)
    )
    return f"message:{hashlib.sha256(value.encode()).hexdigest()[:24]}"


def _direction(
    item: dict[str, object],
    *,
    participant_name: str | None = None,
    is_group: bool = False,
    previous_direction: MessageDirection | None = None,
) -> MessageDirection:
    indicators = " ".join(
        value.casefold()
        for key in ("class_name", "direction", "aria_label")
        if isinstance((value := item.get(key)), str)
    )
    sender = item.get("sender")
    if "system" in indicators:
        return MessageDirection.SYSTEM
    if "outgoing" in indicators or "you sent" in indicators or "align-self-flex-end" in indicators:
        return MessageDirection.OUTGOING
    if "incoming" in indicators or "msg-s-event-listitem--other" in indicators:
        return MessageDirection.INCOMING
    if isinstance(sender, str) and sender:
        if sender.casefold() == "you":
            return MessageDirection.OUTGOING
        if participant_name is not None and not is_group:
            if _visible_name_matches(sender, participant_name):
                return MessageDirection.INCOMING
            return MessageDirection.OUTGOING
    if previous_direction is MessageDirection.INCOMING:
        return MessageDirection.INCOMING
    if previous_direction is MessageDirection.OUTGOING:
        return MessageDirection.OUTGOING
    return MessageDirection.INCOMING


def _resolved_directions(
    items: list[dict[str, object]],
    *,
    participant_name: str | None,
    is_group: bool,
) -> list[MessageDirection]:
    directions: list[MessageDirection] = []
    previous_direction: MessageDirection | None = None
    for item in items:
        direction = _direction(
            item,
            participant_name=participant_name,
            is_group=is_group,
            previous_direction=previous_direction,
        )
        directions.append(direction)
        if direction is not MessageDirection.SYSTEM:
            previous_direction = direction
    return directions


def _attachment_kind(raw: str) -> MessageAttachmentKind:
    value = raw.casefold()
    if "gif" in value:
        return MessageAttachmentKind.GIF
    if (
        "image preview" in value
        or value in {"img", "image", "photo", "picture"}
        or any(
            extension in value
            for extension in (
                ".bmp",
                ".gif",
                ".heic",
                ".heif",
                ".jpeg",
                ".jpg",
                ".png",
                ".tif",
                ".tiff",
                ".webp",
            )
        )
    ):
        return MessageAttachmentKind.IMAGE
    if value in {"video", "mov", "mp4"} or any(
        extension in value for extension in (".mov", ".mp4")
    ):
        return MessageAttachmentKind.VIDEO
    return MessageAttachmentKind.DOCUMENT


def _message_attachments(
    item: dict[str, object],
    *,
    page_url: str,
) -> tuple[MessageAttachmentObservation, ...]:
    raw_attachments = item.get("attachments")
    if not isinstance(raw_attachments, list):
        return ()
    attachments: list[MessageAttachmentObservation] = []
    for raw_item in cast(list[object], raw_attachments):
        if not isinstance(raw_item, dict):
            continue
        raw = cast(dict[str, object], raw_item)
        raw_kind = raw.get("kind")
        raw_name = raw.get("name")
        raw_label = raw.get("accessible_label")
        raw_url = raw.get("resource_url")
        raw_visible = raw.get("visible_text")
        name = raw_name if isinstance(raw_name, str) and raw_name else None
        label = raw_label if isinstance(raw_label, str) and raw_label else None
        visible = raw_visible if isinstance(raw_visible, str) and raw_visible else label or name
        if not visible or (name is None and label is None and not isinstance(raw_url, str)):
            continue
        resource_url: HttpUrl | None = None
        if isinstance(raw_url, str) and raw_url:
            resolved = urljoin(page_url, raw_url)
            if resolved.startswith(("https://", "http://")):
                resource_url = HttpUrl(resolved)
        kind_identity = " ".join(
            value
            for value in (
                raw_kind if isinstance(raw_kind, str) else "",
                name or "",
                label or "",
                raw_url if isinstance(raw_url, str) else "",
            )
            if value
        )
        attachment = MessageAttachmentObservation(
            kind=_attachment_kind(kind_identity),
            name=name,
            accessible_label=label,
            resource_url=resource_url,
            visible_text=visible,
        )
        if attachment in attachments:
            continue
        attachments.append(attachment)
    return tuple(attachments)


class ConversationSurface:
    """Shared visible-surface mechanics for ConversationSurface."""

    def __init__(
        self,
        browser: BrowserManager,
        asset_store: LocalAssetStore | None = None,
        *,
        conversation_search: ConversationSearchPage | None = None,
        max_history_rounds: int = 100,
    ) -> None:
        if max_history_rounds < 1:
            raise ValueError("Conversation history traversal must be bounded.")
        self._browser = browser
        self._assets = asset_store
        self._conversation_search = conversation_search
        self._max_history_rounds = max_history_rounds

    async def _open(
        self,
        page: Page,
        *,
        profile_slug: str | None,
        conversation_id: str | None,
        conversation_ref: str | None,
    ) -> tuple[Page, Locator, str | None, str, bool]:
        expected_name: str | None = None
        selected_profile_slug = profile_slug
        selected_is_group = False
        if conversation_id:
            await self._browser.navigate(page, canonical_conversation_url(conversation_id))
        elif profile_slug:
            await self._browser.navigate(page, canonical_profile_url(profile_slug))
            main = page.locator("main")
            introduction, expected_name = await self._profile_introduction(main)
            top_text = "\n".join(_lines(await _visible_text(introduction))[:30])
            if not re.search(r"\b1st\b", top_text):
                raise InvalidTargetError(
                    "Standard messaging is limited to a visible first-degree connection."
                )
            page, root = await self._open_profile_message_surface(
                page,
                profile_slug=profile_slug,
                profile_name=expected_name,
                profile_main=introduction,
            )
            return page, root, profile_slug, expected_name, False
        elif conversation_ref:
            if self._conversation_search is None:
                raise InvalidTargetError(
                    "Conversation references require the process-local message-search index."
                )
            selected, _ = await self._conversation_search.open_reference(
                page,
                conversation_ref,
            )
            expected_name = selected.participant_name
            selected_profile_slug = selected.participant_profile_slug
            selected_is_group = selected.is_group
        else:
            raise InvalidTargetError("A conversation target is required.")

        root = await self._conversation_root(page)
        root_text = await _visible_text(root)
        if (
            re.search(r"\binmail\b", root_text, re.I)
            and await root.get_by_role("textbox", name=re.compile(r"subject", re.I)).count()
        ):
            raise InvalidTargetError("Paid InMail is outside this message capability.")

        profile_links = root.locator('a[href*="/in/"]')
        slugs: list[str] = []
        names: list[str] = []
        for index in range(min(await profile_links.count(), 20)):
            link = profile_links.nth(index)
            href = await link.get_attribute("href")
            slug = (
                profile_slug_from_url(urljoin("https://www.linkedin.com", href)) if href else None
            )
            text = _lines((await link.inner_text()).strip())
            if slug and slug not in slugs:
                slugs.append(slug)
                if text:
                    names.append(text[0])
        resolved_slug = selected_profile_slug or (slugs[0] if len(slugs) == 1 else None)
        is_group = selected_is_group or len(slugs) > 1
        name = expected_name or (names[0] if names else None)
        if name is None:
            headings = root.get_by_role("heading")
            for index in range(min(await headings.count(), 10)):
                value = _lines((await headings.nth(index).inner_text()).strip())
                if value and value[0].casefold() != "messaging":
                    name = value[0]
                    break
        if name is None:
            raise ParserDriftError("The visible conversation has no participant identity.")
        return page, root, resolved_slug, name, is_group

    @staticmethod
    async def _profile_introduction(main: Locator) -> tuple[Locator, str]:
        headings = main.get_by_role("heading", level=1)
        if await headings.count() == 0:
            headings = main.get_by_role("heading")
        name_heading: Locator | None = None
        name: str | None = None
        for index in range(min(await headings.count(), 10)):
            heading = headings.nth(index)
            if not await heading.is_visible():
                continue
            lines = _lines((await heading.inner_text()).strip())
            if lines:
                name_heading = heading
                name = lines[0]
                break
        if name_heading is None or name is None:
            raise ParserDriftError("The exact profile has no visible member heading.")
        introduction = name_heading.locator("..")
        sections = main.locator("section")
        for index in range(min(await sections.count(), 100)):
            candidate = sections.nth(index)
            exact_name = candidate.get_by_role(
                "heading",
                name=re.compile(rf"^{re.escape(name)}$"),
            )
            if await exact_name.count():
                introduction = candidate
                break
        return introduction, name

    async def _open_profile_message_surface(
        self,
        page: Page,
        *,
        profile_slug: str,
        profile_name: str,
        profile_main: Locator,
    ) -> tuple[Page, Locator]:
        selected: Locator | None = None
        action_area = profile_main
        for _ in range(12):
            candidates = await self._visible_profile_message_controls(
                action_area,
                profile_name=profile_name,
            )
            if len(candidates) > 1:
                raise InvalidTargetError(
                    "The exact profile action area has multiple visible standard Message actions."
                )
            if len(candidates) == 1:
                selected = candidates[0]
                break
            parent = action_area.locator("..")
            if await parent.count() != 1:
                break
            tag_name = await parent.evaluate("element => element.tagName.toLowerCase()")
            if tag_name in {"main", "body", "html"}:
                break
            action_area = parent
        if selected is None:
            candidates = await self._visible_profile_message_controls(
                page.locator("main"),
                profile_name=profile_name,
            )
            selected = await self._nearest_profile_message_control(
                candidates,
                anchor=profile_main,
            )
        if selected is None:
            raise InvalidTargetError(
                "The exact first-degree profile has no visible standard Message action."
            )
        control_diagnostic = await self._profile_message_control_diagnostic(
            selected,
            anchor=profile_main,
        )
        href = await selected.get_attribute("href")
        if href and "/messaging/" in href.casefold():
            await self._browser.navigate(
                page,
                urljoin(page.url, href),
            )
        else:
            await self._browser.click_visible_control(page, selected)
        for _ in range(40):
            surfaces: list[tuple[Page, Locator]] = []
            overlays = await self._profile_message_overlays(
                page,
                profile_name=profile_name,
            )
            if len(overlays) > 1:
                raise InvalidTargetError(
                    "Multiple exact-recipient message panes make the target ambiguous."
                )
            if len(overlays) == 1:
                surfaces.append((page, overlays[0]))
            else:
                thread = await self._profile_message_thread(
                    page,
                    profile_slug=profile_slug,
                    profile_name=profile_name,
                )
                if thread is not None:
                    surfaces.append((page, thread))
            if len(surfaces) > 1:
                raise InvalidTargetError(
                    "Multiple exact-recipient conversation surfaces make the target ambiguous."
                )
            if len(surfaces) == 1:
                surface_page, root = surfaces[0]
                composer = await self._composer(root)
                if await self._composer_value(composer):
                    raise InvalidTargetError(
                        "The exact profile message surface already contains unsent text."
                    )
                return surface_page, root
            await page.wait_for_timeout(250)
        diagnostic = await self._profile_message_surface_diagnostic(
            page,
            control_diagnostic=control_diagnostic,
        )
        raise ParserDriftError(
            "The profile Message button did not open one exact-recipient conversation "
            f"surface ({diagnostic})."
        )

    @staticmethod
    async def _visible_profile_message_controls(
        root: Locator,
        *,
        profile_name: str,
    ) -> list[Locator]:
        controls = root.locator('button, a, [role="button"], [role="link"]')
        candidates: list[Locator] = []
        for index in range(await controls.count()):
            control = controls.nth(index)
            if not await control.is_visible():
                continue
            label = (
                await control.get_attribute("aria-label") or await control.inner_text()
            ).strip()
            if not re.fullmatch(r"message(?:\s+.+)?", label, re.I):
                continue
            suffix = re.sub(r"^message\s*", "", label, flags=re.I)
            if not suffix or _visible_name_matches(suffix, profile_name):
                candidates.append(control)
        return candidates

    @staticmethod
    async def _nearest_profile_message_control(
        candidates: list[Locator],
        *,
        anchor: Locator,
    ) -> Locator | None:
        if not candidates:
            return None
        anchor_box = await anchor.bounding_box()
        if anchor_box is None:
            return candidates[0] if len(candidates) == 1 else None
        anchor_x = anchor_box["x"] + anchor_box["width"] / 2
        anchor_y = anchor_box["y"] + anchor_box["height"] / 2
        ranked: list[tuple[float, int, Locator]] = []
        for index, candidate in enumerate(candidates):
            box = await candidate.bounding_box()
            if box is None:
                continue
            candidate_x = box["x"] + box["width"] / 2
            candidate_y = box["y"] + box["height"] / 2
            distance = (candidate_x - anchor_x) ** 2 + (candidate_y - anchor_y) ** 2
            ranked.append((distance, index, candidate))
        if not ranked:
            return None
        ranked.sort(key=lambda value: (value[0], value[1]))
        if len(ranked) > 1 and abs(ranked[0][0] - ranked[1][0]) < 1:
            raise InvalidTargetError(
                "The exact profile has visually ambiguous standard Message actions."
            )
        return ranked[0][2]

    @staticmethod
    async def _profile_message_control_diagnostic(
        control: Locator,
        *,
        anchor: Locator,
    ) -> str:
        tag_name = await control.evaluate("element => element.tagName.toLowerCase()")
        label = (await control.get_attribute("aria-label") or await control.inner_text()).strip()
        href = await control.get_attribute("href")
        href_kind = (
            "none"
            if href is None
            else ("messaging" if "/messaging" in href.casefold() else "other")
        )
        distance = "unknown"
        control_box = await control.bounding_box()
        anchor_box = await anchor.bounding_box()
        if control_box is not None and anchor_box is not None:
            control_y = control_box["y"] + control_box["height"] / 2
            anchor_y = anchor_box["y"] + anchor_box["height"] / 2
            distance = str(round(abs(control_y - anchor_y)))
        normalized_label = re.sub(r"\s+", " ", label)[:80]
        return f"{tag_name}:{normalized_label}:href_{href_kind}:vertical_distance_{distance}"

    @staticmethod
    async def _profile_message_overlays(
        page: Page,
        *,
        profile_name: str,
    ) -> list[Locator]:
        composers = page.locator(_COMPOSER_SELECTOR)
        candidates: list[Locator] = []
        for index in range(await composers.count()):
            composer = composers.nth(index)
            if not await composer.is_visible():
                continue
            ancestor = composer
            for _ in range(24):
                ancestor = ancestor.locator("..")
                if await ancestor.count() != 1:
                    break
                tag_name = await ancestor.evaluate("element => element.tagName.toLowerCase()")
                if tag_name in {"main", "body", "html"}:
                    break
                nested_composers = ancestor.locator(_COMPOSER_SELECTOR)
                visible_composers = 0
                for nested_index in range(await nested_composers.count()):
                    if await nested_composers.nth(nested_index).is_visible():
                        visible_composers += 1
                if visible_composers != 1:
                    continue
                exact_compose_recipient = ConversationSurface._exact_profile_compose_url(
                    page.url
                ) and await ConversationSurface._has_exact_single_recipient_pill(
                    ancestor,
                    profile_name=profile_name,
                )
                visible_lines = _lines((await ancestor.inner_text()).strip())
                if await ancestor.get_by_role("combobox").count() and not exact_compose_recipient:
                    continue
                if not exact_compose_recipient and not any(
                    _visible_name_matches(line, profile_name) for line in visible_lines
                ):
                    continue
                candidates.append(ancestor)
                break
        return candidates

    @staticmethod
    def _exact_profile_compose_url(url: str) -> bool:
        parsed = urlsplit(url)
        if parsed.path.rstrip("/") != "/messaging/compose":
            return False
        query = parse_qs(parsed.query)
        recipients = query.get("recipient", [])
        profile_urns = query.get("profileUrn", [])
        if len(recipients) != 1 or len(profile_urns) != 1:
            return False
        recipient = recipients[0]
        return bool(recipient) and profile_urns[0] == f"urn:li:fsd_profile:{recipient}"

    @staticmethod
    async def _has_exact_single_recipient_pill(
        root: Locator,
        *,
        profile_name: str,
    ) -> bool:
        recipient_pills = root.locator(
            'button[aria-label^="Remove "], [role="button"][aria-label^="Remove "]'
        )
        visible_labels: list[str] = []
        for index in range(await recipient_pills.count()):
            pill = recipient_pills.nth(index)
            if not await pill.is_visible():
                continue
            label = (await pill.get_attribute("aria-label") or "").strip()
            if label:
                visible_labels.append(label)
        if len(visible_labels) != 1:
            return False
        return bool(
            re.fullmatch(
                rf"Remove\s+{re.escape(profile_name)}"
                r"(?:\s+from(?:\s+the)?\s+recipients?)?",
                visible_labels[0],
                re.I,
            )
        )

    @classmethod
    async def _profile_message_thread(
        cls,
        page: Page,
        *,
        profile_slug: str,
        profile_name: str,
    ) -> Locator | None:
        if conversation_id_from_url(page.url) is None:
            return None
        main = page.locator("main").first
        if await main.count() != 1 or not await main.is_visible():
            return None
        if await main.get_by_role("combobox").count():
            return None
        try:
            composer = await cls._composer(main)
        except InvalidTargetError:
            return None
        if not await composer.is_visible():
            return None

        matching_profile_link = False
        profile_links = main.locator('a[href*="/in/"]')
        for index in range(min(await profile_links.count(), 30)):
            link = profile_links.nth(index)
            if not await link.is_visible():
                continue
            lines = _lines((await link.inner_text()).strip())
            if not any(_visible_name_matches(line, profile_name) for line in lines):
                continue
            href = await link.get_attribute("href")
            visible_slug = (
                profile_slug_from_url(urljoin("https://www.linkedin.com", href)) if href else None
            )
            if visible_slug != profile_slug:
                return None
            matching_profile_link = True

        matching_heading = False
        headings = main.get_by_role("heading")
        for index in range(min(await headings.count(), 20)):
            heading = headings.nth(index)
            if not await heading.is_visible():
                continue
            lines = _lines((await heading.inner_text()).strip())
            if any(_visible_name_matches(line, profile_name) for line in lines):
                matching_heading = True
                break
        if not matching_profile_link and not matching_heading:
            return None
        return main

    @staticmethod
    async def _profile_message_surface_diagnostic(
        page: Page,
        *,
        control_diagnostic: str,
    ) -> str:
        surface = (
            "conversation_thread" if conversation_id_from_url(page.url) is not None else "profile"
        )
        composers = page.locator(_COMPOSER_SELECTOR)
        visible_composers = 0
        for index in range(await composers.count()):
            if await composers.nth(index).is_visible():
                visible_composers += 1
        dialogs = page.get_by_role("dialog")
        visible_dialogs = 0
        for index in range(await dialogs.count()):
            if await dialogs.nth(index).is_visible():
                visible_dialogs += 1
        return (
            f"surface={surface}, visible_composers={visible_composers}, "
            f"visible_dialogs={visible_dialogs}, pages={len(page.context.pages)}, "
            f"selected_control={control_diagnostic}"
        )

    @staticmethod
    async def _conversation_root(page: Page) -> Locator:
        dialogs = page.get_by_role("dialog")
        for index in range(await dialogs.count()):
            dialog = dialogs.nth(index)
            if await dialog.locator(_COMPOSER_SELECTOR).count():
                return dialog
        main = page.locator("main")
        try:
            await main.first.wait_for(state="visible", timeout=5_000)
        except PlaywrightTimeoutError as error:
            raise ParserDriftError("LinkedIn conversation did not render.") from error
        return main

    @staticmethod
    async def _composer(root: Locator) -> Locator:
        composer = root.get_by_role(
            "textbox",
            name=re.compile(r"^(?:write a )?message$", re.I),
        )
        if await composer.count() == 0:
            composer = root.locator(
                '[contenteditable]:not([contenteditable="false"])[role="textbox"]'
            )
        if await composer.count() == 0:
            composer = root.locator('[contenteditable]:not([contenteditable="false"])')
        if await composer.count() == 0:
            composer = root.locator("textarea")
        if await composer.count() != 1:
            raise InvalidTargetError(
                "The conversation has no unique visible plain-text message composer."
            )
        return composer

    @staticmethod
    def _snapshot_messages(
        raw_messages: list[dict[str, object]],
        *,
        target: str,
        page_url: str,
        participant_name: str,
        is_group: bool,
    ) -> tuple[MessageObservation, ...]:
        messages: list[MessageObservation] = []
        directions = _resolved_directions(
            raw_messages,
            participant_name=participant_name,
            is_group=is_group,
        )
        previous_sender: str | None = None
        previous_time: str | None = None
        previous_direction: MessageDirection | None = None
        for raw, direction in zip(raw_messages, directions, strict=True):
            raw_text = raw.get("text")
            raw_visible = raw.get("visible_text")
            text = raw_text if isinstance(raw_text, str) and raw_text else None
            attachments = _message_attachments(raw, page_url=page_url)
            if not isinstance(raw_visible, str):
                continue
            message_visible = raw_visible.strip()
            for attachment in attachments:
                if attachment.visible_text not in message_visible:
                    message_visible = f"{message_visible}\n{attachment.visible_text}".strip()
            if (text is None and not attachments) or not message_visible:
                continue
            raw_sender = raw.get("sender")
            sender = (
                raw_sender
                if isinstance(raw_sender, str) and raw_sender
                else (previous_sender if previous_direction is direction else None)
            )
            raw_time = raw.get("time")
            sent_at = (
                raw_time
                if isinstance(raw_time, str) and raw_time
                else (previous_time if previous_direction is direction else None)
            )
            raw_reply_sender = raw.get("reply_sender")
            reply_sender = (
                raw_reply_sender if isinstance(raw_reply_sender, str) and raw_reply_sender else None
            )
            raw_reply_text = raw.get("reply_text")
            reply_text = (
                raw_reply_text if isinstance(raw_reply_text, str) and raw_reply_text else None
            )
            raw_reactions = raw.get("reaction_summaries")
            reaction_summaries = tuple(
                dict.fromkeys(
                    value
                    for value in (
                        cast(list[object], raw_reactions) if isinstance(raw_reactions, list) else []
                    )
                    if isinstance(value, str) and value
                )
            )[:20]
            messages.append(
                MessageObservation(
                    message_ref=_message_ref(
                        target,
                        direction,
                        sender,
                        sent_at,
                        text,
                        attachments,
                    ),
                    direction=direction,
                    sender_name=sender,
                    sent_at_text=sent_at,
                    text=text,
                    attachments=attachments,
                    edited=raw.get("edited") is True,
                    reply_to_sender_name=reply_sender,
                    reply_to_text=reply_text,
                    reaction_summaries=reaction_summaries,
                    visible_text=message_visible,
                )
            )
            previous_sender = sender
            previous_time = sent_at
            previous_direction = direction
        return tuple(messages)

    @staticmethod
    async def _composer_value(composer: Locator) -> str:
        tag_name = cast(str, await composer.evaluate("element => element.tagName"))
        if tag_name in {"INPUT", "TEXTAREA"}:
            return (await composer.input_value()).strip()
        return (await composer.inner_text()).strip()
