"""Visible LinkedIn login and persistent-session verification."""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlsplit

import structlog
from playwright.async_api import BrowserContext, Cookie, Page, Playwright, async_playwright

from linkedin_mcp.browser.bootstrap import BrowserBootstrap
from linkedin_mcp.browser.profile import BrowserProfileManager
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import (
    AuthenticationRequiredError,
    BrowserUnavailableError,
    LinkedInMCPError,
    RestrictionDetectedError,
)
from linkedin_mcp.ui.safety import assert_safe_linkedin_page
from linkedin_mcp.ui.urls import validate_linkedin_url

logger = structlog.get_logger(__name__)

SESSION_VALIDATION_URL = "https://www.linkedin.com/feed/"
_LOGIN_PATHS = ("/login", "/uas/login", "/authwall")
_PROFILE_REOPEN_DELAY_SECONDS = 1.0
_DURABLE_LOGIN_REQUIRED_MESSAGE = (
    "LinkedIn login was not saved persistently. Keep 'Keep me signed in' enabled and sign in again."
)
_DURABLE_LOGIN_REOPEN_MESSAGE = (
    "LinkedIn login did not survive a clean browser restart. Keep "
    "'Keep me signed in' enabled and sign in again."
)


def persistent_linkedin_session(cookies: list[Cookie]) -> bool:
    now = time.time()
    return any(
        cookie.get("name") == "li_at"
        and (expires := cookie.get("expires")) is not None
        and expires > now
        for cookie in cookies
    )


async def validate_saved_session(context: BrowserContext, settings: Settings) -> None:
    """Prove that the persistent context has a currently usable LinkedIn session."""

    page = await context.new_page()
    try:
        target = validate_linkedin_url(SESSION_VALIDATION_URL, settings.allowed_hosts)
        await page.goto(target, wait_until="domcontentloaded")
        try:
            await assert_safe_linkedin_page(page, settings.allowed_hosts)
        except RestrictionDetectedError as error:
            path = urlsplit(page.url).path.lower()
            if any(path.startswith(marker) for marker in _LOGIN_PATHS):
                raise AuthenticationRequiredError("LinkedIn login is required.") from error
            raise
        cookies = await context.cookies("https://www.linkedin.com")
        if not persistent_linkedin_session(cookies):
            raise AuthenticationRequiredError("The saved LinkedIn session is missing or expired.")
    except LinkedInMCPError:
        raise
    except Exception as error:
        raise BrowserUnavailableError(
            "The saved LinkedIn session could not be validated."
        ) from error
    finally:
        if not page.is_closed():
            await page.close()


async def login_interactively(
    settings: Settings,
    browser_bootstrap: BrowserBootstrap | None = None,
) -> None:
    """Open a headed profile and prove its session survives a clean reopen."""

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
        deadline = time.monotonic() + settings.login_timeout_seconds
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        await _enable_persistent_login(page)
        while time.monotonic() < deadline:
            await asyncio.sleep(2)
            cookies = await context.cookies("https://www.linkedin.com")
            has_session_cookie = any(cookie.get("name") == "li_at" for cookie in cookies)
            path = urlsplit(page.url).path.lower()
            if "/checkpoint/" in path:
                raise RestrictionDetectedError(
                    "LinkedIn presented a security checkpoint during login."
                )
            is_login_surface = any(path.startswith(marker) for marker in _LOGIN_PATHS)
            if has_session_cookie and not is_login_surface:
                validate_linkedin_url(page.url, settings.allowed_hosts)
                await assert_safe_linkedin_page(page, settings.allowed_hosts)
                if not persistent_linkedin_session(cookies):
                    raise AuthenticationRequiredError(_DURABLE_LOGIN_REQUIRED_MESSAGE)
                break
        else:
            raise AuthenticationRequiredError("LinkedIn login did not complete before the timeout.")

        await context.close()
        context = None
        await asyncio.sleep(_PROFILE_REOPEN_DELAY_SECONDS)

        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(settings.browser_profile_path),
            headless=settings.browser_headless,
        )
        _set_timeouts(context, settings)
        try:
            await validate_saved_session(context, settings)
        except AuthenticationRequiredError as error:
            raise AuthenticationRequiredError(_DURABLE_LOGIN_REOPEN_MESSAGE) from error
        logger.info(
            "linkedin_persistent_login_verified",
            verification_headless=settings.browser_headless,
        )
    except LinkedInMCPError:
        raise
    except Exception as error:
        raise BrowserUnavailableError("The interactive LinkedIn login browser failed.") from error
    finally:
        if context is not None:
            await context.close()
        if playwright is not None:
            await playwright.stop()


async def _enable_persistent_login(page: Page) -> None:
    remember_me = page.get_by_role(
        "checkbox",
        name="Keep me signed in",
        exact=False,
    )
    try:
        if await remember_me.count() == 0:
            return
        checkbox = remember_me.first
        if await checkbox.is_visible() and not await checkbox.is_checked():
            await checkbox.check(timeout=2_000)
    except Exception as error:
        logger.debug(
            "linkedin_persistent_login_control_unavailable",
            error_type=type(error).__name__,
        )


def _set_timeouts(context: BrowserContext, settings: Settings) -> None:
    timeout_ms = settings.browser_timeout_seconds * 1_000
    context.set_default_timeout(timeout_ms)
    context.set_default_navigation_timeout(timeout_ms)
