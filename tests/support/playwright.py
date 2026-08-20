"""Adapt offline page providers to the production browser and pacing boundary."""

from __future__ import annotations

import asyncio
from collections.abc import (
    AsyncGenerator,
    Awaitable,
    Callable,
)
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from linkedin_mcp.browser import BrowserManager
from linkedin_mcp.browser.manager import AccessHook, PageFactory
from linkedin_mcp.config import Settings
from linkedin_mcp.infra.playwright.pacer import (
    ClickHook,
    NavigateHook,
    NavigationClickHook,
    Paced,
)


def test_settings(root: Path | None = None) -> Settings:
    base = root or Path(".test-linkedin-playwright")
    return Settings(
        browser_auto_install=False,
        browser_profile_path=base / "profile",
        browser_action_delay_seconds=0,
        runtime_lock_path=base / "runtime.lock",
    )


def adapt_browser(provider: object, *, settings: Settings | None = None) -> BrowserManager:
    """Adapt an offline raw-page provider to the production dependencies."""

    effective_settings = settings or test_settings()
    page_factory = cast(PageFactory, _required_hook(provider, "page"))
    legacy_navigate = cast(
        Callable[[Page, str], Awaitable[None]] | None,
        _optional_hook(provider, "navigate"),
    )
    legacy_click = cast(
        Callable[[Page, Locator], Awaitable[None]] | None,
        _optional_hook(provider, "click_visible_control"),
    )
    legacy_navigation_click = cast(
        Callable[[Page, Locator], Awaitable[str]] | None,
        _optional_hook(provider, "navigate_via_visible_control"),
    )
    navigate = _bounded_navigation_hook(legacy_navigate, effective_settings)
    click = _bounded_click_hook(legacy_click, effective_settings)
    navigate_via_click = _bounded_navigation_click_hook(
        legacy_navigation_click,
        effective_settings,
    )
    assert_access = cast(AccessHook | None, _optional_hook(provider, "assert_safe"))
    paced = Paced(
        effective_settings.browser_action_delay_seconds,
        navigate_hook=navigate,
        click_hook=click,
        navigation_click_hook=navigate_via_click,
    )
    return BrowserManager.for_testing(
        effective_settings,
        paced,
        page_factory=page_factory,
        assert_access=assert_access,
    )


def empty_browser(settings: Settings) -> BrowserManager:
    """Create status-capable browser wiring when tests replace every page object."""

    return BrowserManager.for_testing(
        settings,
        Paced(0),
        page_factory=_unavailable_page,
    )


@asynccontextmanager
async def _unavailable_page() -> AsyncGenerator[Page]:
    raise AssertionError("This protocol fixture has no live Playwright pages.")
    if False:  # pragma: no cover - establishes the async-generator type
        yield cast(Page, object())


def _optional_hook(provider: object, name: str) -> object | None:
    value: Any = getattr(provider, name, None)
    return value if callable(value) else None


def _required_hook(provider: object, name: str) -> object:
    value = _optional_hook(provider, name)
    if value is None:
        raise TypeError(f"Offline page provider must define callable {name!r}.")
    return value


def _bounded_click_hook(
    hook: Callable[[Page, Locator], Awaitable[None]] | None,
    settings: Settings,
) -> ClickHook | None:
    if hook is None:
        return None

    async def bounded(locator: Locator, options: dict[str, Any]) -> None:
        await _run_bounded(hook(locator.page, locator), options, settings)

    return bounded


def _bounded_navigation_hook(
    hook: Callable[[Page, str], Awaitable[None]] | None,
    settings: Settings,
) -> NavigateHook | None:
    if hook is None:
        return None

    async def bounded(page: Page, url: str, options: dict[str, Any]) -> None:
        await _run_bounded(hook(page, url), options, settings)

    return bounded


def _bounded_navigation_click_hook(
    hook: Callable[[Page, Locator], Awaitable[str]] | None,
    settings: Settings,
) -> NavigationClickHook | None:
    if hook is None:
        return None

    async def bounded(page: Page, locator: Locator, options: dict[str, Any]) -> str:
        return await _run_bounded(hook(page, locator), options, settings)

    return bounded


async def _run_bounded[ResultT](
    operation: Awaitable[ResultT],
    options: dict[str, Any],
    settings: Settings,
) -> ResultT:
    configured_timeout = options.get("timeout")
    timeout_ms = (
        float(configured_timeout)
        if isinstance(configured_timeout, (int, float)) and configured_timeout > 0
        else settings.browser_timeout_seconds * 1_000
    )
    try:
        async with asyncio.timeout(timeout_ms / 1_000):
            return await operation
    except TimeoutError as error:
        raise PlaywrightTimeoutError("Offline Playwright control timed out.") from error
