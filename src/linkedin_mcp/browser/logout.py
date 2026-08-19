"""Visible LinkedIn logout and persistent-session verification."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urlsplit

import structlog
from playwright.async_api import BrowserContext, Locator, Playwright, async_playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from linkedin_mcp.browser.access import assert_linkedin_access
from linkedin_mcp.browser.bootstrap import BrowserBootstrap
from linkedin_mcp.browser.login import SESSION_VALIDATION_URL
from linkedin_mcp.browser.profile import BrowserProfileManager
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import (
    BrowserUnavailableError,
    LinkedInMCPError,
    ParserDriftError,
)
from linkedin_mcp.infra.playwright import Paced

logger = structlog.get_logger(__name__)

_PROFILE_REOPEN_DELAY_SECONDS = 1.0
_LOGOUT_VERIFICATION_MESSAGE = "LinkedIn logout did not survive a clean browser restart."


async def logout_interactively(
    settings: Settings,
    paced: Paced,
    browser_bootstrap: BrowserBootstrap | None = None,
) -> bool:
    """Use LinkedIn's visible sign-out control and verify the persistent session ended."""

    bootstrap = browser_bootstrap or BrowserBootstrap(settings)
    BrowserProfileManager(settings, bootstrap).require_initialized()
    await bootstrap.ensure_ready()
    playwright: Playwright | None = None
    context: BrowserContext | None = None
    try:
        playwright = await async_playwright().start()
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(settings.browser_profile_path),
            headless=False,
        )
        _set_timeouts(context, settings)
        page = context.pages[0] if context.pages else await context.new_page()
        await paced.goto(page, SESSION_VALIDATION_URL, wait_until="domcontentloaded")
        cookies = await context.cookies("https://www.linkedin.com")
        has_session_cookie = any(cookie.get("name") == "li_at" for cookie in cookies)
        if not has_session_cookie and _is_logged_out_surface(page.url):
            return False
        await assert_linkedin_access(page, settings.allowed_hosts)

        account_menu = await _unique_visible_control(
            page.get_by_role(
                "button",
                name=re.compile(r"^Me(?:\b|$)", re.IGNORECASE),
            ),
            missing_message="LinkedIn's visible account menu was unavailable for logout.",
            ambiguous_message="LinkedIn exposed multiple visible account menus for logout.",
        )
        await paced.click(account_menu)
        sign_out = await _unique_visible_control(
            page.get_by_role(
                "link",
                name=re.compile(r"^Sign\s+Out$", re.IGNORECASE),
            ),
            missing_message="LinkedIn's visible Sign Out control was unavailable.",
            ambiguous_message="LinkedIn exposed multiple visible Sign Out controls.",
        )
        await paced.click(sign_out)
        for _ in range(40):
            cookies = await context.cookies("https://www.linkedin.com")
            if not any(cookie.get("name") == "li_at" for cookie in cookies):
                break
            await page.wait_for_timeout(250)
        else:
            raise BrowserUnavailableError("LinkedIn did not clear the persistent login session.")

        await context.close()
        context = None
        await asyncio.sleep(_PROFILE_REOPEN_DELAY_SECONDS)
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(settings.browser_profile_path),
            headless=settings.browser_headless,
        )
        _set_timeouts(context, settings)
        verification_page = await context.new_page()
        await paced.goto(
            verification_page,
            SESSION_VALIDATION_URL,
            wait_until="domcontentloaded",
        )
        cookies = await context.cookies("https://www.linkedin.com")
        if any(cookie.get("name") == "li_at" for cookie in cookies):
            raise BrowserUnavailableError(_LOGOUT_VERIFICATION_MESSAGE)
        if not _is_logged_out_surface(verification_page.url):
            raise BrowserUnavailableError(_LOGOUT_VERIFICATION_MESSAGE)
        logger.info("linkedin_persistent_logout_verified")
        return True
    except LinkedInMCPError:
        raise
    except PlaywrightTimeoutError as error:
        raise BrowserUnavailableError("The interactive LinkedIn logout timed out.") from error
    except Exception as error:
        raise BrowserUnavailableError("The interactive LinkedIn logout browser failed.") from error
    finally:
        if context is not None:
            await context.close()
        if playwright is not None:
            await playwright.stop()


def _is_logged_out_surface(url: str) -> bool:
    path = urlsplit(url).path.casefold()
    return any(marker in path for marker in ("/login", "/uas/login", "/authwall"))


async def _unique_visible_control(
    controls: Locator,
    *,
    missing_message: str,
    ambiguous_message: str,
) -> Locator:
    visible: list[Locator] = []
    for index in range(await controls.count()):
        candidate = controls.nth(index)
        if await candidate.is_visible():
            visible.append(candidate)
    if not visible:
        raise ParserDriftError(missing_message)
    if len(visible) != 1:
        raise ParserDriftError(ambiguous_message)
    return visible[0]


def _set_timeouts(context: BrowserContext, settings: Settings) -> None:
    timeout_ms = settings.browser_timeout_seconds * 1_000
    context.set_default_timeout(timeout_ms)
    context.set_default_navigation_timeout(timeout_ms)
