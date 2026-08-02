"""Lazy, serialized Playwright browser management for one LinkedIn account."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import structlog
from playwright.async_api import (
    BrowserContext,
    Cookie,
    Locator,
    Page,
    Playwright,
    async_playwright,
)

from linkedin_mcp.auth import AuthenticationCoordinator
from linkedin_mcp.browser.bootstrap import BrowserRuntimeBootstrap
from linkedin_mcp.browser.guard import assert_safe_linkedin_page
from linkedin_mcp.browser.pacing import NavigationPacer
from linkedin_mcp.config import Settings
from linkedin_mcp.domain.models import BrowserSetupState, SessionAuthenticationState
from linkedin_mcp.errors import (
    AuthenticationRequiredError,
    AuthorizationDeniedError,
    BrowserUnavailableError,
    LinkedInMCPError,
    RestrictionDetectedError,
)
from linkedin_mcp.policy import validate_linkedin_url

logger = structlog.get_logger(__name__)

LoginRunner = Callable[[Settings, BrowserRuntimeBootstrap], Awaitable[None]]
_SESSION_VALIDATION_URL = "https://www.linkedin.com/feed/"
_INTERACTIVE_AUTH_PATHS = ("/login", "/uas/login", "/checkpoint/", "/authwall")
_PROFILE_REOPEN_DELAY_SECONDS = 1.0
_DURABLE_LOGIN_REQUIRED_MESSAGE = (
    "LinkedIn login was not saved persistently. Keep 'Keep me signed in' enabled and sign in again."
)
_DURABLE_LOGIN_REOPEN_MESSAGE = (
    "LinkedIn login did not survive a clean browser restart. Keep "
    "'Keep me signed in' enabled and sign in again."
)


def _persistent_linkedin_session(cookies: list[Cookie]) -> bool:
    now = time.time()
    return any(
        cookie.get("name") == "li_at"
        and (expires := cookie.get("expires")) is not None
        and expires > now
        for cookie in cookies
    )


async def _enable_persistent_login(page: Page) -> None:
    """Select LinkedIn's visible remember-me control when the login UI exposes it."""

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


