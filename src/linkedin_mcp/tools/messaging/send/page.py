"""Visible LinkedIn page implementation for `linkedin_mcp.tools.messaging.send.page`."""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urljoin

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import HttpUrl

from linkedin_mcp.errors import InvalidTargetError, ParserDriftError
from linkedin_mcp.tools._shared.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutcome,
    ActionPageResult,
    ActionTarget,
    MessageSendPayload,
)
from linkedin_mcp.tools._shared.collections import (
    CollectionSettleOutcome,
    CollectionSettleResult,
    dispatch_bubbling_wheel,
    wait_for_collection_interaction,
)
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
from linkedin_mcp.tools.messaging.conversation_surface import ConversationSurface
from linkedin_mcp.tools.messaging.send.models.message_gif_input import MessageGifInput
from linkedin_mcp.tools.messaging.send.models.message_send_input import MessageSendInput

_SCROLL_PROGRESS_POLL_ATTEMPTS = 8

_SCROLL_PROGRESS_POLL_DELAY_MS = 250

_HISTORY_END_CONFIRMATION_ROUNDS = 5


@dataclass(frozen=True, slots=True)
class _ReplyTarget:
    sender_name: str | None
    text: str | None
    attachment_identities: tuple[str, ...]


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


async def _raw_messages(root: Locator) -> list[dict[str, object]]:
    raw = await root.locator("li").evaluate_all(
        """
        elements => elements
          .filter(element => element.getClientRects().length > 0)
          .filter(element => (
            element.matches('[class*="msg-s-event-listitem"]') ||
            element.querySelector(
              '[class*="msg-s-event-listitem"],' +
              '[class*="event-listitem__body"],[data-test-message-body],' +
              '[data-test-message-attachment],[class*="event-listitem__attachment"]'
            )
          ))
          .slice(-1000)
          .map(element => {
            const body = element.querySelector(
              '[class*="event-listitem__body"],[data-test-message-body]'
            );
            const sender = element.querySelector(
              '[class*="message-group__name"],[data-test-message-sender]'
            );
            const reply = element.querySelector(
              '[data-test-message-reply],[class*="reply-to"],' +
              '[class*="quoted-message"]'
            );
            const replySender = reply?.querySelector(
              '[class*="sender"],[class*="name"],[data-test-reply-sender]'
            );
            const replyBody = reply?.querySelector(
              '[class*="body"],[class*="text"],[data-test-reply-body]'
            );
            const attachments = Array.from(element.querySelectorAll(
              '[data-test-message-attachment],[class*="message-attachment"],' +
              '[class*="event-listitem__attachment"]'
            )).slice(0, 20).map(attachment => {
              const media = attachment.matches("img,video,a")
                ? attachment
                : attachment.querySelector("img,video,a");
              const rawKind = (
                attachment.getAttribute("data-kind") ||
                media?.getAttribute("data-kind") ||
                media?.tagName ||
                ""
              ).toLowerCase();
              const name = (
                attachment.getAttribute("data-file-name") ||
                media?.getAttribute("download") ||
                attachment.innerText ||
                media?.getAttribute("alt") ||
                ""
              ).trim();
              const accessibleLabel = (
                attachment.getAttribute("aria-label") ||
                media?.getAttribute("aria-label") ||
                media?.getAttribute("alt") ||
                ""
              ).trim();
              return {
                kind: rawKind,
                name: name || null,
                accessible_label: accessibleLabel || null,
                resource_url: (
                  media?.getAttribute("href") ||
                  media?.getAttribute("src") ||
                  null
                ),
                visible_text: (
                  attachment.innerText ||
                  accessibleLabel ||
                  name
                ).trim()
              };
            });
            const reactionSummaries = Array.from(element.querySelectorAll(
              '[data-test-message-reactions],[class*="reactions-summary"],' +
              '[class*="reaction-count"]'
            )).filter(node => node.getClientRects().length > 0)
              .map(node => (
                node.getAttribute("aria-label") ||
                node.innerText ||
                ""
              ).trim())
              .filter(Boolean)
              .slice(0, 20);
            const descendantClasses = Array.from(element.querySelectorAll("*"))
              .flatMap(node => String(node.className || "").split(/\\s+/))
              .filter(Boolean)
              .join(" ");
            const visibleLines = (element.innerText || "")
              .split(/\\n/)
              .map(value => value.trim())
              .filter(Boolean);
            return {
              visible_text: element.innerText?.trim() ?? "",
              text: body?.innerText?.trim() ?? null,
              attachments,
              sender: sender?.innerText?.trim() ?? null,
              time: element.querySelector("time")?.innerText?.trim() ?? null,
              class_name: [
                element.className?.toString() ?? "",
                descendantClasses
              ].join(" "),
              direction: element.getAttribute("data-direction"),
              aria_label: element.getAttribute("aria-label"),
              edited: visibleLines.some(line => /^edited$/i.test(line)),
              reply_sender: replySender?.innerText?.trim() ?? null,
              reply_text: replyBody?.innerText?.trim() ?? (
                reply?.innerText?.trim() || null
              ),
              reaction_summaries: reactionSummaries
            };
          })
        """
    )
    return [
        cast(dict[str, object], item) for item in cast(list[object], raw) if isinstance(item, dict)
    ]


