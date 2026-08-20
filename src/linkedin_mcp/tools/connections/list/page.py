"""Visible LinkedIn page implementation for `linkedin_mcp.tools.connections.list.page`."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, cast
from urllib.parse import urljoin

from pydantic import HttpUrl

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools.connections.list.models import (
    ConnectionsListCoverage,
    ConnectionsListInput,
    ConnectionsSortBy,
    ConnectionSummary,
    StopReason,
)
from linkedin_mcp.ui import LinkedInPage as Page
from linkedin_mcp.ui import LinkedInPlaywright
from linkedin_mcp.ui.collections import (
    CollectionSettleOutcome,
    CollectionSettleResult,
    dispatch_bubbling_wheel,
    wait_for_collection_interaction,
)
from linkedin_mcp.ui.urls import canonical_profile_url, profile_slug_from_url

_CONNECTIONS_URL = "https://www.linkedin.com/mynetwork/invite-connect/connections/"

_MUTUAL_PATTERN = re.compile(r"\bmutual connections?\b", re.IGNORECASE)

_TIME_PATTERN = re.compile(
    r"\b(?:today|yesterday|\d+\s+(?:minute|hour|day|week|month|year)s?\s+ago|"
    r"connected on|sent on|received on)\b",
    re.IGNORECASE,
)

_ACTION_LINE_PATTERN = re.compile(
    r"^(?:accept|ignore|withdraw|message|more|connect|pending)(?:\b|$)",
    re.IGNORECASE,
)

_INVITATION_ACTION_TARGET_PATTERNS = (
    re.compile(r"^withdraw invitation sent to (?P<name>.+)$", re.IGNORECASE),
    re.compile(
        r"^accept (?P<name>.+?)(?:'|\N{RIGHT SINGLE QUOTATION MARK})s invitation$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^accept (?:an )?invitation(?: to connect)? from (?P<name>.+)$",
        re.IGNORECASE,
    ),
)

_MEMBER_CARD_SELECTOR = (
    'main li, main [role="listitem"], main [data-testid="lazy-column"] > [data-display-contents]'
)

_MEMBER_LIST_END_PATTERN = re.compile(
    r"^(?:no (?:pending )?invitations(?: to show)?|no more invitations|"
    r"you(?:'|\N{RIGHT SINGLE QUOTATION MARK})?re all caught up|"
    r"you have no connections|"
    r"no connections found|no more connections)$",
    re.IGNORECASE,
)

_SCROLL_PROGRESS_POLL_ATTEMPTS = 8

_SCROLL_PROGRESS_POLL_DELAY_MS = 250

_TERMINAL_BOTTOM_STABILITY_ROUNDS = 3

_MAX_RAW_MEMBER_CARDS = 5_000

_CONNECTION_COUNT_PATTERN = re.compile(
    r"^(?P<count>\d[\d,]*)\s+connections$",
    re.I,
)


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


async def _visible_text(page: Page) -> str:
    for locator in (page.locator("main"), page.locator("body")):
        if await locator.count() == 0:
            continue
        value = (await locator.first.inner_text()).strip()
        if value:
            return value
    raise ParserDriftError("LinkedIn returned no visible connection text.")


def _profile_name(link_text: str, aria_label: str | None) -> str | None:
    values = _lines(link_text)
    if values:
        return values[0]
    if aria_label:
        match = re.match(r"^(?:View\s+)?(.+?)(?:'s profile| profile)?$", aria_label, re.I)
        if match:
            return match.group(1).strip()
    return None


def _descriptive_lines(visible_text: str, name: str) -> list[str]:
    values: list[str] = []
    for line in _lines(visible_text):
        if (
            line == name
            or _ACTION_LINE_PATTERN.match(line)
            or _MUTUAL_PATTERN.search(line)
            or _TIME_PATTERN.search(line)
        ):
            continue
        values.append(line)
    return values


async def _raw_member_cards(page: Page) -> list[dict[str, object]]:
    cards = page.locator(_MEMBER_CARD_SELECTOR)
    raw = await cards.evaluate_all(
        """
        (elements, limit) => {
          const candidateSelector = (
            'li,[role="listitem"],' +
            '[data-testid="lazy-column"] > [data-display-contents]'
          );
          const candidateSet = new Set(elements);
          const meaningful = element => {
            if (element.querySelector('a[href*="/in/"]')) return true;
            return Array.from(element.querySelectorAll("button,a")).some(control => {
              const value = (
                control.getAttribute("aria-label") || control.innerText || ""
              ).trim();
              return /^(?:accept|ignore|withdraw|connect|pending|message)(?:\\s|$)/i
                .test(value);
            });
          };
          return elements
          .filter(meaningful)
          .filter(element => !Array.from(
            element.querySelectorAll(candidateSelector)
          ).some(descendant => candidateSet.has(descendant) && meaningful(descendant)))
          .filter(element => (
            element.getClientRects().length > 0 ||
            Array.from(element.querySelectorAll('a[href*="/in/"], button'))
              .some(control => control.getClientRects().length > 0)
          ))
          .slice(0, limit)
          .map(element => {
            const note = element.querySelector(
              '[class*="invitation-card__custom-message"],' +
              '[class*="invitation-card__message"],[data-test-invitation-message]'
            );
            return {
              visible_text: element.innerText?.trim() ?? "",
              note: note?.innerText?.trim() ?? null,
              time: element.querySelector("time")?.innerText?.trim() ?? null,
              class_name: element.className?.toString() ?? "",
              aria_label: element.getAttribute("aria-label"),
              links: Array.from(element.querySelectorAll('a[href*="/in/"]'))
                .slice(0, 20)
                .map(link => ({
                  href: link.getAttribute("href") ?? "",
                  text: link.innerText?.trim() ?? "",
                  aria_label: link.getAttribute("aria-label")
                })),
              buttons: Array.from(element.querySelectorAll("button,a"))
                .filter(button => button.getClientRects().length > 0)
                .slice(0, 30)
                .map(button => (
                  button.getAttribute("aria-label") || button.innerText || ""
                ).trim())
                .filter(value => (
                  /^(?:accept|ignore|withdraw|connect|pending|message)\\b/i.test(value)
                )),
              message_links: Array.from(
                element.querySelectorAll('a[href*="/messaging"]')
              )
                .filter(link => link.getClientRects().length > 0)
                .slice(0, 10)
                .map(link => (
                  link.getAttribute("aria-label") || link.innerText || ""
                ).trim()),
              image_src: Array.from(element.querySelectorAll("img"))
                .find(image => image.getClientRects().length > 0)
                ?.getAttribute("src") ?? null
            };
          });
        }
        """,
        _MAX_RAW_MEMBER_CARDS,
    )
    return [
        cast(dict[str, object], item) for item in cast(list[object], raw) if isinstance(item, dict)
    ]


def _card_buttons(card: dict[str, object]) -> tuple[str, ...]:
    buttons = card.get("buttons")
    if not isinstance(buttons, list):
        return ()
    return tuple(value for value in cast(list[object], buttons) if isinstance(value, str) and value)


def _card_action_target_names(card: dict[str, object]) -> tuple[str, ...]:
    names: dict[str, str] = {}
    for value in _card_buttons(card):
        for pattern in _INVITATION_ACTION_TARGET_PATTERNS:
            match = pattern.fullmatch(value)
            if match is None:
                continue
            name = match.group("name").strip()
            if name:
                names.setdefault(name.casefold(), name)
            break
    return tuple(names.values())


def _card_profile_slugs(card: dict[str, object]) -> tuple[str, ...]:
    links = card.get("links")
    if not isinstance(links, list):
        return ()
    slugs: set[str] = set()
    for raw_link in cast(list[object], links):
        if not isinstance(raw_link, dict):
            continue
        href = cast(dict[str, object], raw_link).get("href")
        if not isinstance(href, str):
            continue
        slug = profile_slug_from_url(urljoin("https://www.linkedin.com", href))
        if slug is not None:
            slugs.add(slug)
    return tuple(sorted(slugs))


def _card_profile(card: dict[str, object]) -> tuple[str, str] | None:
    links = card.get("links")
    slugs = _card_profile_slugs(card)
    if not isinstance(links, list) or len(slugs) != 1:
        return None

    names: dict[str, str] = {}
    for raw_link in cast(list[object], links):
        if not isinstance(raw_link, dict):
            continue
        link = cast(dict[str, object], raw_link)
        href = link.get("href")
        text = link.get("text")
        aria_label = link.get("aria_label")
        image_alt = link.get("image_alt")
        if (
            not isinstance(href, str)
            or not isinstance(text, str)
            or not (isinstance(aria_label, str) or aria_label is None)
            or not (isinstance(image_alt, str) or image_alt is None)
            or profile_slug_from_url(urljoin("https://www.linkedin.com", href)) != slugs[0]
        ):
            continue
        for candidate in (
            _profile_name(text, aria_label),
            _profile_name(image_alt or "", None),
        ):
            if candidate:
                names.setdefault(candidate.casefold(), candidate)

    action_names = _card_action_target_names(card)
    if len(action_names) > 1 or len(names) > 1:
        return None
    action_name = action_names[0] if action_names else None
    link_name = next(iter(names.values())) if names else None
    if (
        link_name is not None
        and action_name is not None
        and link_name.casefold() != action_name.casefold()
    ):
        return None
    if link_name is not None:
        return slugs[0], link_name
    if action_name is None:
        return None

    visible_text = card.get("visible_text")
    visible_lines = _lines(visible_text) if isinstance(visible_text, str) else []
    if not visible_lines or visible_lines[0].casefold() != action_name.casefold():
        return None
    return slugs[0], action_name


def _card_has_message_action(card: dict[str, object]) -> bool:
    if any("message" in value.casefold() for value in _card_buttons(card)):
        return True
    links = card.get("message_links")
    return isinstance(links, list) and any(
        isinstance(value, str) and "message" in value.casefold()
        for value in cast(list[object], links)
    )


def _connection_from_card(card: dict[str, object]) -> ConnectionSummary | None:
    if not _card_has_message_action(card):
        return None
    profile = _card_profile(card)
    visible_text = card.get("visible_text")
    if profile is None or not isinstance(visible_text, str) or not visible_text:
        return None
    slug, name = profile
    descriptive = _descriptive_lines(visible_text, name)
    connected_at = next(
        (line for line in _lines(visible_text) if "connected" in line.casefold()),
        None,
    )
    content = [line for line in descriptive if line != connected_at]
    return ConnectionSummary(
        profile_slug=slug,
        profile_url=HttpUrl(canonical_profile_url(slug)),
        name=name,
        headline=content[0] if content else None,
        location=content[1] if len(content) > 1 else None,
        connected_at_text=connected_at,
        visible_text=visible_text,
    )


async def _visible_member_signature(page: Page) -> tuple[str, ...]:
    """Return raw card identities so parser rejection cannot hide DOM progress."""

    identities: list[str] = []
    for card in await _raw_member_cards(page):
        raw_links = card.get("links")
        href_values: list[str] = []
        if isinstance(raw_links, list):
            for raw_link in cast(list[object], raw_links):
                if not isinstance(raw_link, dict):
                    continue
                href = cast(dict[str, object], raw_link).get("href")
                if isinstance(href, str) and href:
                    href_values.append(href)
        hrefs = tuple(href_values)
        if hrefs:
            identities.append("links:" + "\x1f".join(hrefs))
            continue
        raw_text = card.get("visible_text")
        raw_label = card.get("aria_label")
        fallback = "\x1f".join(
            value
            for value in (
                raw_text if isinstance(raw_text, str) else "",
                raw_label if isinstance(raw_label, str) else "",
            )
            if value
        )
        if fallback:
            identities.append("card:" + hashlib.sha256(fallback.encode()).hexdigest())
    return tuple(identities)


def _member_list_has_explicit_end(visible_text: str) -> bool:
    return any(_MEMBER_LIST_END_PATTERN.fullmatch(line) for line in _lines(visible_text))


def _matched_visible_count(visible_text: str, pattern: re.Pattern[str]) -> int | None:
    values = {
        int(match.group("count").replace(",", ""))
        for line in _lines(visible_text)
        if (match := pattern.fullmatch(line)) is not None
    }
    if len(values) != 1:
        return None
    return values.pop()


def _connections_expected_count(visible_text: str) -> int | None:
    return _matched_visible_count(visible_text, _CONNECTION_COUNT_PATTERN)


async def _member_list_terminal_bottom_signature(
    page: Page,
    *,
    read_signature: Callable[[Page], Awaitable[tuple[str, ...]]] = _visible_member_signature,
) -> tuple[int, int, tuple[str, ...]] | None:
    """Return a stable terminal candidate from LinkedIn's visible list mechanics."""

    main = page.locator("main").first
    raw_state = cast(
        dict[str, object],
        await main.evaluate(
            """
            element => {
              const visible = candidate => candidate.getClientRects().length > 0;
              const candidates = [element, ...Array.from(element.querySelectorAll("*"))]
                .filter(candidate => {
                  const style = getComputedStyle(candidate);
                  return candidate.scrollHeight > candidate.clientHeight + 2 &&
                    /(auto|scroll|overlay)/.test(style.overflowY);
                })
                .sort((left, right) => (
                  (right.scrollHeight - right.clientHeight) -
                  (left.scrollHeight - left.clientHeight)
                ));
              const scroller = candidates[0] || document.scrollingElement;
              const busySelector = (
                '[role="progressbar"],[aria-busy="true"],.artdeco-loader,' +
                '[class*="loader"],[class*="loading"]'
              );
              const busyCandidates = Array.from(
                element.querySelectorAll(busySelector)
              );
              if (element.matches(busySelector)) busyCandidates.unshift(element);
              const busy = busyCandidates.some(candidate => visible(candidate));
              const tailControl = Array.from(element.querySelectorAll(
                "button,a,[role='button']"
              )).some(candidate => {
                if (!visible(candidate)) return false;
                const value = (
                  candidate.getAttribute("aria-label") ||
                  candidate.innerText ||
                  ""
                ).trim();
                return /^(?:show more(?: results)?|load more|see more)$/i.test(value);
              });
              if (!scroller) {
                return {
                  atBottom: false,
                  busy,
                  clientHeight: 0,
                  scrollHeight: 0,
                  tailControl
                };
              }
              const gap = Math.max(
                0,
                scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop
              );
              return {
                atBottom: gap <= 2,
                busy,
                clientHeight: Math.round(scroller.clientHeight),
                scrollHeight: Math.round(scroller.scrollHeight),
                tailControl
              };
            }
            """
        ),
    )
    if (
        raw_state.get("atBottom") is not True
        or raw_state.get("busy") is not False
        or raw_state.get("tailControl") is not False
    ):
        return None
    client_height = raw_state.get("clientHeight")
    scroll_height = raw_state.get("scrollHeight")
    if not isinstance(client_height, int) or not isinstance(scroll_height, int):
        return None
    return scroll_height, client_height, await read_signature(page)


