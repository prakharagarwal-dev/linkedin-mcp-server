"""Adapt existing offline page providers to the tool-facing Playwright facade."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from linkedin_mcp.config import Settings
from linkedin_mcp.ui import LinkedInPlaywright
from linkedin_mcp.ui.playwright import (
    ClickHook,
    NavigateHook,
    NavigationClickHook,
    RawPageFactory,
    SafetyHook,
)


def test_settings(root: Path | None = None) -> Settings:
    base = root or Path(".test-linkedin-playwright")
    return Settings(
        browser_auto_install=False,
        browser_profile_path=base / "profile",
        minimum_navigation_interval_seconds=0,
        runtime_lock_path=base / "runtime.lock",
    )


def adapt_browser(provider: object, *, settings: Settings | None = None) -> LinkedInPlaywright:
    """Wrap a legacy offline page provider without exposing it to production tools."""

    effective_settings = settings or test_settings()
    page_factory = cast(RawPageFactory, _required_hook(provider, "page"))
    navigate = cast(NavigateHook | None, _optional_hook(provider, "navigate"))
    legacy_click = cast(
        Callable[[Page, Locator], Awaitable[None]] | None,
        _optional_hook(provider, "click_visible_control"),
    )
    legacy_navigation_click = cast(
        Callable[[Page, Locator], Awaitable[str]] | None,
        _optional_hook(provider, "navigate_via_visible_control"),
    )
    click = _bounded_click_hook(legacy_click, effective_settings)
    navigate_via_click = _bounded_navigation_click_hook(
        legacy_navigation_click,
        effective_settings,
    )
    assert_safe = cast(SafetyHook | None, _optional_hook(provider, "assert_safe"))
    return LinkedInPlaywright.for_testing(
        effective_settings,
        page_factory=page_factory,
        navigate=navigate,
        click=click,
        navigate_via_click=navigate_via_click,
        assert_safe=assert_safe,
    )


def empty_playwright(settings: Settings) -> LinkedInPlaywright:
    """Create status-capable UI wiring for protocol tests that replace every page object."""

    return LinkedInPlaywright.for_testing(settings, page_factory=_unavailable_page)


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

    async def bounded(page: Page, locator: Locator, options: dict[str, Any]) -> None:
        await _run_bounded(hook(page, locator), options, settings)

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
