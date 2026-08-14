"""Visible LinkedIn inbox, conversation reads, and verified message sends."""

from __future__ import annotations

import hashlib
import html
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, Literal, cast
from urllib.parse import parse_qs, urljoin, urlsplit

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import HttpUrl

from linkedin_mcp.assets import LocalAssetStore
from linkedin_mcp.browser.convergence import (
    CollectionSettleOutcome,
    CollectionSettleResult,
    dispatch_bubbling_wheel,
    wait_for_collection_interaction,
)
from linkedin_mcp.browser.manager import BrowserManager
from linkedin_mcp.domain.models import (
    ActionCommand,
    ActionInspection,
    ActionOutcome,
    ActionPageResult,
    ActionTarget,
    ConversationCategory,
    ConversationCoverage,
    ConversationFilter,
    ConversationGetInput,
    ConversationObservation,
    ConversationSearchCoverage,
    ConversationSearchInput,
    ConversationSummary,
    MessageAttachmentKind,
    MessageAttachmentObservation,
    MessageDirection,
    MessageGifInput,
    MessageObservation,
    MessageSendInput,
    MessageSendPayload,
    StopReason,
)
from linkedin_mcp.errors import InvalidTargetError, ParserDriftError
from linkedin_mcp.policy import (
    canonical_conversation_url,
    canonical_profile_url,
    conversation_id_from_url,
    profile_slug_from_url,
)

_MESSAGING_URL = "https://www.linkedin.com/messaging/"
_COMPOSER_SELECTOR = '[contenteditable]:not([contenteditable="false"]), textarea'
_CONVERSATION_CARD_SELECTOR = (
    'main li[class*="msg-conversation-listitem"], main li:has(a[href*="/messaging/thread/"])'
)
_CONVERSATION_LIST_END_PATTERN = re.compile(
    r"^(?:no (?:messages|conversations)(?: found| to show)?|"
    r"no more (?:messages|conversations)|"
    r"you(?:'|\N{RIGHT SINGLE QUOTATION MARK})?ve reached the end)$",
    re.IGNORECASE,
)
_SCROLL_PROGRESS_POLL_ATTEMPTS = 8
_SCROLL_PROGRESS_POLL_DELAY_MS = 250
_END_CONFIRMATION_ROUNDS = 5
_HISTORY_END_CONFIRMATION_ROUNDS = 5
_NOISE_LINES = frozenset(
    {
        "messaging",
        "compose message",
        "search messages",
        "filter messages",
        "more",
        "send",
    }
)


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


def _conversation_ref(visible_text: str) -> str:
    digest = hashlib.sha256(visible_text.encode()).hexdigest()[:24]
    return f"conversation:{digest}"


async def _raw_conversation_cards(page: Page) -> list[dict[str, object]]:
    raw = (
        await page.locator("main")
        .locator("li")
        .evaluate_all(
            """
        elements => elements
          .filter(element => element.getClientRects().length > 0)
          .filter(element => (
            element.matches('[class*="msg-conversation-listitem"]') ||
            element.querySelector('a[href*="/messaging/thread/"]')
          ))
          .slice(0, 500)
          .map(element => {
            const thread = element.querySelector('a[href*="/messaging/thread/"]');
            const profile = element.querySelector('a[href*="/in/"]');
            const participant = element.querySelector(
              '[class*="conversation-listitem__participant-names"],' +
              '[class*="conversation-card__participant-names"]'
            );
            const snippet = element.querySelector(
              '[class*="message-snippet"],[class*="conversation-card__message"]'
            );
            return {
              visible_text: element.innerText?.trim() ?? "",
              class_name: element.className?.toString() ?? "",
              aria_label: element.getAttribute("aria-label"),
              conversation_href: thread?.getAttribute("href") ?? null,
              profile_href: profile?.getAttribute("href") ?? null,
              profile_text: profile?.innerText?.trim() ?? null,
              participant_text: participant?.innerText?.trim() ?? null,
              participant_class: participant?.className?.toString() ?? "",
              snippet: snippet?.innerText?.trim() ?? null,
              time: element.querySelector("time")?.innerText?.trim() ?? null,
              descendant_classes: Array.from(element.querySelectorAll("*"))
                .flatMap(node => String(node.className || "").split(/\\s+/))
                .filter(Boolean)
                .join(" "),
              status_labels: Array.from(element.querySelectorAll("[aria-label]"))
                .map(node => node.getAttribute("aria-label"))
                .filter(Boolean),
              labels: Array.from(
                element.querySelectorAll('[class*="conversation-card__pill"]')
              ).map(node => node.innerText?.trim() ?? "").filter(Boolean)
            };
          })
        """
        )
    )
    return [
        cast(dict[str, object], item) for item in cast(list[object], raw) if isinstance(item, dict)
    ]