class BrowserManager:
    """Own one persistent LinkedIn browser profile and serialize page interactions."""

    def __init__(
        self,
        settings: Settings,
        *,
        browser_bootstrap: BrowserRuntimeBootstrap | None = None,
        login_runner: LoginRunner | None = None,
    ) -> None:
        self._settings = settings
        self._browser_bootstrap = browser_bootstrap or BrowserRuntimeBootstrap(settings)
        self._login_runner = login_runner
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._operation_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._pacer = NavigationPacer(
            account_id=settings.account_id,
            interval_seconds=settings.minimum_navigation_interval_seconds,
        )
        self._paused = False
        self._pause_reason: str | None = None
        self._authentication = AuthenticationCoordinator(
            automatic=settings.auto_login_on_start,
            state_present=self.profile_present,
            reset_session=self._reset_for_authentication,
            login=self._login_for_authentication,
            validate=self._validate_saved_session,
        )

    @property
    def started(self) -> bool:
        return self._playwright is not None and self._context is not None

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def pause_reason(self) -> str | None:
        return self._pause_reason

    @property
    def authentication_state(self) -> SessionAuthenticationState:
        return self._authentication.state

    @property
    def authentication_status_message(self) -> str | None:
        return self._authentication.status_message

    @property
    def login_browser_open(self) -> bool:
        return self._authentication.login_browser_open

    @property
    def browser_setup_state(self) -> BrowserSetupState:
        return self._browser_bootstrap.state

    def profile_present(self) -> bool:
        profile = self._settings.browser_profile_path
        return profile.is_dir() and any(profile.iterdir())

    def start_session_bootstrap(self) -> None:
        self._browser_bootstrap.start()
        self._authentication.start()

    def pause(self, reason: str) -> None:
        self._paused = True
        self._pause_reason = reason

    def resume(self) -> None:
        self._paused = False
        self._pause_reason = None

    async def _start(self, *, allow_paused: bool = False) -> BrowserContext:
        if self._paused and not allow_paused:
            raise AuthorizationDeniedError(
                f"LinkedIn access is paused: {self._pause_reason or 'operator review required'}"
            )
        if self.started:
            assert self._context is not None
            return self._context
        async with self._start_lock:
            if self.started:
                assert self._context is not None
                return self._context
            await self._close_browser(persist_state=False)
            await self._browser_bootstrap.ensure_ready()
            self._prepare_profile_directory()
            try:
                self._playwright = await async_playwright().start()
                self._context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self._settings.browser_profile_path),
                    headless=self._settings.browser_headless,
                )
                self._context.set_default_timeout(self._settings.browser_timeout_seconds * 1_000)
                self._context.set_default_navigation_timeout(
                    self._settings.browser_timeout_seconds * 1_000
                )
            except Exception as error:
                await self._close_browser(persist_state=False)
                raise BrowserUnavailableError("Chromium could not start.") from error
            return self._context

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        await self._authentication.ensure_ready()
        async with self._operation_lock:
            context = await self._start()
            existing_page_urls = {
                id(existing_page): existing_page.url
                for existing_page in context.pages
                if not existing_page.is_closed()
            }
            page = next(
                (
                    existing_page
                    for existing_page in context.pages
                    if not existing_page.is_closed() and existing_page.url == "about:blank"
                ),
                None,
            )
            if page is None:
                try:
                    page = await context.new_page()
                except Exception as error:
                    raise BrowserUnavailableError(
                        "A Chromium page could not be created."
                    ) from error
            try:
                yield page
            finally:
                owned_pages = [
                    candidate
                    for candidate in context.pages
                    if candidate is page
                    or id(candidate) not in existing_page_urls
                    or existing_page_urls[id(candidate)] != candidate.url
                ]
                for owned_page in reversed(owned_pages):
                    if not owned_page.is_closed():
                        await owned_page.close()

    async def navigate(self, page: Page, url: str) -> None:
        target = validate_linkedin_url(url, self._settings.allowed_hosts)
        await self._pacer.wait()
        try:
            await page.goto(target, wait_until="domcontentloaded")
            await assert_safe_linkedin_page(page, self._settings.allowed_hosts)
            self._authentication.mark_authenticated()
        except LinkedInMCPError as error:
            self._handle_access_error(error, page.url)
            raise

    async def navigate_via_visible_control(self, page: Page, control: Locator) -> str:
        """Pace and validate a navigation initiated by a narrow page-object control."""

        previous_url = page.url
        await self._pacer.wait()
        try:
            await control.click()
            await page.wait_for_url(
                lambda value: str(value) != previous_url,
                wait_until="domcontentloaded",
            )
            target = validate_linkedin_url(page.url, self._settings.allowed_hosts)
            await page.wait_for_timeout(1_000)
            stable_rounds = 0
            for _ in range(40):
                current = validate_linkedin_url(page.url, self._settings.allowed_hosts)
                if current == target:
                    stable_rounds += 1
                else:
                    target = current
                    stable_rounds = 0
                if stable_rounds >= 10:
                    break
                await page.wait_for_timeout(100)
            else:
                raise BrowserUnavailableError(
                    "LinkedIn visible-control navigation did not settle within its bound."
                )
            await assert_safe_linkedin_page(page, self._settings.allowed_hosts)
            self._authentication.mark_authenticated()
            return target
        except LinkedInMCPError as error:
            self._handle_access_error(error, page.url)
            raise

    async def click_visible_control(self, page: Page, control: Locator) -> None:
        """Pace one page-object-owned UI interaction and re-check account safety."""

        await self._pacer.wait()
        try:
            await control.click()
            await page.wait_for_timeout(300)
            await assert_safe_linkedin_page(page, self._settings.allowed_hosts)
            self._authentication.mark_authenticated()
        except LinkedInMCPError as error:
            self._handle_access_error(error, page.url)
            raise

    async def assert_safe(self, page: Page) -> None:
        try:
            await assert_safe_linkedin_page(page, self._settings.allowed_hosts)
            self._authentication.mark_authenticated()
        except LinkedInMCPError as error:
            self._handle_access_error(error, page.url)
            raise

    async def close(self, *, persist_state: bool = True) -> None:
        await self._authentication.close()
        await self._close_browser(persist_state=persist_state)
        await self._browser_bootstrap.close()
        self._pacer.close()

    def _handle_access_error(self, error: LinkedInMCPError, url: str) -> None:
        if error.pause_required:
            self.pause(error.safe_message)
        path = urlsplit(url).path.lower()
        interactive_auth_surface = any(marker in path for marker in _INTERACTIVE_AUTH_PATHS)
        if isinstance(error, AuthenticationRequiredError) or (
            isinstance(error, RestrictionDetectedError) and interactive_auth_surface
        ):
            self._authentication.request_reauthentication(error.safe_message)
        elif error.pause_required:
            self._authentication.mark_attention_required(error)

    async def _reset_for_authentication(self) -> None:
        async with self._operation_lock:
            await self._close_browser(persist_state=False)

    async def _login_for_authentication(self) -> None:
        runner = self._login_runner or login_interactively
        try:
            await runner(self._settings, self._browser_bootstrap)
        except LinkedInMCPError as error:
            if error.pause_required:
                self.pause(error.safe_message)
            raise

    async def _validate_saved_session(self) -> None:
        async with self._operation_lock:
            context = await self._start(allow_paused=True)
            try:
                page = await context.new_page()
            except Exception as error:
                raise BrowserUnavailableError(
                    "A Chromium page could not be created for session validation."
                ) from error
            try:
                target = validate_linkedin_url(
                    _SESSION_VALIDATION_URL,
                    self._settings.allowed_hosts,
                )
                await self._pacer.wait()
                await page.goto(target, wait_until="domcontentloaded")
                try:
                    await assert_safe_linkedin_page(page, self._settings.allowed_hosts)
                except RestrictionDetectedError as error:
                    path = urlsplit(page.url).path.lower()
                    if any(marker in path for marker in _INTERACTIVE_AUTH_PATHS):
                        raise AuthenticationRequiredError(
                            "LinkedIn requires login or human verification."
                        ) from error
                    raise
            except LinkedInMCPError as error:
                if error.pause_required:
                    self.pause(error.safe_message)
                raise
            except Exception as error:
                raise BrowserUnavailableError(
                    "The saved LinkedIn session could not be validated."
                ) from error
            finally:
                if not page.is_closed():
                    await page.close()
        self.resume()

    async def _close_browser(self, *, persist_state: bool) -> None:
        del persist_state
        context = self._context
        playwright = self._playwright
        self._context = None
        self._playwright = None
        if context is not None:
            await context.close()
        if playwright is not None:
            await playwright.stop()

    def _prepare_profile_directory(self) -> None:
        profile = self._settings.browser_profile_path
        profile.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            profile.chmod(0o700)


