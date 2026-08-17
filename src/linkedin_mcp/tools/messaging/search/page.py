"""Visible LinkedIn page implementation for `linkedin_mcp.tools.messaging.search.page`."""

from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, Literal, cast
from urllib.parse import urljoin

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import HttpUrl

from linkedin_mcp.errors import InvalidTargetError, ParserDriftError
from linkedin_mcp.tools._shared.browser import BrowserManager
from linkedin_mcp.tools._shared.collections import (
    CollectionSettleOutcome,
    CollectionSettleResult,
    dispatch_bubbling_wheel,
    wait_for_collection_interaction,
)
from linkedin_mcp.tools._shared.models import StopReason
from linkedin_mcp.tools._shared.urls import (
    canonical_profile_url,
    conversation_id_from_url,
    profile_slug_from_url,
)
from linkedin_mcp.tools.messaging.search.models.conversation_category import ConversationCategory
from linkedin_mcp.tools.messaging.search.models.conversation_filter import ConversationFilter
from linkedin_mcp.tools.messaging.search.models.conversation_search_coverage import (
    ConversationSearchCoverage,
)
from linkedin_mcp.tools.messaging.search.models.conversation_search_input import (
    ConversationSearchInput,
)
from linkedin_mcp.tools.messaging.search.models.conversation_summary import ConversationSummary

_MESSAGING_URL = "https://www.linkedin.com/messaging/"

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


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


async def _visible_text(locator: Locator) -> str:
    if await locator.count() == 0:
        raise ParserDriftError("LinkedIn messaging returned no visible container.")
    value = (await locator.first.inner_text()).strip()
    if not value:
        raise ParserDriftError("LinkedIn messaging returned no visible text.")
    return value


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