async def _visible_conversation_signature(page: Page) -> tuple[str, ...]:
    """Track raw inbox-card identity independently of conversation parsing."""

    identities: list[str] = []
    for card in await _raw_conversation_cards(page):
        values = tuple(
            value
            for key in ("conversation_href", "profile_href", "aria_label", "visible_text")
            if isinstance((value := card.get(key)), str) and value
        )
        if values:
            identities.append(hashlib.sha256("\x1f".join(values).encode()).hexdigest())
    return tuple(identities)


def _conversation_search_has_explicit_end(visible_text: str) -> bool:
    return any(_CONVERSATION_LIST_END_PATTERN.fullmatch(line) for line in _lines(visible_text))


async def _settle_conversation_scroll(page: Page) -> CollectionSettleResult:
    baseline = await _visible_conversation_signature(page)
    cards = page.locator(_CONVERSATION_CARD_SELECTOR)
    last_visible: Locator | None = None
    for index in range(min(await cards.count(), 1_000)):
        candidate = cards.nth(index)
        if await candidate.is_visible():
            last_visible = candidate
    if last_visible is not None:
        await last_visible.scroll_into_view_if_needed()
    main = page.locator("main").first
    wheel_target = main
    containers = page.locator('main [class*="msg-conversations-container__conversations-list"]')
    for index in range(await containers.count()):
        container = containers.nth(index)
        if not await container.is_visible():
            continue
        wheel_target = container
        break
    delivery_attempt = 0

    async def scroll() -> None:
        nonlocal delivery_attempt
        delivery_attempt += 1
        await wheel_target.hover()
        await page.mouse.wheel(0, 1_500)
        if delivery_attempt > 1:
            await dispatch_bubbling_wheel(wheel_target, delta_y=1_500)

    async def explicit_end() -> bool:
        return _conversation_search_has_explicit_end(await _visible_text(page.locator("main")))

    return await wait_for_collection_interaction(
        page,
        baseline=baseline,
        interact=scroll,
        read_signature=lambda: _visible_conversation_signature(page),
        read_explicit_end=explicit_end,
        attempts=_SCROLL_PROGRESS_POLL_ATTEMPTS,
        delay_ms=_SCROLL_PROGRESS_POLL_DELAY_MS,
    )


async def _conversation_list_at_physical_end(page: Page) -> bool:
    containers = page.locator('main [class*="msg-conversations-container__conversations-list"]')
    for index in range(await containers.count()):
        container = containers.nth(index)
        if not await container.is_visible():
            continue
        state = cast(
            dict[str, object],
            await container.evaluate(
                """
                element => ({
                  scrollTop: element.scrollTop,
                  scrollHeight: element.scrollHeight,
                  clientHeight: element.clientHeight
                })
                """
            ),
        )
        scroll_top = state.get("scrollTop")
        scroll_height = state.get("scrollHeight")
        client_height = state.get("clientHeight")
        if all(isinstance(value, int | float) for value in state.values()):
            assert isinstance(scroll_top, int | float)
            assert isinstance(scroll_height, int | float)
            assert isinstance(client_height, int | float)
            return scroll_top + client_height >= scroll_height - 2
    return False


@dataclass(frozen=True, slots=True)
class _ConversationLookup:
    query: str | None
    category: ConversationCategory
    filter: ConversationFilter | None
    participant_name: str


