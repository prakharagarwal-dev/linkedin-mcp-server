"""Serialized lifecycle for one persistent Playwright browser context."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from linkedin_mcp.browser.bootstrap import BrowserRuntimeBootstrap, BrowserSetupState
from linkedin_mcp.browser.profile import BrowserProfileManager
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import BrowserUnavailableError


class BrowserRuntime:
    """Provide serialized, operation-scoped pages from one persistent context."""

    def __init__(
        self,
        settings: Settings,
        *,
        browser_bootstrap: BrowserRuntimeBootstrap | None = None,
        browser_profile: BrowserProfileManager | None = None,
    ) -> None:
        self._settings = settings
        self._bootstrap = browser_bootstrap or BrowserRuntimeBootstrap(settings)
        self._profile = browser_profile or BrowserProfileManager(
            settings,
            self._bootstrap,
        )
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._operation_lock = asyncio.Lock()

    @property
    def bootstrap(self) -> BrowserRuntimeBootstrap:
        return self._bootstrap

    @property
    def started(self) -> bool:
        return self._playwright is not None and self._context is not None

    @property
    def setup_state(self) -> BrowserSetupState:
        return self._bootstrap.state

    def profile_present(self) -> bool:
        return self._profile.inspect().initialized

    def start_setup(self) -> None:
        self._bootstrap.start()

    async def ensure_profile(self) -> None:
        await self._profile.ensure_created()

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        """Yield one serialized page and close every page owned by the operation."""

        async with self._operation_lock:
            context = await self._ensure_started()
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

    async def stop(self) -> None:
        """Close the active context without stopping background browser setup."""

        async with self._operation_lock:
            await self._close_browser()

    async def close(self) -> None:
        """Close the active context and all browser-runtime background work."""

        await self.stop()
        await self._bootstrap.close()

    async def _ensure_started(self) -> BrowserContext:
        if self.started:
            assert self._context is not None
            return self._context
        await self._close_browser()
        await self._bootstrap.ensure_ready()
        await self._profile.ensure_created()
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
