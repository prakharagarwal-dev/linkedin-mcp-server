"""Visible profile mechanics shared by invitation action pages."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urljoin, urlsplit

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import HttpUrl

from linkedin_mcp.errors import InvalidTargetError, ParserDriftError
from linkedin_mcp.tools._shared.actions import (
    ActionInspection,
    ActionOutcome,
    ActionPageResult,
    ActionTarget,
)
from linkedin_mcp.tools._shared.browser import BrowserManager
from linkedin_mcp.tools._shared.urls import canonical_profile_url, profile_slug_from_url

_PROFILE_ACTION_SETTLE_ATTEMPTS = 24

_PROFILE_ACTION_SETTLE_DELAY_MS = 250


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


class InvitationActionSurface:
    """Shared visible-surface mechanics for InvitationActionSurface."""

    def __init__(self, browser: BrowserManager) -> None:
        self._browser = browser

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