@dataclass(slots=True)
class _MemberListTerminalTracker:
    signature: tuple[int, int, tuple[str, ...]] | None = None
    stable_rounds: int = 0
    required_stable_rounds: int = _TERMINAL_BOTTOM_STABILITY_ROUNDS

    def reset(self) -> None:
        self.signature = None
        self.stable_rounds = 0

    async def observe(
        self,
        page: Page,
        settled: CollectionSettleResult,
        *,
        inventory_complete: bool | None = None,
        read_signature: Callable[
            [Page],
            Awaitable[tuple[str, ...]],
        ] = _visible_member_signature,
    ) -> bool:
        if settled.outcome is not CollectionSettleOutcome.IDLE:
            self.reset()
            return False
        if inventory_complete is False:
            self.reset()
            return False
        candidate = await _member_list_terminal_bottom_signature(
            page,
            read_signature=read_signature,
        )
        if candidate is None:
            self.reset()
            return False
        if candidate == self.signature:
            self.stable_rounds += 1
        else:
            self.signature = candidate
            self.stable_rounds = 1
        return self.stable_rounds >= self.required_stable_rounds


async def _settle_scroll(
    page: Page,
    *,
    allow_explicit_end: bool = True,
    read_signature: Callable[
        [Page],
        Awaitable[tuple[str, ...]],
    ] = _visible_member_signature,
) -> CollectionSettleResult:
    baseline = await read_signature(page)
    main = page.locator("main").first
    delivery_attempt = 0

    async def scroll() -> None:
        nonlocal delivery_attempt
        delivery_attempt += 1
        await main.hover()
        await page.mouse.wheel(0, 3_000)
        if delivery_attempt > 1:
            await dispatch_bubbling_wheel(main, delta_y=3_000)

    async def explicit_end() -> bool:
        return _member_list_has_explicit_end(await _visible_text(page))

    return await wait_for_collection_interaction(
        page,
        baseline=baseline,
        interact=scroll,
        read_signature=lambda: read_signature(page),
        read_explicit_end=explicit_end if allow_explicit_end else None,
        attempts=_SCROLL_PROGRESS_POLL_ATTEMPTS,
        delay_ms=_SCROLL_PROGRESS_POLL_DELAY_MS,
    )


