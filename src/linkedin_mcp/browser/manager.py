"""Lifecycle owner for one persistent Playwright Chromium context."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from enum import StrEnum
from urllib.parse import urlsplit

import structlog
from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from linkedin_mcp.browser.access import assert_linkedin_access
from linkedin_mcp.browser.bootstrap import BrowserBootstrap, BrowserSetupState
from linkedin_mcp.browser.login import login_interactively, validate_saved_session
from linkedin_mcp.browser.logout import logout_interactively
from linkedin_mcp.browser.profile import BrowserProfileManager
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import (
    AccessPausedError,
    AuthenticationRequiredError,
    BrowserUnavailableError,
    LinkedInMCPError,
    RestrictionDetectedError,
)
from linkedin_mcp.infra.playwright import Paced

logger = structlog.get_logger(__name__)

PageFactory = Callable[[], AbstractAsyncContextManager[Page]]
AccessHook = Callable[[Page], Awaitable[None]]

_INTERACTIVE_AUTH_PATHS = ("/login", "/uas/login", "/checkpoint/", "/authwall")


class AuthenticationState(StrEnum):
    """Process-local authentication state observed by the browser manager."""

    LOGIN_REQUIRED = "login_required"
    AUTHENTICATED = "authenticated"
    ATTENTION_REQUIRED = "attention_required"


class BrowserManager:
    """Start, authenticate, expose pages from, and close one Chromium context."""

    def __init__(
        self,
        settings: Settings,
        paced: Paced,
        *,
        browser_bootstrap: BrowserBootstrap | None = None,
        browser_profile: BrowserProfileManager | None = None,
    ) -> None:
        self._settings = settings
        self._paced = paced
        self._bootstrap: BrowserBootstrap | None = browser_bootstrap or BrowserBootstrap(settings)
        self._profile: BrowserProfileManager | None = browser_profile or BrowserProfileManager(
            settings,
            self._bootstrap,
        )
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page_factory: PageFactory | None = None
        self._access_hook: AccessHook | None = None
        self._setup_state_override: BrowserSetupState | None = None
        self._profile_present_override: bool | None = None
        self._authentication_state = AuthenticationState.AUTHENTICATED
        self._authentication_status_message: str | None = None
        self._paused = False
        self._pause_reason: str | None = None

    @classmethod
    def for_testing(
        cls,
        settings: Settings,
        paced: Paced,
        *,
        page_factory: PageFactory,
        assert_access: AccessHook | None = None,
    ) -> BrowserManager:
        """Create browser wiring around an offline raw-page provider."""

        instance = cls.__new__(cls)
        instance._settings = settings
        instance._paced = paced
        instance._bootstrap = None
        instance._profile = None
        instance._playwright = None
        instance._context = None
        instance._page_factory = page_factory
        instance._access_hook = assert_access
        instance._setup_state_override = BrowserSetupState.READY
        instance._profile_present_override = True
        instance._authentication_state = AuthenticationState.AUTHENTICATED
        instance._authentication_status_message = None
        instance._paused = False
        instance._pause_reason = None
        return instance

    @property
    def paced(self) -> Paced:
        return self._paced

    @property
    def started(self) -> bool:
        return self._context is not None or self._page_factory is not None

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def pause_reason(self) -> str | None:
        return self._pause_reason

    @property
    def authentication_state(self) -> AuthenticationState:
        return self._authentication_state

    @property
    def authentication_status_message(self) -> str | None:
        return self._authentication_status_message

    @property
    def setup_state(self) -> BrowserSetupState:
        override = self._setup_state_override
        if override is not None:
            return override
        bootstrap = self._bootstrap
        if bootstrap is None:
            return BrowserSetupState.READY
        return bootstrap.state

    @property
    def browser_setup_state(self) -> BrowserSetupState:
        return self.setup_state

    def profile_present(self) -> bool:
        override = self._profile_present_override
        if override is not None:
            return override
        profile = self._profile
        return profile is not None and profile.inspect().initialized

    async def start(self) -> BrowserContext:
        """Start Chromium and synchronously establish a usable LinkedIn session."""

        if self._context is not None:
            return self._context
        profile = self._profile
        bootstrap = self._bootstrap
        if profile is None or bootstrap is None:
            raise BrowserUnavailableError("The offline browser provider cannot be started.")
        profile.require_initialized()
        context = await self._open_context()
        try:
            await validate_saved_session(context, self._settings, self._paced)
        except AuthenticationRequiredError:
            await self._close_browser()
            await login_interactively(self._settings, self._paced, bootstrap)
            context = await self._open_context()
            await validate_saved_session(context, self._settings, self._paced)
        self._mark_authenticated()
        return context

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        """Yield one task page and close every page opened by that task."""

        self._ensure_available()
        page_factory = self._page_factory
        if page_factory is not None:
            async with page_factory() as page:
                try:
                    yield page
                except LinkedInMCPError as error:
                    self._record_access_error(error, page.url)
                    raise
                else:
                    await self._observe_access(page)
            return

        context = self._context
        if context is None:
            raise BrowserUnavailableError("The Playwright browser context is not running.")
        existing_page_urls = {
            id(existing): existing.url for existing in context.pages if not existing.is_closed()
        }
        try:
            page = await context.new_page()
        except Exception as error:
            raise BrowserUnavailableError("A Chromium page could not be created.") from error
        try:
            try:
                yield page
            except LinkedInMCPError as error:
                self._record_access_error(error, page.url)
                raise
            else:
                await self._observe_access(page)
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

    async def login(self) -> None:
        """Close any owned context and perform one visible persistent login."""

        await self._close_browser()
        bootstrap = self._bootstrap
        if bootstrap is None:
            raise BrowserUnavailableError("The offline browser provider cannot log in.")
        await login_interactively(self._settings, self._paced, bootstrap)
        self._mark_authenticated()

    async def logout(self) -> bool:
        """Close any owned context and perform one visible persistent logout."""

        await self._close_browser()
        bootstrap = self._bootstrap
        if bootstrap is None:
            raise BrowserUnavailableError("The offline browser provider cannot log out.")
        logged_out = await logout_interactively(self._settings, self._paced, bootstrap)
        self._authentication_state = AuthenticationState.LOGIN_REQUIRED
        self._authentication_status_message = "LinkedIn login is required."
        return logged_out

    async def close(self) -> None:
        self._page_factory = None
        await self._close_browser()

    async def _observe_access(self, page: Page) -> None:
        try:
            hook = self._access_hook
            if hook is not None:
                await hook(page)
            elif self._page_factory is not None:
                self._mark_authenticated()
                return
            else:
                await assert_linkedin_access(page, self._settings.allowed_hosts)
            self._mark_authenticated()
        except LinkedInMCPError as error:
            self._record_access_error(error, page.url)
            raise

    async def _open_context(self) -> BrowserContext:
        await self._close_browser()
        bootstrap = self._bootstrap
        profile = self._profile
        if bootstrap is None or profile is None:
            raise BrowserUnavailableError("The browser profile is unavailable.")
        await bootstrap.ensure_ready()
        profile.require_initialized()
        try:
            self._playwright = await async_playwright().start()
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self._settings.browser_profile_path),
                headless=self._settings.browser_headless,
            )
            timeout_ms = self._settings.browser_timeout_seconds * 1_000
            self._context.set_default_timeout(timeout_ms)
            self._context.set_default_navigation_timeout(timeout_ms)
        except Exception as error:
            await self._close_browser()
            raise BrowserUnavailableError("Chromium could not start.") from error
        return self._context

    async def _close_browser(self) -> None:
        context = self._context
        playwright = self._playwright
        self._context = None
        self._playwright = None
        try:
            if context is not None:
                await context.close()
        finally:
            if playwright is not None:
                await playwright.stop()

    def _ensure_available(self) -> None:
        if self._authentication_state is AuthenticationState.LOGIN_REQUIRED:
            raise AuthenticationRequiredError(
                self._authentication_status_message or "LinkedIn authentication is required."
            )
        if self._paused:
            raise AccessPausedError(
                f"LinkedIn access is paused: {self._pause_reason or 'operator review required'}"
            )

    def _record_access_error(self, error: LinkedInMCPError, url: str) -> None:
        if error.pause_required:
            self._paused = True
            self._pause_reason = error.safe_message
        path = urlsplit(url).path.lower()
        interactive_auth_surface = any(marker in path for marker in _INTERACTIVE_AUTH_PATHS)
        if isinstance(error, AuthenticationRequiredError) or (
            isinstance(error, RestrictionDetectedError) and interactive_auth_surface
        ):
            self._authentication_state = AuthenticationState.LOGIN_REQUIRED
            self._authentication_status_message = error.safe_message
        elif error.pause_required:
            self._authentication_state = AuthenticationState.ATTENTION_REQUIRED
            self._authentication_status_message = error.safe_message
        logger.warning(
            "linkedin_browser_access_paused",
            error_code=error.code.value,
            error_type=type(error).__name__,
        )

    def _mark_authenticated(self) -> None:
        self._authentication_state = AuthenticationState.AUTHENTICATED
        self._authentication_status_message = None
        self._paused = False
        self._pause_reason = None
