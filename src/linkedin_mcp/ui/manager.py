"""Tool-facing Playwright access with pacing applied to every interaction."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from playwright.async_api import Page

from linkedin_mcp.browser.manager import BrowserManager
from linkedin_mcp.ui.pacer import ClickHook, NavigateHook, NavigationClickHook, Pacer


class UIManager(Pacer):
    """Provide an owned Playwright page and precisely paced interaction methods."""

    def __init__(
        self,
        browser: BrowserManager,
        delay_seconds: float,
        *,
        navigate_hook: NavigateHook | None = None,
        click_hook: ClickHook | None = None,
        navigation_click_hook: NavigationClickHook | None = None,
    ) -> None:
        super().__init__(
            delay_seconds,
            navigate_hook=navigate_hook,
            click_hook=click_hook,
            navigation_click_hook=navigation_click_hook,
        )
        self._browser = browser

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        async with self._browser.page() as page:
            yield page