class ConnectionsListPage:
    _SORT_LABELS: ClassVar[dict[ConnectionsSortBy, re.Pattern[str]]] = {
        ConnectionsSortBy.FIRST_NAME: re.compile(r"^first name$", re.I),
        ConnectionsSortBy.LAST_NAME: re.compile(r"^last name$", re.I),
    }

    def __init__(self, playwright: LinkedInPlaywright, *, max_scroll_rounds: int) -> None:
        self._playwright = playwright
        self._max_scroll_rounds = max_scroll_rounds

    async def collect(
        self,
        request: ConnectionsListInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[ConnectionSummary, ...], ConnectionsListCoverage, str, str]:
        limit = request.page_size if result_limit is None else result_limit
        if limit < 1:
            raise ValueError("Connections result limit must be positive.")
        connections: dict[str, ConnectionSummary] = {}
        captures: list[str] = []
        stop_reason = StopReason.SAFETY_BOUND
        rounds_visited = 0
        terminal_tracker = _MemberListTerminalTracker()
        async with self._playwright.page() as page:
            await page.goto(_CONNECTIONS_URL)
            await page.locator("main").first.wait_for(state="visible")
            if request.sort_by is not ConnectionsSortBy.RECENTLY_ADDED:
                await self._apply_sort(page, request.sort_by)
            for round_index in range(self._max_scroll_rounds):
                rounds_visited += 1
                text = await _visible_text(page)
                if not captures or captures[-1] != text:
                    captures.append(text)
                for item in await self.extract_visible_connections(page):
                    connections.setdefault(item.profile_slug, item)
                if len(connections) >= limit:
                    stop_reason = StopReason.RESULT_LIMIT
                    break
                expected_count = _connections_expected_count(text)
                inventory_state = (
                    None if expected_count is None else len(connections) == expected_count
                )
                if _member_list_has_explicit_end(text) and inventory_state is not False:
                    stop_reason = (
                        StopReason.NO_NEW_RESULTS
                        if not connections
                        else StopReason.VISIBLE_PAGE_COMPLETE
                    )
                    break
                if round_index + 1 >= self._max_scroll_rounds:
                    break
                settled = await _settle_scroll(
                    page,
                    allow_explicit_end=inventory_state is not False,
                )
                if settled.outcome is CollectionSettleOutcome.EXPLICIT_END:
                    end_text = await _visible_text(page)
                    if not captures or captures[-1] != end_text:
                        captures.append(end_text)
                    stop_reason = (
                        StopReason.NO_NEW_RESULTS
                        if not connections
                        else StopReason.VISIBLE_PAGE_COMPLETE
                    )
                    break
                post_scroll_text = await _visible_text(page)
                expected_count = _connections_expected_count(post_scroll_text)
                inventory_state = (
                    None if expected_count is None else len(connections) == expected_count
                )
                if await terminal_tracker.observe(
                    page,
                    settled,
                    inventory_complete=inventory_state,
                ):
                    stop_reason = (
                        StopReason.NO_NEW_RESULTS
                        if not connections
                        else StopReason.VISIBLE_PAGE_COMPLETE
                    )
                    break
            source_url = page.url
        captured_at = datetime.now(UTC)
        values = tuple(connections.values())[:limit]
        return (
            values,
            ConnectionsListCoverage(
                sort_by=request.sort_by,
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
        textbox = main.get_by_role(
            "textbox",
            name=re.compile(r"search (?:by name|connections)", re.I),
        )
        if await textbox.count() == 0:
            textbox = main.get_by_placeholder(re.compile(r"search (?:by name|connections)", re.I))
        if await textbox.count() != 1:
            raise ParserDriftError("LinkedIn Connections has no unique visible name search.")
        await textbox.fill(query)
        await textbox.press("Enter")
        await page.wait_for_timeout(750)
        await page.assert_safe()

    async def _apply_sort(self, page: Page, sort_by: ConnectionsSortBy) -> None:
        main = page.locator("main")
        current_sort = main.get_by_role(
            "button",
            name=re.compile(r"^(?:recently added|first name|last name)$", re.I),
        )
        visible_controls = [
            current_sort.nth(index)
            for index in range(await current_sort.count())
            if await current_sort.nth(index).is_visible()
            and await current_sort.nth(index).get_attribute("aria-expanded") is not None
        ]
        if len(visible_controls) != 1:
            raise ParserDriftError("LinkedIn Connections has no unique visible sort control.")
        await visible_controls[0].click()
        option = page.get_by_role("option", name=self._SORT_LABELS[sort_by])
        if await option.count() == 0:
            option = page.get_by_role("menuitem", name=self._SORT_LABELS[sort_by])
        visible_options = [
            option.nth(index)
            for index in range(await option.count())
            if await option.nth(index).is_visible()
        ]
        if len(visible_options) != 1:
            raise ParserDriftError("The requested visible Connections sort option is unavailable.")
        await visible_options[0].click()

    @staticmethod
    async def extract_visible_connections(page: Page) -> tuple[ConnectionSummary, ...]:
        results: dict[str, ConnectionSummary] = {}
        for card in await _raw_member_cards(page):
            connection = _connection_from_card(card)
            if connection is None:
                continue
            results[connection.profile_slug] = connection
        return tuple(results.values())