class ConversationReferenceIndex:
    """Bounded process-local search context for opaque visible conversation refs."""

    def __init__(self, *, capacity: int = 5_000) -> None:
        if capacity < 1:
            raise ValueError("Conversation reference capacity must be positive.")
        self._capacity = capacity
        self._values: OrderedDict[str, _ConversationLookup] = OrderedDict()

    def remember(
        self,
        conversation_ref: str,
        *,
        request: ConversationSearchInput,
        participant_name: str,
    ) -> None:
        self._values[conversation_ref] = _ConversationLookup(
            query=request.query,
            category=request.resolved_category,
            filter=request.filter,
            participant_name=participant_name,
        )
        self._values.move_to_end(conversation_ref)
        while len(self._values) > self._capacity:
            self._values.popitem(last=False)

    def get(self, conversation_ref: str) -> _ConversationLookup | None:
        value = self._values.get(conversation_ref)
        if value is not None:
            self._values.move_to_end(conversation_ref)
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


class ConversationSearchPage:
    _CATEGORY_LABELS: ClassVar[dict[ConversationCategory, re.Pattern[str]]] = {
        ConversationCategory.FOCUSED: re.compile(r"^focused$", re.I),
        ConversationCategory.OTHER: re.compile(r"^other$", re.I),
        ConversationCategory.ARCHIVED: re.compile(r"^archived$", re.I),
        ConversationCategory.SPAM: re.compile(r"^spam$", re.I),
    }
    _FILTER_LABELS: ClassVar[dict[ConversationFilter, re.Pattern[str]]] = {
        ConversationFilter.JOBS: re.compile(r"^jobs$", re.I),
        ConversationFilter.UNREAD: re.compile(r"^(?:unread|unread messages)$", re.I),
        ConversationFilter.CONNECTIONS: re.compile(r"^connections$", re.I),
        ConversationFilter.STARRED: re.compile(r"^starred$", re.I),
        ConversationFilter.INMAIL: re.compile(r"^inmail$", re.I),
    }

    def __init__(
        self,
        browser: BrowserManager,
        *,
        max_scroll_rounds: int,
        reference_index: ConversationReferenceIndex | None = None,
    ) -> None:
        self._browser = browser
        self._max_scroll_rounds = max_scroll_rounds
        self._reference_index = reference_index or ConversationReferenceIndex()

    @property
    def reference_index(self) -> ConversationReferenceIndex:
        return self._reference_index

    async def collect(
        self,
        request: ConversationSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[ConversationSummary, ...], ConversationSearchCoverage, str, str]:
        limit = request.page_size if result_limit is None else result_limit
        if limit < 1:
            raise ValueError("Message-search result limit must be positive.")
        conversations: dict[str, ConversationSummary] = {}
        captures: list[str] = []
        stop_reason = StopReason.SAFETY_BOUND
        rounds_visited = 0
        end_confirmations = 0
        async with self._browser.page() as page:
            await self._browser.navigate(page, _MESSAGING_URL)
            await page.locator("main").first.wait_for(state="visible")
            await self._apply_category(page, request.resolved_category)
            if request.filter is not None:
                await self._apply_filter(page, request.filter)
            if request.query:
                await self._apply_query(page, request.query)
            for round_index in range(self._max_scroll_rounds):
                rounds_visited += 1
                text = await _visible_text(page.locator("main"))
                if not captures or captures[-1] != text:
                    captures.append(text)
                for item in await self.extract_visible_conversations(page):
                    key = item.conversation_id or item.conversation_ref
                    conversations.setdefault(key, item)
                    self._reference_index.remember(
                        item.conversation_ref,
                        request=request,
                        participant_name=item.participant_name,
                    )
                    if len(conversations) >= limit:
                        stop_reason = StopReason.RESULT_LIMIT
                        break
                if len(conversations) >= limit:
                    break
                if _conversation_search_has_explicit_end(text):
                    stop_reason = (
                        StopReason.NO_NEW_RESULTS
                        if not conversations
                        else StopReason.VISIBLE_PAGE_COMPLETE
                    )
                    break
                if round_index + 1 >= self._max_scroll_rounds:
                    break
                settled = await _settle_conversation_scroll(page)
                if settled.outcome is CollectionSettleOutcome.EXPLICIT_END:
                    end_text = await _visible_text(page.locator("main"))
                    if not captures or captures[-1] != end_text:
                        captures.append(end_text)
                    stop_reason = (
                        StopReason.NO_NEW_RESULTS
                        if not conversations
                        else StopReason.VISIBLE_PAGE_COMPLETE
                    )
                    break
                if settled.outcome is CollectionSettleOutcome.PROGRESSED:
                    end_confirmations = 0
                    continue
                if await _conversation_list_at_physical_end(page):
                    end_confirmations += 1
                    if end_confirmations >= _END_CONFIRMATION_ROUNDS:
                        stop_reason = (
                            StopReason.NO_NEW_RESULTS
                            if not conversations
                            else StopReason.VISIBLE_PAGE_COMPLETE
                        )
                        break
                else:
                    end_confirmations = 0
            source_url = _MESSAGING_URL
        captured_at = datetime.now(UTC)
        values = tuple(conversations.values())[:limit]
        return (
            values,
            ConversationSearchCoverage(
                query=request.query,
                category=request.resolved_category,
                filter=request.filter,
                rounds_visited=rounds_visited,
                result_count=len(values),
                max_results=limit,
                stop_reason=stop_reason,
                captured_at=captured_at,
            ),
            "\n\n--- scroll boundary ---\n\n".join(captures),
            source_url,
        )

    async def _apply_query(self, page: Page, query: str) -> None:
        main = page.locator("main")
        textbox = main.get_by_role("textbox", name=re.compile(r"search messages", re.I))
        if await textbox.count() == 0:
            textbox = main.get_by_placeholder(re.compile(r"search messages", re.I))
        if await textbox.count() != 1:
            raise ParserDriftError("LinkedIn Messaging has no unique visible search box.")
        await textbox.fill(query)
        await textbox.press("Enter")
        await page.wait_for_timeout(750)
        await self._browser.assert_safe(page)

    async def _apply_category(
        self,
        page: Page,
        category: ConversationCategory,
    ) -> None:
        label = self._CATEGORY_LABELS[category]
        option = await self._unique_named_control(page, label, roles=("menuitem", "option"))
        if option is None:
            main = page.locator("main")
            opener = main.get_by_role(
                "button",
                name=re.compile(
                    r"^(?:inbox category|focused|other|archived|spam)(?: messages)?$",
                    re.I,
                ),
            )
            if await opener.count() != 1:
                raise ParserDriftError(
                    "LinkedIn Messaging has no unique visible inbox-category control."
                )
            current_name = (
                await opener.get_attribute("aria-label") or await opener.inner_text()
            ).strip()
            if label.fullmatch(current_name):
                return
            await self._browser.click_visible_control(page, opener)
            option = await self._unique_named_control(
                page,
                label,
                roles=("menuitem", "option", "button"),
            )
        if option is None:
            raise ParserDriftError(
                f"LinkedIn Messaging has no unique visible {category.value} category."
            )
        await self._browser.click_visible_control(page, option)
        await page.wait_for_timeout(500)
        await self._browser.assert_safe(page)

    async def _apply_filter(
        self,
        page: Page,
        conversation_filter: ConversationFilter,
    ) -> None:
        label = self._FILTER_LABELS[conversation_filter]
        option = await self._unique_named_control(page, label, roles=("button",))
        if option is None:
            raise ParserDriftError(
                f"LinkedIn Messaging has no unique visible {conversation_filter.value} filter."
            )
        if (
            await option.get_attribute("aria-pressed") == "true"
            or await option.get_attribute("aria-checked") == "true"
        ):
            return
        await self._browser.click_visible_control(page, option)
        await page.wait_for_timeout(500)
        await self._browser.assert_safe(page)
        if (
            await option.get_attribute("aria-pressed") != "true"
            and await option.get_attribute("aria-checked") != "true"
        ):
            raise ParserDriftError(
                f"LinkedIn Messaging did not visibly select the {conversation_filter.value} filter."
            )

    async def open_reference(
        self,
        page: Page,
        conversation_ref: str,
    ) -> tuple[ConversationSummary, Locator]:
        lookup = self._reference_index.get(conversation_ref)
        if lookup is None:
            raise InvalidTargetError(
                "The process-local conversation reference is unavailable; search messages "
                "again before opening it."
            )
        await self._browser.navigate(page, _MESSAGING_URL)
        await page.locator("main").first.wait_for(state="visible")
        await self._apply_category(page, lookup.category)
        if lookup.filter is not None:
            await self._apply_filter(page, lookup.filter)
        if lookup.query:
            await self._apply_query(page, lookup.query)

        end_confirmations = 0
        for round_index in range(self._max_scroll_rounds):
            summaries = await self.extract_visible_conversations(page)
            exact = [item for item in summaries if item.conversation_ref == conversation_ref]
            if not exact:
                exact = [
                    item
                    for item in summaries
                    if item.participant_name.casefold() == lookup.participant_name.casefold()
                ]
            cards = page.locator('main li[class*="msg-conversation-listitem"]')
            matching_cards: list[Locator] = []
            for index in range(await cards.count()):
                card = cards.nth(index)
                if not await card.is_visible():
                    continue
                text = (await card.inner_text()).strip()
                participant = card.locator(
                    '[class*="conversation-listitem__participant-names"],'
                    '[class*="conversation-card__participant-names"]'
                )
                participant_text = (
                    (await participant.first.inner_text()).strip()
                    if await participant.count()
                    else ""
                )
                if _conversation_ref(text) == conversation_ref or (
                    participant_text.casefold() == lookup.participant_name.casefold()
                ):
                    matching_cards.append(card)
            if len(exact) == 1 and len(matching_cards) == 1:
                card = matching_cards[0]
                clickable = card.locator(
                    '[class*="msg-conversation-listitem__link"],'
                    '[class*="msg-conversations-container__convo-item-link"]'
                )
                control = clickable.first if await clickable.count() == 1 else card
                await self._browser.click_visible_control(page, control)
                try:
                    await page.wait_for_url(
                        lambda value: conversation_id_from_url(str(value)) is not None,
                        timeout=5_000,
                    )
                except PlaywrightTimeoutError as error:
                    raise ParserDriftError(
                        "The exact visible search result did not open a supported thread URL."
                    ) from error
                await self._browser.assert_safe(page)
                return exact[0], card
            if len(exact) > 1 or len(matching_cards) > 1:
                raise InvalidTargetError(
                    "The searched conversation reference resolves to multiple visible threads."
                )
            if round_index + 1 >= self._max_scroll_rounds:
                break
            settled = await _settle_conversation_scroll(page)
            if settled.outcome is CollectionSettleOutcome.EXPLICIT_END:
                break
            if settled.outcome is CollectionSettleOutcome.PROGRESSED:
                end_confirmations = 0
            elif await _conversation_list_at_physical_end(page):
                end_confirmations += 1
                if end_confirmations >= _END_CONFIRMATION_ROUNDS:
                    break
            else:
                end_confirmations = 0
        raise InvalidTargetError(
            "The searched conversation reference is no longer visible; search messages again."
        )

    @staticmethod
    async def _unique_named_control(
        page: Page,
        label: re.Pattern[str],
        *,
        roles: tuple[Literal["menuitem", "option", "button"], ...],
    ) -> Locator | None:
        candidates: list[Locator] = []
        for role in roles:
            controls = page.get_by_role(role, name=label)
            for index in range(await controls.count()):
                control = controls.nth(index)
                if not await control.is_visible():
                    continue
                candidates.append(control)
        if len(candidates) > 1:
            raise ParserDriftError("LinkedIn Messaging exposed an ambiguous visible filter.")
        return candidates[0] if candidates else None

    @staticmethod
    async def extract_visible_conversations(page: Page) -> tuple[ConversationSummary, ...]:
        values: list[ConversationSummary] = []
        for card in await _raw_conversation_cards(page):
            visible_text = card.get("visible_text")
            if not isinstance(visible_text, str) or not visible_text:
                continue
            conversation_href = card.get("conversation_href")
            conversation_id = (
                conversation_id_from_url(urljoin("https://www.linkedin.com", conversation_href))
                if isinstance(conversation_href, str)
                else None
            )
            profile_href = card.get("profile_href")
            profile_slug = (
                profile_slug_from_url(urljoin("https://www.linkedin.com", profile_href))
                if isinstance(profile_href, str)
                else None
            )
            raw_profile_text = card.get("profile_text")
            raw_participant_text = card.get("participant_text")
            lines = _lines(visible_text)
            participant_name = (
                _lines(raw_profile_text)[0]
                if isinstance(raw_profile_text, str) and _lines(raw_profile_text)
                else (
                    _lines(raw_participant_text)[0]
                    if isinstance(raw_participant_text, str) and _lines(raw_participant_text)
                    else next(
                        (line for line in lines if line.casefold() not in _NOISE_LINES),
                        None,
                    )
                )
            )
            if not participant_name:
                continue
            raw_time = card.get("time")
            activity = raw_time if isinstance(raw_time, str) and raw_time else None
            raw_snippet = card.get("snippet")
            snippet = (
                raw_snippet
                if isinstance(raw_snippet, str) and raw_snippet
                else next(
                    (
                        line
                        for line in lines
                        if line not in {participant_name, activity}
                        and line.casefold() not in _NOISE_LINES
                    ),
                    None,
                )
            )
            indicators = " ".join(
                value.casefold()
                for key in (
                    "class_name",
                    "aria_label",
                    "participant_class",
                    "descendant_classes",
                )
                if isinstance((value := card.get(key)), str)
            )
            raw_status_labels = card.get("status_labels")
            status_labels = tuple(
                value
                for value in (
                    cast(list[object], raw_status_labels)
                    if isinstance(raw_status_labels, list)
                    else []
                )
                if isinstance(value, str) and value
            )
            raw_labels = card.get("labels")
            labels = tuple(
                dict.fromkeys(
                    value
                    for value in (
                        cast(list[object], raw_labels) if isinstance(raw_labels, list) else []
                    )
                    if isinstance(value, str) and value
                )
            )[:10]
            values.append(
                ConversationSummary(
                    conversation_ref=_conversation_ref(visible_text),
                    conversation_id=conversation_id,
                    participant_profile_slug=profile_slug,
                    participant_profile_url=(
                        HttpUrl(canonical_profile_url(profile_slug)) if profile_slug else None
                    ),
                    participant_name=participant_name,
                    is_group="group" in indicators,
                    last_message_text=snippet,
                    last_activity_text=activity,
                    unread="unread" in indicators or "t-bold" in indicators.split(),
                    starred=any(
                        re.search(r"^unstar conversation", value, re.I) for value in status_labels
                    ),
                    muted="mute-icon" in indicators
                    or any(re.search(r"\bmuted\b", value, re.I) for value in status_labels),
                    labels=labels,
                    visible_text=visible_text,
                )
            )
        return tuple(values)