async def _history_scroller(root: Locator) -> Locator | None:
    candidates = root.locator(
        '[class*="msg-s-message-list"][class*="scrollable"],[aria-label*="message history" i]'
    )
    visible: list[Locator] = []
    for index in range(await candidates.count()):
        candidate = candidates.nth(index)
        if not await candidate.is_visible():
            continue
        state = cast(
            dict[str, object],
            await candidate.evaluate(
                """
                element => ({
                  scrollHeight: element.scrollHeight,
                  clientHeight: element.clientHeight
                })
                """
            ),
        )
        if state.get("scrollHeight") != state.get("clientHeight"):
            visible.append(candidate)
    if len(visible) > 1:
        raise ParserDriftError(
            "LinkedIn Messaging exposed multiple visible conversation-history scrollers."
        )
    return visible[0] if visible else None


async def _history_signature(root: Locator) -> tuple[str, ...]:
    identities: list[str] = []
    for item in await _raw_messages(root):
        values = tuple(
            value
            for key in ("visible_text", "sender", "time", "class_name")
            if isinstance((value := item.get(key)), str) and value
        )
        if values:
            identities.append(hashlib.sha256("\x1f".join(values).encode()).hexdigest())
    scroller = await _history_scroller(root)
    if scroller is not None:
        state = cast(
            dict[str, object],
            await scroller.evaluate(
                """
                element => ({
                  scrollTop: Math.round(element.scrollTop),
                  scrollHeight: element.scrollHeight,
                  clientHeight: element.clientHeight
                })
                """
            ),
        )
        identities.append(
            "scroll:"
            + ":".join(
                str(state.get(key, "")) for key in ("scrollTop", "scrollHeight", "clientHeight")
            )
        )
    return tuple(identities)


async def _history_at_physical_start(root: Locator) -> bool:
    scroller = await _history_scroller(root)
    if scroller is None:
        return True
    state = cast(
        dict[str, object],
        await scroller.evaluate(
            """
            element => ({
              scrollTop: element.scrollTop,
              scrollHeight: element.scrollHeight,
              clientHeight: element.clientHeight,
              flexDirection: getComputedStyle(element).flexDirection
            })
            """
        ),
    )
    scroll_top = state.get("scrollTop")
    scroll_height = state.get("scrollHeight")
    client_height = state.get("clientHeight")
    flex_direction = state.get("flexDirection")
    if not (
        isinstance(scroll_top, int | float)
        and isinstance(scroll_height, int | float)
        and isinstance(client_height, int | float)
    ):
        raise ParserDriftError("LinkedIn's conversation-history scroll state is invalid.")
    boundary = max(0.0, scroll_height - client_height)
    if flex_direction == "column-reverse":
        return abs(scroll_top) >= boundary - 2
    return scroll_top <= 2


