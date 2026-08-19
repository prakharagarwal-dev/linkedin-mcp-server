"""Precisely paced wrappers for mutating Playwright interactions."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypeVar, cast

from playwright.async_api import FileChooser, Keyboard, Locator, Mouse, Page, Response

ResultT = TypeVar("ResultT")

NavigateHook = Callable[[Page, str, dict[str, Any]], Awaitable[Response | None]]
ClickHook = Callable[[Locator, dict[str, Any]], Awaitable[None]]
NavigationClickHook = Callable[[Page, Locator, dict[str, Any]], Awaitable[str]]


class _EventDispatcher(Protocol):
    def dispatch_event(
        self,
        event_type: str,
        event_init: dict[str, object],
    ) -> Awaitable[None]: ...


class _Evaluator(Protocol):
    def evaluate(self, expression: str, arg: object | None = None) -> Awaitable[Any]: ...


class Paced:
    """Apply one configured delay before selected Playwright interactions."""

    def __init__(
        self,
        delay_seconds: float,
        *,
        navigate_hook: NavigateHook | None = None,
        click_hook: ClickHook | None = None,
        navigation_click_hook: NavigationClickHook | None = None,
    ) -> None:
        if delay_seconds < 0:
            raise ValueError("Playwright interaction delay cannot be negative.")
        self._delay_seconds = delay_seconds
        self._navigate_hook = navigate_hook
        self._click_hook = click_hook
        self._navigation_click_hook = navigation_click_hook

    async def goto(self, page: Page, url: str, **kwargs: Any) -> Response | None:
        await self._wait()
        hook = self._navigate_hook
        if hook is not None:
            return await hook(page, url, kwargs)
        kwargs.setdefault("wait_until", "domcontentloaded")
        return await page.goto(url, **kwargs)

    async def click(self, locator: Locator, **kwargs: Any) -> None:
        await self._wait()
        if kwargs.get("trial") is True:
            await locator.click(**kwargs)
            return
        hook = self._click_hook
        if hook is not None:
            await hook(locator, kwargs)
            return
        await locator.click(**kwargs)

    async def click_and_wait_for_navigation(
        self,
        page: Page,
        locator: Locator,
        **kwargs: Any,
    ) -> str:
        await self._wait()
        hook = self._navigation_click_hook
        if hook is not None:
            return await hook(page, locator, kwargs)
        previous_url = page.url
        await locator.click(**kwargs)
        await page.wait_for_url(
            lambda value: str(value) != previous_url,
            wait_until="domcontentloaded",
        )
        await page.wait_for_timeout(1_000)
        target = page.url
        stable_rounds = 0
        for _ in range(40):
            await page.wait_for_timeout(100)
            current = page.url
            if current == target:
                stable_rounds += 1
            else:
                target = current
                stable_rounds = 0
            if stable_rounds >= 10:
                return target
        raise TimeoutError("Visible-control navigation did not settle within its bound.")

    async def check(self, locator: Locator, **kwargs: Any) -> None:
        await self._perform(locator.check, **kwargs)

    async def uncheck(self, locator: Locator, **kwargs: Any) -> None:
        await self._perform(locator.uncheck, **kwargs)

    async def fill(self, locator: Locator, value: str, **kwargs: Any) -> None:
        await self._perform(locator.fill, value, **kwargs)

    async def press(self, locator: Locator, key: str, **kwargs: Any) -> None:
        await self._perform(locator.press, key, **kwargs)

    async def press_sequentially(
        self,
        locator: Locator,
        text: str,
        **kwargs: Any,
    ) -> None:
        await self._perform(locator.press_sequentially, text, **kwargs)

    async def set_input_files(self, locator: Locator, files: Any, **kwargs: Any) -> None:
        await self._perform(locator.set_input_files, files, **kwargs)

    async def set_files(self, chooser: FileChooser, files: Any, **kwargs: Any) -> None:
        await self._perform(chooser.set_files, files, **kwargs)

    async def select_option(
        self,
        locator: Locator,
        values: Any = None,
        **kwargs: Any,
    ) -> list[str]:
        result = await self._perform(locator.select_option, values, **kwargs)
        return list(result)

    async def hover(self, locator: Locator, **kwargs: Any) -> None:
        await self._perform(locator.hover, **kwargs)

    async def focus(self, locator: Locator, **kwargs: Any) -> None:
        await self._perform(locator.focus, **kwargs)

    async def scroll_into_view_if_needed(self, locator: Locator, **kwargs: Any) -> None:
        await self._perform(locator.scroll_into_view_if_needed, **kwargs)

    async def dispatch_event(
        self,
        locator: Locator,
        event_type: str,
        event_init: dict[str, object],
    ) -> None:
        dispatcher = cast(_EventDispatcher, locator)
        await self._perform(dispatcher.dispatch_event, event_type, event_init)

    async def evaluate(
        self,
        target: Page | Locator,
        expression: str,
        arg: object | None = None,
    ) -> Any:
        evaluator = cast(_Evaluator, target)
        return await self._perform(evaluator.evaluate, expression, arg)

    async def keyboard_press(self, keyboard: Keyboard, key: str, **kwargs: Any) -> None:
        await self._perform(keyboard.press, key, **kwargs)

    async def wheel(self, mouse: Mouse, delta_x: float, delta_y: float) -> None:
        await self._perform(mouse.wheel, delta_x, delta_y)

    async def _perform(
        self,
        operation: Callable[..., Awaitable[ResultT]],
        *args: Any,
        **kwargs: Any,
    ) -> ResultT:
        await self._wait()
        return await operation(*args, **kwargs)

    async def _wait(self) -> None:
        if self._delay_seconds > 0:
            await asyncio.sleep(self._delay_seconds)
