"""Visible LinkedIn connection inventory and exact invitation lifecycle actions."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar, cast
from urllib.parse import parse_qs, urljoin, urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import HttpUrl

from linkedin_mcp.errors import InvalidTargetError, LinkedInMCPError, ParserDriftError
from linkedin_mcp.tools._shared.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutcome,
    ActionPageResult,
    ActionTarget,
    InvitationAcceptPayload,
    InvitationIgnorePayload,
    InvitationSendPayload,
)
from linkedin_mcp.tools._shared.browser import BrowserManager
from linkedin_mcp.tools._shared.collections import (
    CollectionSettleOutcome,
    CollectionSettleResult,
    dispatch_bubbling_wheel,
    wait_for_collection_interaction,
)
from linkedin_mcp.tools._shared.models import StopReason
from linkedin_mcp.tools._shared.network_models import (
    ConnectionsListCoverage,
    ConnectionsListInput,
    ConnectionsSortBy,
    ConnectionSummary,
    InvitationAcceptInput,
    InvitationIgnoreInput,
    InvitationSendInput,
)
from linkedin_mcp.tools._shared.urls import canonical_profile_url, profile_slug_from_url

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
_PROFILE_ACTION_SETTLE_ATTEMPTS = 24
_PROFILE_ACTION_SETTLE_DELAY_MS = 250
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


def _received_invitation_ref(profile_slug: str) -> str:
    digest = hashlib.sha256(f"received\x1f{profile_slug}".encode()).hexdigest()[:24]
    return f"invitation:{digest}"


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


async def _wait_for_unique_visible(
    page: Page,
    locator: Locator,
    description: str,
    *,
    attempts: int = 20,
) -> Locator:
    for _ in range(attempts):
        visible = [
            locator.nth(index)
            for index in range(await locator.count())
            if await locator.nth(index).is_visible()
        ]
        if len(visible) == 1:
            return visible[0]
        if len(visible) > 1:
            raise ParserDriftError(f"LinkedIn exposed ambiguous visible {description}.")
        await page.wait_for_timeout(250)
    raise ParserDriftError(f"LinkedIn exposed no unique visible {description}.")


async def _optional_unique_visible(
    locator: Locator,
    description: str,
) -> Locator | None:
    visible = [
        locator.nth(index)
        for index in range(await locator.count())
        if await locator.nth(index).is_visible()
    ]
    if len(visible) > 1:
        raise ParserDriftError(f"LinkedIn exposed ambiguous visible {description}.")
    return visible[0] if visible else None


class ConnectionsListPage:
    _SORT_LABELS: ClassVar[dict[ConnectionsSortBy, re.Pattern[str]]] = {
        ConnectionsSortBy.FIRST_NAME: re.compile(r"^first name$", re.I),
        ConnectionsSortBy.LAST_NAME: re.compile(r"^last name$", re.I),
    }

    def __init__(self, browser: BrowserManager, *, max_scroll_rounds: int) -> None:
        self._browser = browser
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
        async with self._browser.page() as page:
            await self._browser.navigate(page, _CONNECTIONS_URL)
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
        await self._browser.assert_safe(page)

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
        await self._browser.click_visible_control(page, visible_controls[0])
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
        await self._browser.click_visible_control(page, visible_options[0])

    @staticmethod
    async def extract_visible_connections(page: Page) -> tuple[ConnectionSummary, ...]:
        results: dict[str, ConnectionSummary] = {}
        for card in await _raw_member_cards(page):
            connection = _connection_from_card(card)
            if connection is None:
                continue
            results[connection.profile_slug] = connection
        return tuple(results.values())


class InvitationActionPage:
    def __init__(self, browser: BrowserManager) -> None:
        self._browser = browser

    async def inspect_send(
        self,
        request: InvitationSendInput,
    ) -> ActionInspection:
        async with self._browser.page() as page:
            await self._browser.navigate(page, canonical_profile_url(request.profile_slug))
            main, name = await self._profile_identity(page)
            state, connect = await self._wait_for_connect_control(page, main, name)
            if state != "connect_available":
                raise InvalidTargetError(
                    f"LinkedIn profile is not eligible for a new invitation: {state}."
                )
            if connect is None:
                raise ParserDriftError("The exact profile has no unique visible Connect control.")
            await self._browser.click_visible_control(page, connect)
            dialog = await _wait_for_unique_visible(
                page,
                page.get_by_role("dialog"),
                "invitation confirmation dialog",
            )
            dialog = await self._validate_invitation_dialog(
                page,
                dialog,
                request.note,
            )
            captured_text = f"{await _visible_text(page)}\n{await dialog.inner_text()}".strip()
            return ActionInspection(
                target=ActionTarget(
                    profile_slug=request.profile_slug,
                    profile_url=HttpUrl(canonical_profile_url(request.profile_slug)),
                    display_name=name,
                ),
                current_state=state,
                source_url=HttpUrl(page.url),
                captured_text=captured_text,
                captured_at=datetime.now(UTC),
            )

    async def inspect_accept(
        self,
        request: InvitationAcceptInput,
    ) -> ActionInspection:
        return await self._inspect_received_request(request.profile_slug)

    async def inspect_ignore(
        self,
        request: InvitationIgnoreInput,
    ) -> ActionInspection:
        return await self._inspect_received_request(request.profile_slug)

    async def _inspect_received_request(
        self,
        profile_slug: str,
    ) -> ActionInspection:
        async with self._browser.page() as page:
            await self._browser.navigate(page, canonical_profile_url(profile_slug))
            main, name = await self._profile_identity(page)
            accept, ignore = await self._incoming_request_controls(main, name)
            if accept is None or ignore is None:
                raise InvalidTargetError(
                    "The exact profile has no current visible incoming connection request."
                )
            captured_text = await _visible_text(page)
            reference = _received_invitation_ref(profile_slug)
            return ActionInspection(
                target=ActionTarget(
                    profile_slug=profile_slug,
                    profile_url=HttpUrl(canonical_profile_url(profile_slug)),
                    display_name=name,
                    invitation_ref=reference,
                ),
                current_state="received_invitation_pending",
                source_url=HttpUrl(page.url),
                captured_text=captured_text,
                captured_at=datetime.now(UTC),
            )

    async def _validate_invitation_dialog(
        self,
        page: Page,
        dialog: Locator,
        note: str | None,
    ) -> Locator:
        if re.search(r"how do you know", await dialog.inner_text(), re.I):
            raise InvalidTargetError(
                "LinkedIn requires a relationship choice; no relationship was inferred."
            )
        if note is None:
            send_without_note = dialog.get_by_role(
                "button",
                name=re.compile(r"^send without a note$", re.I),
            )
            if await send_without_note.count() != 1:
                raise ParserDriftError(
                    "The current invitation dialog has no unique Send without a note control."
                )
            await self._validate_send_control(send_without_note)
            return dialog

        add_note = dialog.get_by_role("button", name=re.compile(r"^add a note$", re.I))
        if await add_note.count() != 1:
            raise InvalidTargetError(
                "LinkedIn does not offer a personalized note for this invitation."
            )
        await self._browser.click_visible_control(page, add_note)
        textbox = await _wait_for_unique_visible(
            page,
            page.get_by_role("dialog").get_by_role("textbox"),
            "invitation note textbox",
        )
        note_dialog = textbox.locator("xpath=ancestor::*[self::dialog or @role='dialog'][1]")
        if await note_dialog.count() != 1 or not await note_dialog.is_visible():
            raise ParserDriftError("Invitation note textbox has no unique visible dialog.")
        maximum = await self._invitation_note_limit(textbox, note_dialog)
        if len(note) > maximum:
            raise InvalidTargetError(
                "The invitation note exceeds LinkedIn's current visible field limit."
            )
        await textbox.fill(note)
        note_count, note_limit = await self._invitation_note_counter(note_dialog)
        if await textbox.input_value() != note or note_count != len(note) or note_limit != maximum:
            raise ParserDriftError(
                "The invitation note did not visibly commit to the textbox and character counter."
            )
        send = note_dialog.get_by_role(
            "button",
            name=re.compile(r"^send invitation$", re.I),
        )
        if await send.count() != 1:
            raise ParserDriftError("The current note dialog has no unique Send invitation control.")
        await self._validate_send_control(send)
        return note_dialog

    @staticmethod
    async def _validate_send_control(send: Locator) -> None:
        if not await send.is_visible() or not await send.is_enabled():
            raise ParserDriftError("The current invitation Send control is not actionable.")
        try:
            await send.click(trial=True, timeout=2_000)
        except PlaywrightError as error:
            raise ParserDriftError(
                "The current invitation Send control did not pass actionability checks."
            ) from error

    async def perform_send(self, command: ActionCommand) -> ActionPageResult:
        if not isinstance(command.payload, InvitationSendPayload):
            raise InvalidTargetError("The invitation action payload is invalid.")
        async with self._browser.page() as page:
            await self._browser.navigate(page, canonical_profile_url(command.target.profile_slug))
            main, name = await self._profile_identity(page)
            if name.casefold() != command.target.display_name.casefold():
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "target_identity_changed",
                    "The visible profile name changed during the action; review before retrying.",
                )
            state, connect = await self._wait_for_connect_control(page, main, name)
            if state in {"already_connected", "pending_sent"}:
                return await self._result(
                    page,
                    ActionOutcome.VERIFIED,
                    False,
                    state,
                    "LinkedIn already shows the requested terminal connection state.",
                )
            if state != "connect_available" or connect is None:
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    state,
                    "The requested profile no longer exposes a visible Connect action.",
                )
            await self._browser.click_visible_control(page, connect)
            try:
                dialog = await _wait_for_unique_visible(
                    page,
                    page.get_by_role("dialog"),
                    "invitation confirmation dialog",
                )
            except ParserDriftError:
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "connection_dialog_unavailable",
                    "Connect opened no supported visible invitation confirmation.",
                )
            if re.search(r"how do you know", await dialog.inner_text(), re.I):
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "relationship_confirmation_required",
                    "LinkedIn requires a relationship choice; no relationship was inferred.",
                )
            if command.payload.note:
                add_note = dialog.get_by_role("button", name=re.compile(r"^add a note$", re.I))
                if await add_note.count() != 1:
                    return await self._result(
                        page,
                        ActionOutcome.FAILED,
                        False,
                        "personalized_invitation_unavailable",
                        "LinkedIn does not offer a personalized note for this invitation.",
                    )
                await self._browser.click_visible_control(page, add_note)
                textbox = await _wait_for_unique_visible(
                    page,
                    page.get_by_role("dialog").get_by_role("textbox"),
                    "invitation note textbox",
                )
                dialog = textbox.locator("xpath=ancestor::*[self::dialog or @role='dialog'][1]")
                if await dialog.count() != 1 or not await dialog.is_visible():
                    raise ParserDriftError("Invitation note textbox has no unique visible dialog.")
                maximum = await self._invitation_note_limit(textbox, dialog)
                if len(command.payload.note) > maximum:
                    return await self._result(
                        page,
                        ActionOutcome.FAILED,
                        False,
                        "invitation_note_too_long",
                        "The requested note exceeds LinkedIn's current visible field limit.",
                    )
                await textbox.fill(command.payload.note)
                note_value = await textbox.input_value()
                note_count, note_limit = await self._invitation_note_counter(dialog)
                if (
                    note_value != command.payload.note
                    or note_count != len(command.payload.note)
                    or note_limit != maximum
                ):
                    return await self._result(
                        page,
                        ActionOutcome.FAILED,
                        False,
                        "invitation_note_not_committed",
                        (
                            "The exact requested note was not visibly committed to LinkedIn's "
                            "textbox and character counter."
                        ),
                    )
            send = dialog.get_by_role(
                "button",
                name=(
                    re.compile(r"^send invitation$", re.I)
                    if command.payload.note
                    else re.compile(r"^send without a note$", re.I)
                ),
            )
            if await send.count() != 1:
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "invitation_send_unavailable",
                    "The visible invitation dialog has no unique supported Send control.",
                )
            if not await send.is_visible() or not await send.is_enabled():
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "invitation_send_not_actionable",
                    "The visible Send control is disabled or not actionable.",
                )
            try:
                await send.click(trial=True, timeout=2_000)
            except PlaywrightError:
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "invitation_send_not_actionable",
                    "The visible Send control did not pass Playwright's actionability checks.",
                )
            verification_source_url = HttpUrl(page.url)
            verification_captured_text = (
                f"{await _visible_text(page)}\n{await dialog.inner_text()}".strip()
            )
            verification_captured_at = datetime.now(UTC)
            try:
                await self._browser.click_visible_control(page, send)
            except LinkedInMCPError as error:
                if error.pause_required:
                    raise
                return self._captured_result(
                    ActionOutcome.UNCERTAIN,
                    None,
                    "invitation_outcome_unknown",
                    (
                        "The final Send click did not complete, so its outcome could not be "
                        f"verified: {error.safe_message}"
                    ),
                    source_url=verification_source_url,
                    captured_text=verification_captured_text,
                    captured_at=verification_captured_at,
                )
            except Exception:
                return self._captured_result(
                    ActionOutcome.UNCERTAIN,
                    None,
                    "invitation_outcome_unknown",
                    "The final Send click did not complete, so its outcome could not be verified.",
                    source_url=verification_source_url,
                    captured_text=verification_captured_text,
                    captured_at=verification_captured_at,
                )
            try:
                await self._browser.navigate(
                    page,
                    canonical_profile_url(command.target.profile_slug),
                )
                main, fresh_name = await self._profile_identity(page)
                state, _ = await self._wait_for_connect_control(page, main, fresh_name)
            except LinkedInMCPError as error:
                if error.pause_required:
                    raise
                return self._captured_result(
                    ActionOutcome.UNCERTAIN,
                    None,
                    "invitation_outcome_unknown",
                    (
                        "The final Send click completed, but the fresh profile verification "
                        f"failed: {error.safe_message}"
                    ),
                    source_url=verification_source_url,
                    captured_text=verification_captured_text,
                    captured_at=verification_captured_at,
                )
            except Exception:
                return self._captured_result(
                    ActionOutcome.UNCERTAIN,
                    None,
                    "invitation_outcome_unknown",
                    "The final Send click completed, but the fresh profile could not be read.",
                    source_url=verification_source_url,
                    captured_text=verification_captured_text,
                    captured_at=verification_captured_at,
                )
            if fresh_name.casefold() != command.target.display_name.casefold():
                return await self._result(
                    page,
                    ActionOutcome.UNCERTAIN,
                    None,
                    "invitation_outcome_unknown",
                    "The fresh profile identity did not match the requested invitation target.",
                )
            if state == "pending_sent":
                return await self._result(
                    page,
                    ActionOutcome.VERIFIED,
                    True,
                    "pending_sent",
                    "A fresh exact-profile read visibly shows the invitation as Pending.",
                )
            if state == "connect_available":
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "invitation_not_sent",
                    (
                        "The fresh exact-profile read still shows Connect, so LinkedIn did not "
                        "send the invitation."
                    ),
                )
            return await self._result(
                page,
                ActionOutcome.UNCERTAIN,
                None,
                "invitation_outcome_unknown",
                (
                    "The fresh exact-profile read showed neither Pending nor a visible Connect "
                    f"action; the observed state was {state}."
                ),
            )

    async def perform_accept(self, command: ActionCommand) -> ActionPageResult:
        if not isinstance(command.payload, InvitationAcceptPayload):
            raise InvalidTargetError("The acceptance action payload is invalid.")
        expected_ref = _received_invitation_ref(command.target.profile_slug)
        if command.payload.invitation_ref != expected_ref:
            raise InvalidTargetError("The acceptance payload does not match the target invitation.")
        async with self._browser.page() as page:
            await self._browser.navigate(
                page,
                canonical_profile_url(command.target.profile_slug),
            )
            main, name = await self._profile_identity(page)
            if name.casefold() != command.target.display_name.casefold():
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "target_identity_changed",
                    "The exact profile name changed after inspection.",
                )
            accept, ignore = await self._incoming_request_controls(main, name)
            if accept is None or ignore is None:
                state, _ = await self._wait_for_connect_control(page, main, name)
                if state == "already_connected":
                    return await self._result(
                        page,
                        ActionOutcome.VERIFIED,
                        False,
                        "already_connected",
                        "The exact profile already visibly shows a first-degree connection.",
                    )
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "invitation_no_longer_pending",
                    "The exact profile no longer exposes the requested incoming request.",
                )
            try:
                await self._browser.click_visible_control(page, accept)
            except Exception:
                return await self._result(
                    page,
                    ActionOutcome.UNCERTAIN,
                    None,
                    "acceptance_outcome_unknown",
                    "Accept was invoked, but LinkedIn's result could not be verified.",
                )
            for _ in range(20):
                current_accept, current_ignore = await self._incoming_request_controls(main, name)
                state, _ = await self._connect_control(page, main, name)
                if (
                    current_accept is None
                    and current_ignore is None
                    and state == "already_connected"
                ):
                    return await self._result(
                        page,
                        ActionOutcome.VERIFIED,
                        True,
                        "connected",
                        (
                            "The exact profile removed the incoming-request controls and "
                            "visibly shows a first-degree connection."
                        ),
                    )
                await page.wait_for_timeout(250)
            await self._browser.navigate(
                page,
                canonical_profile_url(command.target.profile_slug),
            )
            main, visible_name = await self._profile_identity(page)
            current_accept, current_ignore = await self._incoming_request_controls(
                main,
                visible_name,
            )
            state, _ = await self._wait_for_connect_control(page, main, visible_name)
            if (
                visible_name.casefold() == command.target.display_name.casefold()
                and current_accept is None
                and current_ignore is None
                and state == "already_connected"
            ):
                return await self._result(
                    page,
                    ActionOutcome.VERIFIED,
                    True,
                    "connected",
                    (
                        "A fresh exact-profile read shows no incoming-request controls "
                        "and visibly proves a first-degree connection."
                    ),
                )
            return await self._result(
                page,
                ActionOutcome.UNCERTAIN,
                None,
                "acceptance_outcome_unknown",
                (
                    "Accept was invoked, but a fresh exact-profile read did not visibly prove "
                    "both request removal and the first-degree connection state."
                ),
            )

    async def perform_ignore(self, command: ActionCommand) -> ActionPageResult:
        if not isinstance(command.payload, InvitationIgnorePayload):
            raise InvalidTargetError("The ignore action payload is invalid.")
        expected_ref = _received_invitation_ref(command.target.profile_slug)
        if command.payload.invitation_ref != expected_ref:
            raise InvalidTargetError("The ignore payload does not match the target invitation.")
        async with self._browser.page() as page:
            await self._browser.navigate(
                page,
                canonical_profile_url(command.target.profile_slug),
            )
            main, name = await self._profile_identity(page)
            if name.casefold() != command.target.display_name.casefold():
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "target_identity_changed",
                    "The exact profile name changed after inspection.",
                )
            accept, ignore = await self._incoming_request_controls(main, name)
            if accept is None or ignore is None:
                return await self._result(
                    page,
                    ActionOutcome.FAILED,
                    False,
                    "invitation_no_longer_pending",
                    "The exact profile no longer exposes the requested incoming request.",
                )
            try:
                await self._browser.click_visible_control(page, ignore)
            except Exception:
                return await self._result(
                    page,
                    ActionOutcome.UNCERTAIN,
                    None,
                    "ignore_outcome_unknown",
                    "Ignore was invoked, but LinkedIn's result could not be verified.",
                )
            for _ in range(20):
                current_accept, current_ignore = await self._incoming_request_controls(main, name)
                if current_accept is None and current_ignore is None:
                    break
                await page.wait_for_timeout(250)
            await self._browser.navigate(
                page,
                canonical_profile_url(command.target.profile_slug),
            )
            main, visible_name = await self._profile_identity(page)
            current_accept, current_ignore = await self._incoming_request_controls(
                main,
                visible_name,
            )
            state, _ = await self._wait_for_connect_control(page, main, visible_name)
            if (
                visible_name.casefold() == command.target.display_name.casefold()
                and current_accept is None
                and current_ignore is None
                and state not in {"already_connected", "pending_sent"}
            ):
                return await self._result(
                    page,
                    ActionOutcome.VERIFIED,
                    True,
                    "invitation_ignored",
                    (
                        "A fresh exact-profile read shows the incoming-request controls "
                        "are gone with neither a connection nor an outgoing request."
                    ),
                )
            return await self._result(
                page,
                ActionOutcome.UNCERTAIN,
                None,
                "ignore_outcome_unknown",
                (
                    "Ignore was invoked, but a fresh exact-profile read did not visibly prove "
                    "request removal without creating a connection."
                ),
            )

    async def _connect_control(
        self,
        page: Page,
        main: Locator,
        profile_name: str,
    ) -> tuple[str, Locator | None]:
        visible = await _visible_text(page)
        pending = main.get_by_role(
            "button",
            name=re.compile(r"^(?:pending|invitation sent)", re.I),
        )
        if await pending.count() > 0 or re.search(
            r"\bpending\b", "\n".join(_lines(visible)[:20]), re.I
        ):
            return "pending_sent", None
        top_text = "\n".join(_lines(visible)[:30])
        message_actions = (
            main.get_by_role("button", name=re.compile(r"^message\b", re.I)),
            main.get_by_role("link", name=re.compile(r"^message\b", re.I)),
        )
        message_count = 0
        for action in message_actions:
            message_count += await action.count()
        if re.search(r"\b1st\b", top_text) and message_count > 0:
            return "already_connected", None
        exact_invite_button = main.get_by_role(
            "button",
            name=re.compile(
                rf"^invite\s+{re.escape(profile_name)}\s+to\s+connect$",
                re.I,
            ),
        )
        visible_exact_invite_buttons = [
            exact_invite_button.nth(index)
            for index in range(await exact_invite_button.count())
            if await exact_invite_button.nth(index).is_visible()
        ]
        if len(visible_exact_invite_buttons) > 1:
            raise ParserDriftError(
                "The exact profile exposes ambiguous visible invitation buttons."
            )
        if visible_exact_invite_buttons:
            return "connect_available", visible_exact_invite_buttons[0]
        direct = main.get_by_role(
            "button",
            name=re.compile(r"^(?:connect|connect with .+)$", re.I),
        )
        visible_direct = [
            direct.nth(index)
            for index in range(await direct.count())
            if await direct.nth(index).is_visible()
        ]
        if len(visible_direct) == 1:
            return "connect_available", visible_direct[0]
        if len(visible_direct) > 1:
            raise ParserDriftError("The exact profile exposes ambiguous visible Connect controls.")
        expected_slug = profile_slug_from_url(page.url)
        invite_links = main.get_by_role(
            "link",
            name=re.compile(r"^invite .+ to connect$", re.I),
        )
        exact_invite_links: list[Locator] = []
        for index in range(await invite_links.count()):
            candidate = invite_links.nth(index)
            if not await candidate.is_visible():
                continue
            href = await candidate.get_attribute("href")
            if not href or expected_slug is None:
                continue
            parsed = urlsplit(urljoin(page.url, href))
            vanity_name = parse_qs(parsed.query).get("vanityName", [None])[0]
            if (
                parsed.path.rstrip("/") == "/preload/custom-invite"
                and vanity_name is not None
                and vanity_name.casefold() == expected_slug.casefold()
            ):
                exact_invite_links.append(candidate)
        if len(exact_invite_links) > 1:
            raise ParserDriftError("The exact profile exposes ambiguous visible invitation links.")
        if exact_invite_links:
            return "connect_available", exact_invite_links[0]
        more = main.get_by_role("button", name=re.compile(r"^more(?: actions)?$", re.I))
        if await more.count() == 1:
            await self._browser.click_visible_control(page, more)
            menu_connect = page.get_by_role(
                "menuitem",
                name=re.compile(r"^connect(?: with .+)?$", re.I),
            )
            if await menu_connect.count() == 1:
                return "connect_available", menu_connect
            await page.keyboard.press("Escape")
        return "connect_unavailable", None

    async def _wait_for_connect_control(
        self,
        page: Page,
        main: Locator,
        profile_name: str,
    ) -> tuple[str, Locator | None]:
        """Wait for LinkedIn's asynchronously hydrated profile actions."""

        result: tuple[str, Locator | None] = ("connect_unavailable", None)
        for attempt_index in range(_PROFILE_ACTION_SETTLE_ATTEMPTS):
            result = await self._connect_control(page, main, profile_name)
            if result[0] != "connect_unavailable":
                return result
            if attempt_index + 1 < _PROFILE_ACTION_SETTLE_ATTEMPTS:
                await page.wait_for_timeout(_PROFILE_ACTION_SETTLE_DELAY_MS)
        return result

    @staticmethod
    async def _profile_identity(page: Page) -> tuple[Locator, str]:
        main = page.locator("main")
        try:
            await main.first.wait_for(state="visible")
        except PlaywrightTimeoutError as error:
            raise ParserDriftError("LinkedIn member profile did not render.") from error
        headings = main.get_by_role("heading")
        for index in range(min(await headings.count(), 10)):
            value = (await headings.nth(index).inner_text()).strip()
            lines = _lines(value)
            if lines and len(lines[0]) <= 500:
                return main, lines[0]
        raise ParserDriftError("LinkedIn member profile has no visible identity heading.")

    @staticmethod
    async def _incoming_request_controls(
        main: Locator,
        name: str,
    ) -> tuple[Locator | None, Locator | None]:
        escaped_name = re.escape(name)
        possessive = r"(?:'|\u2019)s"
        accept = await _optional_unique_visible(
            main.get_by_role(
                "button",
                name=re.compile(
                    rf"^accept {escaped_name}{possessive} request to connect$",
                    re.I,
                ),
            ),
            "incoming-request Accept control",
        )
        ignore = await _optional_unique_visible(
            main.get_by_role(
                "button",
                name=re.compile(
                    rf"^ignore {escaped_name}{possessive} request to connect$",
                    re.I,
                ),
            ),
            "incoming-request Ignore control",
        )
        if (accept is None) != (ignore is None):
            raise ParserDriftError(
                "The exact profile exposes an incomplete incoming-request action pair."
            )
        return accept, ignore

    @staticmethod
    async def _invitation_note_limit(textbox: Locator, dialog: Locator) -> int:
        limits: set[int] = set()
        maximum = await textbox.get_attribute("maxlength")
        if maximum is not None:
            try:
                limits.add(int(maximum))
            except ValueError as error:
                raise ParserDriftError(
                    "LinkedIn exposed an invalid invitation-note maxlength."
                ) from error
        for match in re.finditer(r"\b\d+\s*/\s*(?P<maximum>\d+)\b", await dialog.inner_text()):
            limits.add(int(match.group("maximum")))
        if len(limits) != 1:
            raise ParserDriftError(
                "LinkedIn exposed no unique visible invitation-note character limit."
            )
        return limits.pop()

    @staticmethod
    async def _invitation_note_counter(dialog: Locator) -> tuple[int, int]:
        counters = {
            (int(match.group("current")), int(match.group("maximum")))
            for match in re.finditer(
                r"\b(?P<current>\d+)\s*/\s*(?P<maximum>\d+)\b",
                await dialog.inner_text(),
            )
        }
        if len(counters) != 1:
            raise ParserDriftError(
                "LinkedIn exposed no unique visible invitation-note character counter."
            )
        return counters.pop()

    @staticmethod
    def _captured_result(
        outcome: ActionOutcome,
        performed: bool | None,
        final_state: str,
        detail: str,
        *,
        source_url: HttpUrl,
        captured_text: str,
        captured_at: datetime,
    ) -> ActionPageResult:
        return ActionPageResult(
            outcome=outcome,
            performed=performed,
            final_state=final_state,
            detail=detail,
            source_url=source_url,
            captured_text=captured_text,
            captured_at=captured_at,
        )

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