def _history_has_explicit_start(visible_text: str) -> bool:
    return any(
        re.fullmatch(
            r"(?:you(?:'|\N{RIGHT SINGLE QUOTATION MARK})?ve reached the beginning|"
            r"beginning of (?:the )?conversation|no older messages)",
            line,
            re.I,
        )
        for line in _lines(visible_text)
    )


async def _settle_history_scroll(
    page: Page,
    root: Locator,
) -> CollectionSettleResult:
    baseline = await _history_signature(root)
    scroller = await _history_scroller(root)
    if scroller is None:
        return CollectionSettleResult(
            outcome=CollectionSettleOutcome.EXPLICIT_END,
            signature=baseline,
        )
    box = await scroller.bounding_box()
    if box is None:
        raise ParserDriftError("LinkedIn's conversation-history scroller is not visible.")
    delivery_attempt = 0

    async def scroll() -> None:
        nonlocal delivery_attempt
        delivery_attempt += 1
        await scroller.hover(
            position={
                "x": box["width"] / 2,
                "y": min(20, box["height"] / 2),
            }
        )
        await page.mouse.wheel(0, -1_800)
        await scroller.evaluate(
            """
            element => {
              const boundary = Math.max(0, element.scrollHeight - element.clientHeight);
              element.scrollTop = getComputedStyle(element).flexDirection === "column-reverse"
                ? -boundary
                : 0;
            }
            """
        )
        if delivery_attempt > 1:
            await dispatch_bubbling_wheel(scroller, delta_y=-1_800)

    async def explicit_start() -> bool:
        return _history_has_explicit_start(await _visible_text(root))

    return await wait_for_collection_interaction(
        page,
        baseline=baseline,
        interact=scroll,
        read_signature=lambda: _history_signature(root),
        read_explicit_end=explicit_start,
        attempts=_SCROLL_PROGRESS_POLL_ATTEMPTS,
        delay_ms=_SCROLL_PROGRESS_POLL_DELAY_MS,
    )


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


