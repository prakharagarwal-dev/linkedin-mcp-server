"""Tool-facing Playwright facade with LinkedIn pacing and safety built in."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

import structlog
from playwright.async_api import BrowserContext, Locator, Page, Response

from linkedin_mcp.browser.bootstrap import BrowserSetupState
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import (
    AccessPausedError,
    AuthenticationRequiredError,
    BrowserUnavailableError,
    LinkedInMCPError,
    RestrictionDetectedError,
)
from linkedin_mcp.ui.authentication_state import AuthenticationState
from linkedin_mcp.ui.pacing import NavigationPacer
from linkedin_mcp.ui.page import LinkedInPage
from linkedin_mcp.ui.safety import assert_safe_linkedin_page
from linkedin_mcp.ui.urls import validate_linkedin_url

logger = structlog.get_logger(__name__)

RawPageFactory = Callable[[], AbstractAsyncContextManager[Page]]
NavigateHook = Callable[[Page, str], Awaitable[None]]
ClickHook = Callable[[Page, Locator, dict[str, Any]], Awaitable[None]]
NavigationClickHook = Callable[[Page, Locator, dict[str, Any]], Awaitable[str]]
SafetyHook = Callable[[Page], Awaitable[None]]

_INTERACTIVE_AUTH_PATHS = ("/login", "/uas/login", "/checkpoint/", "/authwall")


class LinkedInPlaywright:
    """Create task pages and enforce process-local LinkedIn UI policy."""

    def __init__(
        self,
        context: BrowserContext,
        settings: Settings,
        *,
        browser_setup_state: BrowserSetupState,
        profile_present: bool,
    ) -> None:
        self._context = context
        self._settings = settings
        self._pacer = NavigationPacer(
            account_id=settings.account_id,
            interval_seconds=settings.minimum_navigation_interval_seconds,
        )
        self._browser_setup_state = browser_setup_state
        self._profile_present = profile_present
        self._authentication_state = AuthenticationState.AUTHENTICATED
        self._authentication_status_message: str | None = None
        self._paused = False
        self._pause_reason: str | None = None
        self._page_factory: RawPageFactory | None = None
        self._navigate_hook: NavigateHook | None = None
        self._click_hook: ClickHook | None = None
        self._navigation_click_hook: NavigationClickHook | None = None
        self._safety_hook: SafetyHook | None = None

    @classmethod
    def for_testing(
        cls,
        settings: Settings,
        *,
        page_factory: RawPageFactory,
        navigate: NavigateHook | None = None,
        click: ClickHook | None = None,
        navigate_via_click: NavigationClickHook | None = None,
        assert_safe: SafetyHook | None = None,
    ) -> LinkedInPlaywright:
        """Create a facade around an offline page provider without a browser context."""

        instance = cls.__new__(cls)
        instance._context = None
        instance._settings = settings
        instance._pacer = NavigationPacer(
            account_id=settings.account_id,
            interval_seconds=settings.minimum_navigation_interval_seconds,
        )
        instance._browser_setup_state = BrowserSetupState.READY
        instance._profile_present = True
        instance._authentication_state = AuthenticationState.AUTHENTICATED
        instance._authentication_status_message = None
        instance._paused = False
        instance._pause_reason = None
        instance._page_factory = page_factory
        instance._navigate_hook = navigate
        instance._click_hook = click
        instance._navigation_click_hook = navigate_via_click
        instance._safety_hook = assert_safe
        return instance

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
    def browser_setup_state(self) -> BrowserSetupState:
        return self._browser_setup_state

    def profile_present(self) -> bool:
        return self._profile_present

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[LinkedInPage]:
        """Yield one wrapped task page and close every page opened by that task."""

        self._ensure_available()
        if self._page_factory is not None:
            async with self._page_factory() as raw_page:
                yield LinkedInPage(raw_page, self)
            return

        context = self._context
        if context is None:
            raise BrowserUnavailableError("The Playwright browser context is not running.")
        existing_page_urls = {
            id(existing): existing.url for existing in context.pages if not existing.is_closed()
        }
        try:
            raw_page = await context.new_page()
        except Exception as error:
            raise BrowserUnavailableError("A Chromium page could not be created.") from error
        try:
            yield LinkedInPage(raw_page, self)
        finally:
            owned_pages = [
                candidate
                for candidate in context.pages
                if candidate is raw_page
                or id(candidate) not in existing_page_urls
                or existing_page_urls[id(candidate)] != candidate.url
            ]
            for owned_page in reversed(owned_pages):
                if not owned_page.is_closed():
                    await owned_page.close()

    async def navigate(self, page: Page, url: str, **kwargs: Any) -> Response | None:
        target = validate_linkedin_url(url, self._settings.allowed_hosts)
        await self._pacer.wait()
        try:
            hook = self._navigate_hook
            if hook is not None:
                await hook(page, target)
                response = None
            else:
                kwargs.setdefault("wait_until", "domcontentloaded")
                response = await page.goto(target, **kwargs)
            await self.assert_safe(page)
            return response
        except LinkedInMCPError as error:
            self._record_access_error(error, page.url or target)
            raise
        except Exception as error:
            raise BrowserUnavailableError("LinkedIn navigation failed.") from error

    async def click(self, page: Page, locator: Locator, **kwargs: Any) -> None:
        if kwargs.get("trial") is True:
            await locator.click(**kwargs)
            return
        await self._pacer.wait()
        try:
            hook = self._click_hook
            if hook is not None:
                await hook(page, locator, kwargs)
            else:
                await locator.click(**kwargs)
                await page.wait_for_timeout(300)
            await self.assert_safe(page)
        except LinkedInMCPError as error:
            self._record_access_error(error, page.url)
            raise

    async def click_and_wait_for_navigation(
        self,
        page: Page,
        locator: Locator,
        **kwargs: Any,
    ) -> str:
        hook = self._navigation_click_hook
        if hook is not None:
            await self._pacer.wait()
            try:
                target = await hook(page, locator, kwargs)
                await self.assert_safe(page)
                return validate_linkedin_url(target, self._settings.allowed_hosts)
            except LinkedInMCPError as error:
                self._record_access_error(error, page.url)
                raise

        previous_url = page.url
        await self.click(page, locator, **kwargs)
        try:
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
            await self.assert_safe(page)
            return target
        except LinkedInMCPError as error:
            self._record_access_error(error, page.url)
            raise

    async def check(self, page: Page, locator: Locator, **kwargs: Any) -> None:
        await self._mutate(page, locator.check, paced=True, **kwargs)

    async def uncheck(self, page: Page, locator: Locator, **kwargs: Any) -> None:
        await self._mutate(page, locator.uncheck, paced=True, **kwargs)

    async def fill(self, page: Page, locator: Locator, value: str, **kwargs: Any) -> None:
        await self._mutate(page, locator.fill, value, **kwargs)

    async def press(self, page: Page, locator: Locator, key: str, **kwargs: Any) -> None:
        await self._mutate(page, locator.press, key, **kwargs)

    async def press_sequentially(
        self,
        page: Page,
        locator: Locator,
        text: str,
        **kwargs: Any,
    ) -> None:
        await self._mutate(page, locator.press_sequentially, text, **kwargs)

    async def set_input_files(
        self,
        page: Page,
        locator: Locator,
        files: Any,
        **kwargs: Any,
    ) -> None:
        await self._mutate(page, locator.set_input_files, files, **kwargs)

    async def select_option(
        self,
        page: Page,
        locator: Locator,
        values: Any,
        **kwargs: Any,
    ) -> list[str]:
        result = await self._mutate(page, locator.select_option, values, paced=True, **kwargs)
        return list(result)

    async def assert_safe(self, page: Page) -> None:
        try:
            hook = self._safety_hook
            if hook is not None:
                await hook(page)
            elif self._page_factory is None:
                await assert_safe_linkedin_page(page, self._settings.allowed_hosts)
            self._mark_authenticated()
        except LinkedInMCPError as error:
            self._record_access_error(error, page.url)
            raise

    async def close(self) -> None:
        self._pacer.close()
        self._page_factory = None
        self._context = None

    async def _mutate(
        self,
        page: Page,
        operation: Callable[..., Awaitable[Any]],
        *args: Any,
        paced: bool = False,
        **kwargs: Any,
    ) -> Any:
        if paced:
            await self._pacer.wait()
        try:
            result = await operation(*args, **kwargs)
            await self.assert_safe(page)
            return result
        except LinkedInMCPError as error:
            self._record_access_error(error, page.url)
            raise

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
            "linkedin_ui_access_paused",
            error_code=error.code.value,
            error_type=type(error).__name__,
        )

    def _mark_authenticated(self) -> None:
        self._authentication_state = AuthenticationState.AUTHENTICATED
        self._authentication_status_message = None
        self._paused = False
        self._pause_reason = None
