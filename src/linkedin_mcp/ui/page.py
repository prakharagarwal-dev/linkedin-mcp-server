"""A Playwright Page wrapper backed by the LinkedIn UI policy facade."""

from __future__ import annotations

from collections.abc import Callable
from re import Pattern
from typing import TYPE_CHECKING, Any, cast

from playwright.async_api import FileChooser, Keyboard, Mouse, Page, Response

from linkedin_mcp.ui.locator import LinkedInLocator

if TYPE_CHECKING:
    from playwright._impl._async_base import AsyncEventContextManager

    from linkedin_mcp.ui.playwright import LinkedInPlaywright


class LinkedInPage:
    """Present Playwright-style page calls with pacing and safety built in."""

    def __init__(self, page: Page, owner: LinkedInPlaywright) -> None:
        self._page = page
        self._owner = owner

    @property
    def raw_page(self) -> Page:
        """Return the official page for facade internals and narrow test adapters."""

        return self._page

    @property
    def url(self) -> str:
        return self._page.url

    @property
    def keyboard(self) -> Keyboard:
        return self._page.keyboard

    @property
    def mouse(self) -> Mouse:
        return self._page.mouse

    @property
    def context_page_count(self) -> int:
        return len(self._page.context.pages)

    def wrap_locator(self, locator: Any) -> LinkedInLocator:
        return LinkedInLocator(locator, self)

    def locator(self, *args: Any, **kwargs: Any) -> LinkedInLocator:
        return self.wrap_locator(self._page.locator(*args, **kwargs))

    def get_by_role(self, *args: Any, **kwargs: Any) -> LinkedInLocator:
        return self.wrap_locator(self._page.get_by_role(*args, **kwargs))

    def get_by_text(self, *args: Any, **kwargs: Any) -> LinkedInLocator:
        return self.wrap_locator(self._page.get_by_text(*args, **kwargs))

    def get_by_placeholder(self, *args: Any, **kwargs: Any) -> LinkedInLocator:
        return self.wrap_locator(self._page.get_by_placeholder(*args, **kwargs))

    def get_by_label(self, *args: Any, **kwargs: Any) -> LinkedInLocator:
        return self.wrap_locator(self._page.get_by_label(*args, **kwargs))

    def get_by_alt_text(self, *args: Any, **kwargs: Any) -> LinkedInLocator:
        return self.wrap_locator(self._page.get_by_alt_text(*args, **kwargs))

    async def goto(self, url: str, **kwargs: Any) -> Response | None:
        return await self._owner.navigate(self._page, url, **kwargs)

    async def click(self, locator: LinkedInLocator, **kwargs: Any) -> None:
        await self._owner.click(self._page, locator.raw_locator, **kwargs)

    async def click_and_wait_for_navigation(
        self,
        locator: LinkedInLocator,
        **kwargs: Any,
    ) -> str:
        return await self._owner.click_and_wait_for_navigation(
            self._page,
            locator.raw_locator,
            **kwargs,
        )

    async def check(self, locator: LinkedInLocator, **kwargs: Any) -> None:
        await self._owner.check(self._page, locator.raw_locator, **kwargs)

    async def uncheck(self, locator: LinkedInLocator, **kwargs: Any) -> None:
        await self._owner.uncheck(self._page, locator.raw_locator, **kwargs)

    async def fill(self, locator: LinkedInLocator, value: str, **kwargs: Any) -> None:
        await self._owner.fill(self._page, locator.raw_locator, value, **kwargs)

    async def press(self, locator: LinkedInLocator, key: str, **kwargs: Any) -> None:
        await self._owner.press(self._page, locator.raw_locator, key, **kwargs)

    async def press_sequentially(
        self,
        locator: LinkedInLocator,
        text: str,
        **kwargs: Any,
    ) -> None:
        await self._owner.press_sequentially(self._page, locator.raw_locator, text, **kwargs)

    async def set_input_files(
        self,
        locator: LinkedInLocator,
        files: Any,
        **kwargs: Any,
    ) -> None:
        await self._owner.set_input_files(self._page, locator.raw_locator, files, **kwargs)

    async def select_option(
        self,
        locator: LinkedInLocator,
        values: Any = None,
        **kwargs: Any,
    ) -> list[str]:
        return await self._owner.select_option(
            self._page,
            locator.raw_locator,
            values,
            **kwargs,
        )

    async def assert_safe(self) -> None:
        await self._owner.assert_safe(self._page)

    async def wait_for_timeout(self, milliseconds: float) -> None:
        await self._page.wait_for_timeout(milliseconds)

    async def wait_for_url(
        self,
        url: str | Pattern[str] | Callable[[object], bool],
        **kwargs: Any,
    ) -> None:
        await self._page.wait_for_url(cast(Any, url), **kwargs)

    async def wait_for_load_state(self, state: Any = None, **kwargs: Any) -> None:
        await self._page.wait_for_load_state(state, **kwargs)

    async def title(self) -> str:
        return await self._page.title()

    async def evaluate(self, expression: str, arg: object | None = None) -> Any:
        return await self._page.evaluate(expression, arg)

    def expect_file_chooser(
        self,
        predicate: Any = None,
        **kwargs: Any,
    ) -> AsyncEventContextManager[FileChooser]:
        event = self._page.expect_file_chooser(predicate, **kwargs)
        return event  # pyright: ignore[reportReturnType]

    def is_closed(self) -> bool:
        return self._page.is_closed()
