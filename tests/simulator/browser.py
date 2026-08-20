"""A real Playwright browser whose LinkedIn document requests are fulfilled offline."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from playwright.async_api import (
    Browser,
    BrowserContext,
    Locator,
    Page,
    Playwright,
    Route,
    async_playwright,
)

from linkedin_mcp.browser.bootstrap import BrowserSetupState
from linkedin_mcp.errors import (
    AuthenticationRequiredError,
    BrowserUnavailableError,
    ParserDriftError,
    RestrictionDetectedError,
)
from linkedin_mcp.ui import AuthenticationState
from linkedin_mcp.ui.safety import assert_safe_linkedin_page
from linkedin_mcp.ui.urls import validate_linkedin_url
from tests.simulator.scenario import SimulatorScenario
from tests.simulator.state import SimulatorFault


class SimulatorBrowser:
    """Offline raw-page provider adapted to LinkedInPlaywright in tests."""

    def __init__(self, scenario: SimulatorScenario) -> None:
        self.scenario = scenario
        self.navigations: list[str] = []
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    @property
    def started(self) -> bool:
        return self._context is not None

    @property
    def paused(self) -> bool:
        return not self.scenario.state.authenticated

    @property
    def pause_reason(self) -> str | None:
        return None if self.scenario.state.authenticated else "Synthetic authentication expired."

    @property
    def browser_setup_state(self) -> BrowserSetupState:
        return BrowserSetupState.READY

    @property
    def authentication_state(self) -> AuthenticationState:
        if self.scenario.state.authenticated:
            return AuthenticationState.AUTHENTICATED
        return AuthenticationState.ATTENTION_REQUIRED

    @property
    def authentication_status_message(self) -> str | None:
        return self.pause_reason

    def profile_present(self) -> bool:
        return True

    async def start(self) -> None:
        if self.started:
            return
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context()
        await self._context.route("**/*", self._fulfill)

    @asynccontextmanager
    async def page(self) -> AsyncGenerator[Page]:
        if self._context is None:
            raise RuntimeError("The simulator browser must be started before use.")
        page = await self._context.new_page()
        try:
            yield page
        finally:
            await page.close()

    async def navigate(self, page: Page, url: str) -> None:
        target = validate_linkedin_url(url, ("www.linkedin.com", "linkedin.com"))
        self._raise_planned_fault(self.scenario.surface_for_url(target))
        self._raise_planned_fault("navigate")
        self.navigations.append(target)
        await page.goto(target, wait_until="domcontentloaded")
        await self.assert_safe(page)

    async def navigate_via_visible_control(self, page: Page, control: Locator) -> str:
        await control.click()
        await page.wait_for_load_state("domcontentloaded")
        target = validate_linkedin_url(page.url, ("www.linkedin.com", "linkedin.com"))
        await self.assert_safe(page)
        return target

    async def click_visible_control(self, page: Page, control: Locator) -> None:
        self._raise_planned_fault("click")
        await control.click()
        await self.assert_safe(page)

    async def assert_safe(self, page: Page) -> None:
        await assert_safe_linkedin_page(page, ("www.linkedin.com", "linkedin.com"))

    async def close(self) -> None:
        context, self._context = self._context, None
        browser, self._browser = self._browser, None
        playwright, self._playwright = self._playwright, None
        if context is not None:
            await context.close()
        if browser is not None:
            await browser.close()
        if playwright is not None:
            await playwright.stop()

    async def _fulfill(self, route: Route) -> None:
        request = route.request
        if request.resource_type != "document":
            await route.fulfill(status=204, body="")
            return
        try:
            fixture = self.scenario.fixture_for_url(request.url)
        except ValueError:
            await route.abort("blockedbyclient")
            return
        await route.fulfill(
            status=200,
            content_type="text/html; charset=utf-8",
            body=fixture.read_text(encoding="utf-8"),
        )

    def _raise_planned_fault(self, operation: str) -> None:
        fault = self.scenario.state.take_fault(operation)
        if fault is None:
            return
        if fault is SimulatorFault.NAVIGATION_TIMEOUT:
            raise BrowserUnavailableError("Synthetic LinkedIn navigation timed out.")
        if fault is SimulatorFault.AUTHENTICATION_EXPIRED:
            self.scenario.state.authenticated = False
            raise AuthenticationRequiredError("Synthetic LinkedIn authentication expired.")
        if fault is SimulatorFault.RESTRICTION:
            raise RestrictionDetectedError("Synthetic LinkedIn restriction page detected.")
        if fault is SimulatorFault.CONTROL_MISSING:
            raise ParserDriftError("Synthetic visible control is unavailable.")
        if fault is SimulatorFault.EFFECT_INTERRUPTED:
            raise BrowserUnavailableError("Synthetic action was interrupted.")
        raise BrowserUnavailableError("Synthetic postcondition verification timed out.")