async def login_interactively(
    settings: Settings,
    browser_bootstrap: BrowserRuntimeBootstrap | None = None,
) -> None:
    """Open a headed profile and prove its session survives a clean reopen."""

    bootstrap = browser_bootstrap or BrowserRuntimeBootstrap(settings)
    await bootstrap.ensure_ready()
    settings.browser_profile_path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        settings.browser_profile_path.chmod(0o700)
    playwright: Playwright | None = None
    context: BrowserContext | None = None
    try:
        playwright = await async_playwright().start()
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(settings.browser_profile_path),
            headless=False,
        )
        context.set_default_timeout(settings.browser_timeout_seconds * 1_000)
        context.set_default_navigation_timeout(settings.browser_timeout_seconds * 1_000)
        page = context.pages[0] if context.pages else await context.new_page()
        deadline = time.monotonic() + settings.login_timeout_seconds
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        await _enable_persistent_login(page)
        while time.monotonic() < deadline:
            await asyncio.sleep(2)
            cookies = await context.cookies("https://www.linkedin.com")
            has_session_cookie = any(cookie.get("name") == "li_at" for cookie in cookies)
            path = page.url.lower()
            is_login_surface = any(
                marker in path for marker in ("/login", "/checkpoint", "/authwall")
            )
            if has_session_cookie and not is_login_surface:
                validate_linkedin_url(page.url, settings.allowed_hosts)
                await assert_safe_linkedin_page(page, settings.allowed_hosts)
                if not _persistent_linkedin_session(cookies):
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
        context.set_default_timeout(settings.browser_timeout_seconds * 1_000)
        context.set_default_navigation_timeout(settings.browser_timeout_seconds * 1_000)
        verification_page = await context.new_page()
        try:
            target = validate_linkedin_url(
                _SESSION_VALIDATION_URL,
                settings.allowed_hosts,
            )
            await verification_page.goto(target, wait_until="domcontentloaded")
            try:
                await assert_safe_linkedin_page(
                    verification_page,
                    settings.allowed_hosts,
                )
            except AuthenticationRequiredError as error:
                raise AuthenticationRequiredError(_DURABLE_LOGIN_REOPEN_MESSAGE) from error
            cookies = await context.cookies("https://www.linkedin.com")
            if not _persistent_linkedin_session(cookies):
                raise AuthenticationRequiredError(_DURABLE_LOGIN_REOPEN_MESSAGE)
        finally:
            if not verification_page.is_closed():
                await verification_page.close()
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
