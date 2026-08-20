"""Lifecycle owner for one persistent Playwright Chromium context."""

from __future__ import annotations

from playwright.async_api import BrowserContext, Playwright, async_playwright

from linkedin_mcp.browser.bootstrap import BrowserBootstrap, BrowserSetupState
from linkedin_mcp.browser.login import login_interactively, validate_saved_session
from linkedin_mcp.browser.logout import logout_interactively
from linkedin_mcp.browser.profile import BrowserProfileManager
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import AuthenticationRequiredError, BrowserUnavailableError


class BrowserManager:
    """Start, authenticate, expose, and close one persistent browser context."""

    def __init__(
        self,
        settings: Settings,
        *,
        browser_bootstrap: BrowserBootstrap | None = None,
        browser_profile: BrowserProfileManager | None = None,
    ) -> None:
        self._settings = settings
        self._bootstrap = browser_bootstrap or BrowserBootstrap(settings)
        self._profile = browser_profile or BrowserProfileManager(settings, self._bootstrap)
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None

    @property
    def started(self) -> bool:
        return self._playwright is not None and self._context is not None

    @property
    def setup_state(self) -> BrowserSetupState:
        return self._bootstrap.state

    def profile_present(self) -> bool:
        return self._profile.inspect().initialized

    async def start(self) -> BrowserContext:
        """Start Chromium and synchronously establish a usable LinkedIn session."""

        if self._context is not None:
            return self._context
        self._profile.require_initialized()
        context = await self._open_context()
        try:
            await validate_saved_session(context, self._settings)
        except AuthenticationRequiredError:
            await self._close_browser()
            await login_interactively(self._settings, self._bootstrap)
            context = await self._open_context()
            await validate_saved_session(context, self._settings)
        return context

    async def login(self) -> None:
        """Close any owned context and perform one visible persistent login."""

        await self._close_browser()
        await login_interactively(self._settings, self._bootstrap)

    async def logout(self) -> bool:
        """Close any owned context and perform one visible persistent logout."""

        await self._close_browser()
        return await logout_interactively(self._settings, self._bootstrap)

    async def close(self) -> None:
        await self._close_browser()

    async def _open_context(self) -> BrowserContext:
        await self._close_browser()
        await self._bootstrap.ensure_ready()
        self._profile.require_initialized()
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
