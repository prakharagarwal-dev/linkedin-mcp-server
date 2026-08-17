"""Lazy, serialized Playwright browser management for one LinkedIn account."""

from __future__ import annotations

import asyncio
import re
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
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from linkedin_mcp.browser.bootstrap import BrowserRuntimeBootstrap, BrowserSetupState
from linkedin_mcp.browser.profile import BrowserProfileManager
from linkedin_mcp.browser.runtime import BrowserRuntime
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import (
    AccessPausedError,
    AuthenticationRequiredError,
    BrowserUnavailableError,
    LinkedInMCPError,
    ParserDriftError,
    RestrictionDetectedError,
)
from linkedin_mcp.tools._shared.authentication import AuthenticationCoordinator
from linkedin_mcp.tools._shared.pacing import NavigationPacer
from linkedin_mcp.tools._shared.safety import assert_safe_linkedin_page
from linkedin_mcp.tools._shared.status import SessionAuthenticationState
from linkedin_mcp.tools._shared.urls import validate_linkedin_url

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
_LOGOUT_VERIFICATION_MESSAGE = "LinkedIn logout did not survive a clean browser restart."


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
    """Coordinate LinkedIn session safety over the generic browser runtime."""

    def __init__(
        self,
        settings: Settings,
        *,
        browser_bootstrap: BrowserRuntimeBootstrap | None = None,
        browser_profile: BrowserProfileManager | None = None,
        login_runner: LoginRunner | None = None,
    ) -> None:
        self._settings = settings
        self._runtime = BrowserRuntime(
            settings,
            browser_bootstrap=browser_bootstrap,
            browser_profile=browser_profile,
        )
        self._login_runner = login_runner
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
        return self._runtime.started

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
        return self._runtime.setup_state

    def profile_present(self) -> bool:
        return self._runtime.profile_present()

    def start_session_bootstrap(self) -> None:
        self._runtime.start_setup()
        self._authentication.start()

    def pause(self, reason: str) -> None:
        self._paused = True
        self._pause_reason = reason

    def resume(self) -> None:
        self._paused = False
        self._pause_reason = None

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        await self._authentication.ensure_ready()
        if self._paused:
            raise AccessPausedError(
                f"LinkedIn access is paused: {self._pause_reason or 'operator review required'}"
            )
        async with self._runtime.page() as page:
            yield page

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

    async def close(self) -> None:
        await self._authentication.close()
        await self._runtime.close()
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
        await self._runtime.stop()

    async def _login_for_authentication(self) -> None:
        runner = self._login_runner or login_interactively
        try:
            await self._runtime.ensure_profile()
            await runner(self._settings, self._runtime.bootstrap)
        except LinkedInMCPError as error:
            if error.pause_required:
                self.pause(error.safe_message)
            raise

    async def _validate_saved_session(self) -> None:
        try:
            async with self._runtime.page() as page:
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
        self.resume()


async def login_interactively(
    settings: Settings,
    browser_bootstrap: BrowserRuntimeBootstrap | None = None,
) -> None:
    """Open a headed profile and prove its session survives a clean reopen."""

    bootstrap = browser_bootstrap or BrowserRuntimeBootstrap(settings)
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


async def logout_interactively(
    settings: Settings,
    browser_bootstrap: BrowserRuntimeBootstrap | None = None,
) -> bool:
    """Use LinkedIn's visible sign-out control and verify the persistent session ended."""

    bootstrap = browser_bootstrap or BrowserRuntimeBootstrap(settings)
    BrowserProfileManager(settings, bootstrap).require_initialized()
    await bootstrap.ensure_ready()
    pacer = NavigationPacer(
        account_id=settings.account_id,
        interval_seconds=settings.minimum_navigation_interval_seconds,
    )
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
        await pacer.wait()
        await page.goto(_SESSION_VALIDATION_URL, wait_until="domcontentloaded")
        cookies = await context.cookies("https://www.linkedin.com")
        has_session_cookie = any(cookie.get("name") == "li_at" for cookie in cookies)
        if not has_session_cookie and _is_logged_out_surface(page.url):
            return False
        await assert_safe_linkedin_page(page, settings.allowed_hosts)

        account_menu = await _unique_visible_control(
            page.get_by_role(
                "button",
                name=re.compile(r"^Me(?:\b|$)", re.IGNORECASE),
            ),
            missing_message="LinkedIn's visible account menu was unavailable for logout.",
            ambiguous_message="LinkedIn exposed multiple visible account menus for logout.",
        )
        await pacer.wait()
        await account_menu.click()
        sign_out = await _unique_visible_control(
            page.get_by_role(
                "link",
                name=re.compile(r"^Sign\s+Out$", re.IGNORECASE),
            ),
            missing_message="LinkedIn's visible Sign Out control was unavailable.",
            ambiguous_message="LinkedIn exposed multiple visible Sign Out controls.",
        )
        await pacer.wait()
        await sign_out.click()
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
        context.set_default_timeout(settings.browser_timeout_seconds * 1_000)
        context.set_default_navigation_timeout(settings.browser_timeout_seconds * 1_000)
        verification_page = await context.new_page()
        await pacer.wait()
        await verification_page.goto(_SESSION_VALIDATION_URL, wait_until="domcontentloaded")
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
        pacer.close()
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