class MessageSendPage(ConversationSurface):
    async def inspect_message(
        self,
        request: MessageSendInput,
    ) -> ActionInspection:
        async with self._browser.page() as page:
            page, root, profile_slug, name, is_group = await self._open(
                page,
                profile_slug=request.profile_slug,
                conversation_id=request.conversation_id,
                conversation_ref=request.conversation_ref,
            )
            if is_group:
                raise InvalidTargetError("Group conversations are outside this message capability.")
            if profile_slug is None:
                raise InvalidTargetError(
                    "A one-to-one message requires an unambiguous visible profile identity."
                )
            await self._composer(root)
            if request.reply_to_message_ref is not None:
                await self._reply_control(
                    page,
                    root,
                    request.reply_to_message_ref,
                    participant_name=name,
                )
            if request.attachments:
                await self._validate_attachment_controls(root, request)
            if request.gif is not None:
                await self._gif_result(page, root, request.gif)
            visible_text = await _visible_text(root)
            conversation_id = conversation_id_from_url(page.url) or request.conversation_id
            source_url = (
                canonical_conversation_url(conversation_id)
                if conversation_id
                else canonical_profile_url(profile_slug)
            )
            return ActionInspection(
                target=ActionTarget(
                    profile_slug=profile_slug,
                    profile_url=HttpUrl(canonical_profile_url(profile_slug)),
                    display_name=name,
                    conversation_id=conversation_id,
                ),
                current_state=(
                    "message_reply_gif_ready"
                    if request.gif is not None and request.reply_to_message_ref is not None
                    else (
                        "message_gif_ready"
                        if request.gif is not None
                        else (
                            "message_reply_attachment_composer_available"
                            if request.attachments and request.reply_to_message_ref is not None
                            else (
                                "message_attachment_composer_available"
                                if request.attachments
                                else (
                                    "message_reply_composer_available"
                                    if request.reply_to_message_ref is not None
                                    else "message_composer_available"
                                )
                            )
                        )
                    )
                ),
                source_url=HttpUrl(source_url),
                captured_text=visible_text,
                captured_at=datetime.now(UTC),
            )

    async def perform_message(self, command: ActionCommand) -> ActionPageResult:
        if not isinstance(command.payload, MessageSendPayload):
            raise InvalidTargetError("The message action payload is invalid.")
        payload = command.payload
        async with self._browser.page() as page:
            page, root, profile_slug, name, is_group = await self._open(
                page,
                profile_slug=(
                    None if command.target.conversation_id else command.target.profile_slug
                ),
                conversation_id=command.target.conversation_id,
                conversation_ref=None,
            )
            mismatch = self._inspected_target_mismatch(
                command.target,
                opened_conversation_id=conversation_id_from_url(page.url),
                visible_profile_slug=profile_slug,
                visible_name=name,
                is_group=is_group,
            )
            if (
                mismatch == "display_name_changed"
                and command.target.conversation_id is not None
                and profile_slug is None
            ):
                page, root, profile_slug, name, is_group = await self._open(
                    page,
                    profile_slug=command.target.profile_slug,
                    conversation_id=None,
                    conversation_ref=None,
                )
                mismatch = self._inspected_target_mismatch(
                    command.target.model_copy(update={"conversation_id": None}),
                    opened_conversation_id=conversation_id_from_url(page.url),
                    visible_profile_slug=profile_slug,
                    visible_name=name,
                    is_group=is_group,
                )
            if mismatch is not None:
                return await self._result(
                    page,
                    root,
                    ActionOutcome.FAILED,
                    False,
                    "target_identity_changed",
                    (
                        "The visible one-to-one conversation no longer matches the requested "
                        f"target ({mismatch})."
                    ),
                )
            composer = await self._composer(root)
            reply_target: _ReplyTarget | None = None
            if payload.reply_to_message_ref is not None:
                try:
                    reply, reply_target = await self._reply_control(
                        page,
                        root,
                        payload.reply_to_message_ref,
                        participant_name=name,
                    )
                    await self._browser.click_visible_control(page, reply)
                except (InvalidTargetError, ParserDriftError) as error:
                    return await self._result(
                        page,
                        root,
                        ActionOutcome.FAILED,
                        False,
                        "message_reply_target_unavailable",
                        str(error),
                    )
            if payload.gif is not None:
                return await self._execute_gif(
                    page,
                    root,
                    payload,
                    participant_name=name,
                    reply_target=reply_target,
                )
            if payload.message is not None:
                maximum = await composer.get_attribute("maxlength")
                if maximum and len(payload.message) > int(maximum):
                    return await self._result(
                        page,
                        root,
                        ActionOutcome.FAILED,
                        False,
                        "message_too_long",
                        "The requested message exceeds LinkedIn's current visible field limit.",
                    )
            before = await self._matching_payload_count(
                page,
                root,
                payload,
                participant_name=name,
                reply_target=reply_target,
            )
            if payload.message is not None:
                await composer.fill(payload.message)
            try:
                await self._upload_attachments(root, payload)
            except InvalidTargetError as error:
                return await self._result(
                    page,
                    root,
                    ActionOutcome.FAILED,
                    False,
                    "message_attachment_unavailable",
                    str(error),
                )
            except PlaywrightError:
                return await self._result(
                    page,
                    root,
                    ActionOutcome.FAILED,
                    False,
                    "message_attachment_unavailable",
                    (
                        "The client-selected path could not be uploaded through "
                        "LinkedIn's visible attachment control."
                    ),
                )
            send = root.get_by_role(
                "button",
                name=re.compile(r"^(?:send|send message)$", re.I),
            )
            if await send.count() != 1:
                return await self._result(
                    page,
                    root,
                    ActionOutcome.FAILED,
                    False,
                    "message_send_unavailable",
                    "The conversation has no unique visible Send control.",
                )
            try:
                await self._browser.click_visible_control(page, send)
            except Exception:
                return await self._result(
                    page,
                    root,
                    ActionOutcome.UNCERTAIN,
                    None,
                    "message_outcome_unknown",
                    "Send was invoked, but LinkedIn's result could not be verified.",
                )
            composer_value: str | None = await self._available_composer_value(composer)
            for _ in range(24):
                if await root.count() != 1 or not await root.is_visible():
                    composer_value = None
                    break
                after = await self._matching_payload_count(
                    page,
                    root,
                    payload,
                    participant_name=name,
                    reply_target=reply_target,
                )
                composer_value = await self._available_composer_value(composer)
                if after > before and composer_value == "":
                    return await self._result(
                        page,
                        root,
                        ActionOutcome.VERIFIED,
                        True,
                        "message_sent",
                        (
                            "The exact requested message content newly appeared in visible "
                            "outgoing history."
                        ),
                    )
                if composer_value is None:
                    break
                await page.wait_for_timeout(250)
            result_root = (
                root
                if await root.count() == 1 and await root.is_visible()
                else page.locator("main").first
            )
            return await self._result(
                page,
                result_root,
                ActionOutcome.UNCERTAIN,
                None,
                "message_outcome_unknown",
                (
                    "The same visible conversation overlay did not gain the exact requested "
                    "outgoing payload within the verification bound."
                ),
            )

    @staticmethod
    def _inspected_target_mismatch(
        target: ActionTarget,
        *,
        opened_conversation_id: str | None,
        visible_profile_slug: str | None,
        visible_name: str,
        is_group: bool,
    ) -> str | None:
        if is_group:
            return "group_conversation_detected"
        if target.conversation_id is not None:
            if opened_conversation_id != target.conversation_id:
                return "conversation_id_changed"
        elif visible_profile_slug is None:
            return "profile_identity_missing"
        if visible_profile_slug is not None and visible_profile_slug != target.profile_slug:
            return "profile_slug_changed"
        if visible_name.casefold() != target.display_name.casefold():
            return "display_name_changed"
        return None

    async def _execute_gif(
        self,
        page: Page,
        root: Locator,
        payload: MessageSendPayload,
        *,
        participant_name: str,
        reply_target: _ReplyTarget | None,
    ) -> ActionPageResult:
        if payload.gif is None:
            raise InvalidTargetError("The GIF message payload is missing.")
        before = await self._matching_payload_count(
            page,
            root,
            payload,
            participant_name=participant_name,
            reply_target=reply_target,
        )
        result = await self._gif_result(page, root, payload.gif)
        try:
            await self._browser.click_visible_control(page, result)
        except Exception:
            return await self._result(
                page,
                root,
                ActionOutcome.UNCERTAIN,
                None,
                "message_outcome_unknown",
                "The exact GIF result was invoked, but its send outcome is unknown.",
            )
        for _ in range(24):
            after = await self._matching_payload_count(
                page,
                root,
                payload,
                participant_name=participant_name,
                reply_target=reply_target,
            )
            if after > before:
                return await self._result(
                    page,
                    root,
                    ActionOutcome.VERIFIED,
                    True,
                    "message_sent",
                    "The exact requested GIF newly appeared in visible outgoing history.",
                )
            await page.wait_for_timeout(250)
        return await self._result(
            page,
            root,
            ActionOutcome.UNCERTAIN,
            None,
            "message_outcome_unknown",
            "The requested GIF did not gain a new visible bubble within the verification bound.",
        )

    async def _validate_attachment_controls(
        self,
        root: Locator,
        request: MessageSendInput,
    ) -> None:
        for attachment in request.attachments:
            await self._attachment_input(root, attachment.asset_ref)

    async def _reply_control(
        self,
        page: Page,
        root: Locator,
        message_ref: str,
        *,
        participant_name: str,
    ) -> tuple[Locator, _ReplyTarget]:
        target = conversation_id_from_url(page.url) or participant_name.casefold()
        end_confirmations = 0
        for round_index in range(self._max_history_rounds):
            raw = await _raw_messages(root)
            messages = self._snapshot_messages(
                raw,
                target=target,
                page_url=page.url,
                participant_name=participant_name,
                is_group=False,
            )
            candidates = root.locator(
                'li:has([class*="event-listitem__body"]),'
                "li:has([data-test-message-body]),"
                "li:has([data-test-message-attachment]),"
                'li[class*="msg-s-event-listitem"]'
            )
            visible_candidates = [
                candidates.nth(index)
                for index in range(await candidates.count())
                if await candidates.nth(index).is_visible()
            ]
            if len(visible_candidates) != len(messages):
                raise ParserDriftError(
                    "LinkedIn's visible message identities do not align with reply controls."
                )
            matches = [
                (item, message)
                for item, message in zip(visible_candidates, messages, strict=True)
                if message.message_ref == message_ref
            ]
            if len(matches) > 1:
                raise InvalidTargetError(
                    "The exact reply message identity is ambiguous in this conversation."
                )
            if matches:
                item, message = matches[0]
                await item.scroll_into_view_if_needed()
                await item.hover()
                controls = item.get_by_role(
                    "button",
                    name=re.compile(r"^reply to this message$", re.I),
                )
                visible_controls = [
                    controls.nth(index)
                    for index in range(await controls.count())
                    if await controls.nth(index).is_visible()
                ]
                if len(visible_controls) != 1:
                    raise InvalidTargetError(
                        "The exact visible message has no unique Reply control."
                    )
                attachment_identities = tuple(
                    dict.fromkeys(
                        value
                        for attachment in message.attachments
                        for value in (
                            attachment.name,
                            attachment.accessible_label,
                            attachment.visible_text,
                        )
                        if value is not None
                    )
                )
                return (
                    visible_controls[0],
                    _ReplyTarget(
                        sender_name=message.sender_name,
                        text=message.text,
                        attachment_identities=attachment_identities,
                    ),
                )
            if round_index + 1 >= self._max_history_rounds:
                break
            settled = await _settle_history_scroll(page, root)
            if settled.outcome is CollectionSettleOutcome.EXPLICIT_END:
                break
            if settled.outcome is CollectionSettleOutcome.PROGRESSED:
                end_confirmations = 0
            elif await _history_at_physical_start(root):
                end_confirmations += 1
                if end_confirmations >= _HISTORY_END_CONFIRMATION_ROUNDS:
                    break
            else:
                end_confirmations = 0
        raise InvalidTargetError(
            "The exact reply message is no longer visible in the bounded conversation history."
        )

    async def _upload_attachments(
        self,
        root: Locator,
        payload: MessageSendPayload,
    ) -> None:
        for asset_ref in payload.attachment_refs:
            upload = await self._attachment_input(root, asset_ref)
            await upload.set_input_files(asset_ref)

    @staticmethod
    async def _attachment_input(root: Locator, asset_ref: str) -> Locator:
        suffix = Path(asset_ref).suffix.casefold()
        image_suffixes = {
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
        }
        inputs = root.locator('input[type="file"]')
        matches: list[tuple[Locator, tuple[str, ...]]] = []
        for index in range(await inputs.count()):
            upload = inputs.nth(index)
            accepted = (await upload.get_attribute("accept") or "").casefold()
            tokens = tuple(value.strip() for value in accepted.split(",") if value.strip())
            if not tokens or suffix in tokens or ("image/*" in tokens and suffix in image_suffixes):
                matches.append((upload, tokens))
        if suffix in image_suffixes:
            image_only = [upload for upload, tokens in matches if tokens == ("image/*",)]
            if len(image_only) == 1:
                return image_only[0]
        else:
            general = [
                upload for upload, tokens in matches if "image/*" in tokens and len(tokens) > 1
            ]
            if len(general) == 1:
                return general[0]
        if len(matches) != 1:
            raise InvalidTargetError(
                "The conversation has no unique compatible visible attachment input "
                f"for {suffix or 'this file'}."
            )
        return matches[0][0]

    async def _gif_result(
        self,
        page: Page,
        root: Locator,
        gif: MessageGifInput,
    ) -> Locator:
        opener = root.get_by_role(
            "button",
            name=re.compile(
                r"^(?:gif|add (?:a )?gif|open gif (?:picker|keyboard))$",
                re.I,
            ),
        )
        if await opener.count() != 1:
            raise InvalidTargetError("The conversation has no unique visible GIF picker control.")
        await self._browser.click_visible_control(page, opener)
        search = page.get_by_role(
            "textbox",
            name=re.compile(r"(?:search|find).*(?:gifs?|klipy)", re.I),
        )
        if await search.count() == 0:
            search = page.get_by_placeholder(re.compile(r"(?:search|find).*(?:gifs?|klipy)", re.I))
        if await search.count() != 1:
            raise ParserDriftError("LinkedIn's GIF picker has no unique visible search field.")
        await search.fill(gif.search_query)
        for _ in range(24):
            await page.wait_for_timeout(250)
            await self._browser.assert_safe(page)
            result = await self._visible_gif_result(page, gif.result_title)
            if result is not None:
                return result
        raise InvalidTargetError(
            "The requested GIF search did not produce one unique exact visible result "
            "within the bounded current-result wait."
        )

    @staticmethod
    async def _visible_gif_result(
        page: Page,
        result_title: str,
    ) -> Locator | None:
        label = re.compile(rf"^{re.escape(result_title)}$", re.I)
        candidates: list[Locator] = []
        for role in cast(
            tuple[Literal["button", "option"], ...],
            ("button", "option"),
        ):
            controls = page.get_by_role(role, name=label)
            for index in range(await controls.count()):
                control = controls.nth(index)
                if await control.is_visible():
                    candidates.append(control)
        if len(candidates) > 1:
            raise InvalidTargetError(
                "The requested GIF search produced multiple exact visible results."
            )
        if candidates:
            return candidates[0]
        images = page.get_by_role("img", name=label)
        visible_images = [
            images.nth(index)
            for index in range(await images.count())
            if await images.nth(index).is_visible()
        ]
        if len(visible_images) > 1:
            raise InvalidTargetError(
                "The requested GIF search produced multiple exact visible result images."
            )
        if visible_images:
            return visible_images[0]

        result_buttons = page.locator("button.tenor-gif__select-gif")
        title_matches: list[Locator] = []
        for index in range(await result_buttons.count()):
            result = result_buttons.nth(index)
            if not await result.is_visible():
                continue
            image = result.locator("img").first
            if await image.count() != 1:
                continue
            alternative = html.unescape(
                html.unescape((await image.get_attribute("alt") or "").strip())
            )
            match = re.fullmatch(
                r'A GIF image titled "(?P<title>.+)", that matches your search for .+\.',
                alternative,
                re.I,
            )
            if match and match.group("title").casefold() == result_title.casefold():
                title_matches.append(result)
        if len(title_matches) > 1:
            raise InvalidTargetError(
                "The requested GIF search produced multiple exact visible results."
            )
        return title_matches[0] if title_matches else None

    @staticmethod
    async def _matching_payload_count(
        page: Page,
        root: Locator,
        payload: MessageSendPayload,
        *,
        participant_name: str,
        reply_target: _ReplyTarget | None,
    ) -> int:
        count = 0
        raw_messages = await _raw_messages(root)
        directions = _resolved_directions(
            raw_messages,
            participant_name=participant_name,
            is_group=False,
        )
        for raw, direction in zip(raw_messages, directions, strict=True):
            if direction is not MessageDirection.OUTGOING:
                continue
            raw_text = raw.get("text")
            text = raw_text if isinstance(raw_text, str) and raw_text else None
            attachments = _message_attachments(raw, page_url=page.url)
            if payload.reply_to_message_ref is not None and (
                reply_target is None
                or not MessageSendPage._reply_matches(
                    raw,
                    reply_target,
                )
            ):
                continue
            if payload.gif is not None:
                if text is not None or len(attachments) != 1:
                    continue
                attachment = attachments[0]
                identities = {
                    value.casefold()
                    for value in (
                        attachment.name,
                        attachment.accessible_label,
                        attachment.visible_text,
                    )
                    if value is not None
                }
                if attachment.kind is MessageAttachmentKind.GIF and any(
                    payload.gif.result_title.casefold() in identity for identity in identities
                ):
                    count += 1
                continue
            if text != payload.message or len(attachments) != len(payload.attachment_refs):
                continue
            expected_kinds = tuple(
                MessageSendPage._attachment_kind_from_ref(value)
                for value in payload.attachment_refs
            )
            if tuple(attachment.kind for attachment in attachments) == expected_kinds:
                count += 1
        return count

    @staticmethod
    def _reply_matches(
        raw: dict[str, object],
        target: _ReplyTarget,
    ) -> bool:
        raw_sender = raw.get("reply_sender")
        visible_sender = (
            raw_sender.casefold() if isinstance(raw_sender, str) and raw_sender else None
        )
        if target.sender_name is not None and (
            visible_sender is None
            or not _visible_name_matches(visible_sender, target.sender_name.casefold())
        ):
            return False
        raw_text = raw.get("reply_text")
        visible_text = (
            " ".join(raw_text.split()).casefold()
            if isinstance(raw_text, str) and raw_text
            else None
        )
        expected_values = tuple(
            " ".join(value.split()).casefold()
            for value in (
                (target.text,) if target.text is not None else target.attachment_identities
            )
            if value
        )
        return (
            visible_text is not None
            and bool(expected_values)
            and any(
                visible_text == expected
                or visible_text.startswith(expected)
                or expected.startswith(visible_text)
                for expected in expected_values
            )
        )

    @staticmethod
    def _attachment_kind_from_ref(asset_ref: str) -> MessageAttachmentKind:
        suffix = Path(asset_ref).suffix.casefold()
        if suffix == ".gif":
            return MessageAttachmentKind.GIF
        if suffix in {
            ".bmp",
            ".heic",
            ".heif",
            ".jpeg",
            ".jpg",
            ".png",
            ".tif",
            ".tiff",
            ".webp",
        }:
            return MessageAttachmentKind.IMAGE
        if suffix in {".mov", ".mp4"}:
            return MessageAttachmentKind.VIDEO
        return MessageAttachmentKind.DOCUMENT

    @staticmethod
    async def _available_composer_value(composer: Locator) -> str | None:
        if await composer.count() != 1:
            return None
        try:
            return await MessageSendPage._composer_value(composer)
        except PlaywrightTimeoutError:
            return None

    @staticmethod
    async def _result(
        page: Page,
        root: Locator,
        outcome: ActionOutcome,
        performed: bool | None,
        final_state: str,
        detail: str,
    ) -> ActionPageResult:
        source_url = page.url
        if not conversation_id_from_url(source_url):
            profile_links = root.locator('a[href*="/in/"]')
            if await profile_links.count():
                href = await profile_links.first.get_attribute("href")
                slug = profile_slug_from_url(urljoin("https://www.linkedin.com", href or ""))
                if slug:
                    source_url = canonical_profile_url(slug)
        return ActionPageResult(
            outcome=outcome,
            performed=performed,
            final_state=final_state,
            detail=detail,
            source_url=HttpUrl(source_url),
            captured_text=await _visible_text(root),
            captured_at=datetime.now(UTC),
        )