class ConversationPage:
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

    async def read(self, request: ConversationGetInput) -> ConversationObservation:
        async with self._browser.page() as page:
            page, root, profile_slug, name, is_group = await self._open(
                page,
                profile_slug=request.profile_slug,
                conversation_id=request.conversation_id,
                conversation_ref=request.conversation_ref,
            )
            return await self._extract(
                page,
                root,
                conversation_ref=request.conversation_ref,
                profile_slug=profile_slug,
                participant_name=name,
                is_group=is_group,
                max_messages=request.max_messages,
            )

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
        paths: dict[str, Path] = {}
        if payload.attachment_refs:
            if self._assets is None:
                raise InvalidTargetError(
                    "Message attachments require the configured local asset store."
                )
            paths = await self._assets.resolve_message(payload.attachment_refs)
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
                await self._upload_attachments(root, payload, paths)
            except InvalidTargetError as error:
                return await self._result(
                    page,
                    root,
                    ActionOutcome.FAILED,
                    False,
                    "message_attachment_unavailable",
                    str(error),
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
        paths: dict[str, Path],
    ) -> None:
        for asset_ref in payload.attachment_refs:
            path = paths.get(asset_ref)
            if path is None:
                raise InvalidTargetError(
                    f"The requested message attachment {asset_ref!r} was not verified."
                )
            upload = await self._attachment_input(root, asset_ref)
            await upload.set_input_files(str(path))

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
                or not ConversationPage._reply_matches(
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
                ConversationPage._attachment_kind_from_ref(value)
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
                exact_compose_recipient = ConversationPage._exact_profile_compose_url(
                    page.url
                ) and await ConversationPage._has_exact_single_recipient_pill(
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

    async def _extract(
        self,
        page: Page,
        root: Locator,
        *,
        conversation_ref: str | None,
        profile_slug: str | None,
        participant_name: str,
        is_group: bool,
        max_messages: int,
    ) -> ConversationObservation:
        conversation_id = conversation_id_from_url(page.url)
        target = conversation_id or profile_slug or participant_name.casefold()
        snapshots: list[tuple[MessageObservation, ...]] = []
        captures: list[str] = []
        observed_refs: set[str] = set()
        stop_reason = StopReason.SAFETY_BOUND
        end_confirmations = 0
        rounds_visited = 0

        for round_index in range(self._max_history_rounds):
            rounds_visited += 1
            visible_text = await _visible_text(root)
            if not captures or captures[-1] != visible_text:
                captures.append(visible_text)
            snapshot = self._snapshot_messages(
                await _raw_messages(root),
                target=target,
                page_url=page.url,
                participant_name=participant_name,
                is_group=is_group,
            )
            snapshots.append(snapshot)
            observed_refs.update(message.message_ref for message in snapshot)
            if len(observed_refs) > max_messages:
                stop_reason = StopReason.RESULT_LIMIT
                break
            if _history_has_explicit_start(visible_text):
                stop_reason = (
                    StopReason.NO_NEW_RESULTS
                    if not observed_refs
                    else StopReason.VISIBLE_PAGE_COMPLETE
                )
                break
            if round_index + 1 >= self._max_history_rounds:
                break
            settled = await _settle_history_scroll(page, root)
            if settled.outcome is CollectionSettleOutcome.EXPLICIT_END:
                stop_reason = (
                    StopReason.NO_NEW_RESULTS
                    if not observed_refs
                    else StopReason.VISIBLE_PAGE_COMPLETE
                )
                break
            if settled.outcome is CollectionSettleOutcome.PROGRESSED:
                end_confirmations = 0
                continue
            if await _history_at_physical_start(root):
                end_confirmations += 1
                if end_confirmations >= _HISTORY_END_CONFIRMATION_ROUNDS:
                    stop_reason = (
                        StopReason.NO_NEW_RESULTS
                        if not observed_refs
                        else StopReason.VISIBLE_PAGE_COMPLETE
                    )
                    break
            else:
                end_confirmations = 0

        merged: list[MessageObservation] = []
        merged_refs: set[str] = set()
        for snapshot in reversed(snapshots):
            for message in snapshot:
                if message.message_ref in merged_refs:
                    continue
                merged_refs.add(message.message_ref)
                merged.append(message)
        retained = tuple(merged[-max_messages:])
        history_complete = stop_reason in {
            StopReason.NO_NEW_RESULTS,
            StopReason.VISIBLE_PAGE_COMPLETE,
        }
        captured_at = datetime.now(UTC)
        evidence_text = "\n\n--- history window ---\n\n".join(captures)
        return ConversationObservation(
            conversation_ref=conversation_ref,
            conversation_id=conversation_id,
            participant_profile_slug=profile_slug,
            participant_profile_url=(
                HttpUrl(canonical_profile_url(profile_slug)) if profile_slug else None
            ),
            participant_name=participant_name,
            is_group=is_group,
            messages=retained,
            visible_text=evidence_text,
            coverage=ConversationCoverage(
                messages_observed=len(merged),
                messages_returned=len(retained),
                attachments_returned=sum(len(message.attachments) for message in retained),
                replies_returned=sum(
                    message.reply_to_sender_name is not None or message.reply_to_text is not None
                    for message in retained
                ),
                reactions_returned=sum(len(message.reaction_summaries) for message in retained),
                max_messages=max_messages,
                rounds_visited=rounds_visited,
                stop_reason=stop_reason,
                history_complete=history_complete,
                truncated=not history_complete or len(merged) > len(retained),
                captured_at=captured_at,
            ),
            captured_at=captured_at,
        )

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

    @staticmethod
    async def _available_composer_value(composer: Locator) -> str | None:
        if await composer.count() != 1:
            return None
        try:
            return await ConversationPage._composer_value(composer)
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
