"""A Playwright Locator wrapper with centrally enforced LinkedIn interactions."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, Protocol, cast

from playwright.async_api import FloatRect, Locator

if TYPE_CHECKING:
    from linkedin_mcp.ui.page import LinkedInPage


class _EventDispatcher(Protocol):
    def dispatch_event(
        self,
        event_type: str,
        event_init: dict[str, object],
    ) -> Awaitable[None]: ...


def _unwrap(value: object) -> object:
    if isinstance(value, LinkedInLocator):
        return value.raw_locator
    if isinstance(value, list):
        return [_unwrap(item) for item in cast(list[object], value)]
    if isinstance(value, tuple):
        return tuple(_unwrap(item) for item in cast(tuple[object, ...], value))
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return {key: _unwrap(item) for key, item in mapping.items()}
    return value


class LinkedInLocator:
    """Expose familiar Locator operations while guarding visible UI mutations."""

    def __init__(self, locator: Locator, page: LinkedInPage) -> None:
        self._locator = locator
        self._page = page

    @property
    def raw_locator(self) -> Locator:
        """Return the official locator for wrapper internals and Playwright callbacks."""

        return self._locator

    @property
    def page(self) -> LinkedInPage:
        return self._page

    @property
    def first(self) -> LinkedInLocator:
        return self._page.wrap_locator(self._locator.first)

    @property
    def last(self) -> LinkedInLocator:
        return self._page.wrap_locator(self._locator.last)

    def nth(self, index: int) -> LinkedInLocator:
        return self._page.wrap_locator(self._locator.nth(index))

    def locator(self, *args: Any, **kwargs: Any) -> LinkedInLocator:
        unwrapped = cast(dict[str, Any], _unwrap(kwargs))
        return self._page.wrap_locator(self._locator.locator(*args, **unwrapped))

    def get_by_role(self, *args: Any, **kwargs: Any) -> LinkedInLocator:
        return self._page.wrap_locator(self._locator.get_by_role(*args, **kwargs))

    def get_by_text(self, *args: Any, **kwargs: Any) -> LinkedInLocator:
        return self._page.wrap_locator(self._locator.get_by_text(*args, **kwargs))

    def get_by_placeholder(self, *args: Any, **kwargs: Any) -> LinkedInLocator:
        return self._page.wrap_locator(self._locator.get_by_placeholder(*args, **kwargs))

    def get_by_label(self, *args: Any, **kwargs: Any) -> LinkedInLocator:
        return self._page.wrap_locator(self._locator.get_by_label(*args, **kwargs))

    def get_by_alt_text(self, *args: Any, **kwargs: Any) -> LinkedInLocator:
        return self._page.wrap_locator(self._locator.get_by_alt_text(*args, **kwargs))

    def filter(self, **kwargs: Any) -> LinkedInLocator:
        unwrapped = cast(dict[str, Any], _unwrap(kwargs))
        return self._page.wrap_locator(self._locator.filter(**unwrapped))

    def or_(self, locator: LinkedInLocator) -> LinkedInLocator:
        return self._page.wrap_locator(self._locator.or_(locator.raw_locator))

    def and_(self, locator: LinkedInLocator) -> LinkedInLocator:
        return self._page.wrap_locator(self._locator.and_(locator.raw_locator))

    async def count(self) -> int:
        return await self._locator.count()

    async def is_visible(self, **kwargs: Any) -> bool:
        return await self._locator.is_visible(**kwargs)

    async def is_enabled(self, **kwargs: Any) -> bool:
        return await self._locator.is_enabled(**kwargs)

    async def is_disabled(self, **kwargs: Any) -> bool:
        return await self._locator.is_disabled(**kwargs)

    async def is_checked(self, **kwargs: Any) -> bool:
        return await self._locator.is_checked(**kwargs)

    async def inner_text(self, **kwargs: Any) -> str:
        return await self._locator.inner_text(**kwargs)

    async def text_content(self, **kwargs: Any) -> str | None:
        return await self._locator.text_content(**kwargs)

    async def all_inner_texts(self) -> list[str]:
        return await self._locator.all_inner_texts()

    async def get_attribute(self, name: str, **kwargs: Any) -> str | None:
        return await self._locator.get_attribute(name, **kwargs)

    async def bounding_box(self, **kwargs: Any) -> FloatRect | None:
        return await self._locator.bounding_box(**kwargs)

    async def wait_for(self, **kwargs: Any) -> None:
        await self._locator.wait_for(**kwargs)

    async def evaluate(self, expression: str, arg: object | None = None) -> Any:
        return await self._locator.evaluate(expression, arg)

    async def evaluate_all(self, expression: str, arg: object | None = None) -> Any:
        return await self._locator.evaluate_all(expression, arg)

    async def click(self, **kwargs: Any) -> None:
        await self._page.click(self, **kwargs)

    async def click_and_wait_for_navigation(self, **kwargs: Any) -> str:
        return await self._page.click_and_wait_for_navigation(self, **kwargs)

    async def check(self, **kwargs: Any) -> None:
        await self._page.check(self, **kwargs)

    async def uncheck(self, **kwargs: Any) -> None:
        await self._page.uncheck(self, **kwargs)

    async def fill(self, value: str, **kwargs: Any) -> None:
        await self._page.fill(self, value, **kwargs)

    async def press(self, key: str, **kwargs: Any) -> None:
        await self._page.press(self, key, **kwargs)

    async def press_sequentially(self, text: str, **kwargs: Any) -> None:
        await self._page.press_sequentially(self, text, **kwargs)

    async def set_input_files(self, files: Any, **kwargs: Any) -> None:
        await self._page.set_input_files(self, files, **kwargs)

    async def select_option(self, values: Any = None, **kwargs: Any) -> list[str]:
        return await self._page.select_option(self, values, **kwargs)

    async def hover(self, **kwargs: Any) -> None:
        await self._locator.hover(**kwargs)

    async def focus(self, **kwargs: Any) -> None:
        await self._locator.focus(**kwargs)

    async def scroll_into_view_if_needed(self, **kwargs: Any) -> None:
        await self._locator.scroll_into_view_if_needed(**kwargs)

    async def dispatch_event(
        self,
        event_type: str,
        event_init: dict[str, object],
    ) -> None:
        dispatcher = cast(_EventDispatcher, self._locator)
        await dispatcher.dispatch_event(event_type, event_init)

    async def input_value(self, **kwargs: Any) -> str:
        return await self._locator.input_value(**kwargs)
