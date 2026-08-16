from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, cast

import pytest

import linkedin_mcp.linkedin.browser as manager_module
from linkedin_mcp.browser import BrowserRuntimeBootstrap
from linkedin_mcp.browser.profile import BrowserProfileManager, BrowserProfileStatus
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import (
    AccessPausedError,
    AuthenticationRequiredError,
    BrowserUnavailableError,
    ConfigurationError,
    InvalidTargetError,
    ParserDriftError,
    RestrictionDetectedError,
)
from linkedin_mcp.linkedin.browser import (
    BrowserManager,
    login_interactively,
    logout_interactively,
)


def _live_settings(tmp_path: Path, *, profile_name: str = "profile") -> Settings:
    return Settings(
        browser_profile_path=tmp_path / profile_name,
        browser_auto_install=False,
        auto_login_on_start=False,
        minimum_navigation_interval_seconds=0,
        browser_timeout_seconds=5,
    )


def _mark_profile_initialized(settings: Settings) -> None:
    settings.browser_profile_path.mkdir(parents=True, exist_ok=True)
    (settings.browser_profile_path / "Preferences").write_text("{}", encoding="utf-8")


class FakeBrowserProfileManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def inspect(self) -> BrowserProfileStatus:
        path = self.settings.browser_profile_path
        initialized = path.is_dir() and any(path.iterdir())
        return BrowserProfileStatus(path=path, exists=path.is_dir(), initialized=initialized)

    async def ensure_created(self) -> None:
        _mark_profile_initialized(self.settings)


class FakeRuntimePage:
    def __init__(self) -> None:
        self.url = "about:blank"
        self.visited_url: str | None = None
        self.closed = False

    async def goto(self, url: str, *, wait_until: str) -> None:
        assert wait_until == "domcontentloaded"
        self.url = url
        self.visited_url = url

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True


class FakeRuntimeContext:
    def __init__(self) -> None:
        self.pages: list[FakeRuntimePage] = []
        self.closed = False
        self.default_timeout: float | None = None
        self.default_navigation_timeout: float | None = None

    def set_default_timeout(self, timeout: float) -> None:
        self.default_timeout = timeout

    def set_default_navigation_timeout(self, timeout: float) -> None:
        self.default_navigation_timeout = timeout

    async def new_page(self) -> FakeRuntimePage:
        page = FakeRuntimePage()
        self.pages.append(page)
        return page

    async def close(self) -> None:
        self.closed = True


class FakeRuntimeChromium:
    def __init__(self, context: FakeRuntimeContext) -> None:
        self.context = context
        self.headless: bool | None = None
        self.user_data_dir: str | None = None

    async def launch_persistent_context(
        self,
        *,
        user_data_dir: str,
        headless: bool,
    ) -> FakeRuntimeContext:
        self.user_data_dir = user_data_dir
        self.headless = headless
        return self.context


class FakeRuntimePlaywright:
    def __init__(self, context: FakeRuntimeContext) -> None:
        self.chromium = FakeRuntimeChromium(context)
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class FakeRuntimeStarter:
    def __init__(self, playwright: FakeRuntimePlaywright) -> None:
        self.playwright = playwright

    async def start(self) -> FakeRuntimePlaywright:
        return self.playwright


class FakeRememberMeLocator:
    def __init__(self, *, present: bool, checked: bool) -> None:
        self.present = present
        self.checked = checked
        self.check_timeout: float | None = None

    @property
    def first(self) -> FakeRememberMeLocator:
        return self

    async def count(self) -> int:
        return int(self.present)

    async def is_visible(self) -> bool:
        return self.present

    async def is_checked(self) -> bool:
        return self.checked

    async def check(self, **options: float) -> None:
        self.checked = True
        self.check_timeout = options["timeout"]


class FakeLoginBody:
    async def inner_text(self, **options: float) -> str:
        assert options["timeout"] == 2_000
        return "Authenticated LinkedIn feed"


class FakeLoginPage:
    def __init__(
        self,
        *,
        login_destination: str = "https://www.linkedin.com/feed/",
        feed_destination: str = "https://www.linkedin.com/feed/",
        remember_me_present: bool = False,
        remember_me_checked: bool = True,
    ) -> None:
        self.url = "about:blank"
        self.login_destination = login_destination
        self.feed_destination = feed_destination
        self.remember_me = FakeRememberMeLocator(
            present=remember_me_present,
            checked=remember_me_checked,
        )
        self.visited_urls: list[str] = []
        self.closed = False

    async def goto(self, url: str, *, wait_until: str) -> None:
        assert wait_until == "domcontentloaded"
        self.visited_urls.append(url)
        if url.endswith("/login"):
            self.url = self.login_destination
        elif url.endswith("/feed/"):
            self.url = self.feed_destination
        else:
            self.url = url

    def get_by_role(
        self,
        role: str,
        *,
        name: str,
        exact: bool,
    ) -> FakeRememberMeLocator:
        assert role == "checkbox"
        assert name == "Keep me signed in"
        assert exact is False
        return self.remember_me

    def locator(self, selector: str) -> FakeLoginBody:
        assert selector == "body"
        return FakeLoginBody()

    def is_closed(self) -> bool:
        return self.closed

    async def close(self) -> None:
        self.closed = True


class FakeLoginContext:
    def __init__(
        self,
        page: FakeLoginPage,
        *,
        cookies: list[dict[str, object]],
    ) -> None:
        self.pages = [page]
        self.cookies_result = cookies
        self.closed = False
        self.default_timeout: float | None = None
        self.default_navigation_timeout: float | None = None

    async def new_page(self) -> FakeLoginPage:
        return self.pages[0]

    async def cookies(self, _: str) -> list[dict[str, object]]:
        return self.cookies_result

    def set_default_timeout(self, timeout: float) -> None:
        self.default_timeout = timeout

    def set_default_navigation_timeout(self, timeout: float) -> None:
        self.default_navigation_timeout = timeout

    async def close(self) -> None:
        self.closed = True


class FakeLoginChromium:
    def __init__(self, contexts: list[FakeLoginContext]) -> None:
        self.contexts = contexts
        self.launches: list[tuple[str, bool]] = []

    async def launch_persistent_context(
        self,
        *,
        user_data_dir: str,
        headless: bool,
    ) -> FakeLoginContext:
        self.launches.append((user_data_dir, headless))
        return self.contexts[len(self.launches) - 1]


class FakeLoginPlaywright:
    def __init__(self, contexts: list[FakeLoginContext]) -> None:
        self.chromium = FakeLoginChromium(contexts)
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class FakeLoginStarter:
    def __init__(self, playwright: FakeLoginPlaywright) -> None:
        self.playwright = playwright

    async def start(self) -> FakeLoginPlaywright:
        return self.playwright


class FakeLogoutControl:
    def __init__(self, *, visible: bool = True, on_click: Any | None = None) -> None:
        self.visible = visible
        self.on_click = on_click
        self.clicked = False

    async def is_visible(self) -> bool:
        return self.visible

    async def click(self) -> None:
        self.clicked = True
        if self.on_click is not None:
            self.on_click()


class FakeLogoutControls:
    def __init__(self, controls: list[FakeLogoutControl]) -> None:
        self.controls = controls

    async def count(self) -> int:
        return len(self.controls)

    def nth(self, index: int) -> FakeLogoutControl:
        return self.controls[index]


class FakeLogoutPage:
    def __init__(
        self,
        *,
        destination: str,
        account_controls: list[FakeLogoutControl] | None = None,
        sign_out_controls: list[FakeLogoutControl] | None = None,
    ) -> None:
        self.url = "about:blank"
        self.destination = destination
        self.account_controls = account_controls or []
        self.sign_out_controls = sign_out_controls or []
        self.visited_urls: list[str] = []

    async def goto(self, url: str, *, wait_until: str) -> None:
        assert wait_until == "domcontentloaded"
        self.visited_urls.append(url)
        self.url = self.destination

    def get_by_role(self, role: str, *, name: object) -> FakeLogoutControls:
        del name
        if role == "button":
            return FakeLogoutControls(self.account_controls)
        if role == "link":
            return FakeLogoutControls(self.sign_out_controls)
        raise AssertionError(f"Unexpected role: {role}")

    async def wait_for_timeout(self, _: float) -> None:
        return


class FakeLogoutContext:
    def __init__(self, page: FakeLogoutPage, *, cookies: list[dict[str, object]]) -> None:
        self.pages = [page]
        self.cookies_result = cookies
        self.closed = False

    def set_default_timeout(self, _: float) -> None:
        return

    def set_default_navigation_timeout(self, _: float) -> None:
        return

    async def new_page(self) -> FakeLogoutPage:
        return self.pages[0]

    async def cookies(self, _: str) -> list[dict[str, object]]:
        return self.cookies_result

    async def close(self) -> None:
        self.closed = True


class FakeLogoutChromium:
    def __init__(self, contexts: list[FakeLogoutContext]) -> None:
        self.contexts = contexts
        self.launches: list[tuple[str, bool]] = []

    async def launch_persistent_context(
        self,
        *,
        user_data_dir: str,
        headless: bool,
    ) -> FakeLogoutContext:
        self.launches.append((user_data_dir, headless))
        return self.contexts[len(self.launches) - 1]


class FakeLogoutPlaywright:
    def __init__(self, contexts: list[FakeLogoutContext]) -> None:
        self.chromium = FakeLogoutChromium(contexts)
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class FakeLogoutStarter:
    def __init__(self, playwright: FakeLogoutPlaywright) -> None:
        self.playwright = playwright

    async def start(self) -> FakeLogoutPlaywright:
        return self.playwright


def _fake_li_at(*, persistent: bool) -> dict[str, object]:
    return {
        "name": "li_at",
        "expires": time.time() + 3_600 if persistent else -1,
    }


@pytest.mark.asyncio
async def test_automatic_first_run_login_validates_and_reuses_one_persistent_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _live_settings(tmp_path, profile_name="automatic").model_copy(
        update={"auto_login_on_start": True}
    )
    context = FakeRuntimeContext()
    playwright = FakeRuntimePlaywright(context)
    login_calls = 0

    async def fake_login(
        login_settings: Settings,
        _: BrowserRuntimeBootstrap,
    ) -> None:
        nonlocal login_calls
        login_calls += 1
        assert login_settings.browser_profile_path.is_dir()

    def fake_async_playwright() -> FakeRuntimeStarter:
        return FakeRuntimeStarter(playwright)

    async def safe_page(_: object, __: tuple[str, ...]) -> None:
        return

    monkeypatch.setattr(manager_module, "async_playwright", cast(Any, fake_async_playwright))
    monkeypatch.setattr(manager_module, "assert_safe_linkedin_page", safe_page)

    manager = BrowserManager(
        settings,
        browser_profile=cast(BrowserProfileManager, FakeBrowserProfileManager(settings)),
        login_runner=fake_login,
    )
    manager.start_session_bootstrap()

    async with manager.page() as capability_page:
        assert capability_page is context.pages[1]

    assert login_calls == 1
    assert manager.authentication_state.value == "authenticated"
    assert manager.profile_present() is True
    assert context.pages[0].visited_url == "https://www.linkedin.com/feed/"
    assert playwright.chromium.headless is True
    assert playwright.chromium.user_data_dir == str(settings.browser_profile_path)
    assert manager.started is True

    await manager.close()
    assert context.closed is True
    assert playwright.stopped is True


@pytest.mark.timeout(20)
async def test_browser_manager_starts_navigates_pauses_and_persists_profile(
    tmp_path: Path,
) -> None:
    settings = _live_settings(tmp_path)
    manager = BrowserManager(settings)

    assert manager.profile_present() is False
    assert manager.started is False
    assert manager.paused is False

    async with manager.page() as page:
        await page.route(
            "**/*",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body="<html><body><main>Visible jobs</main></body></html>",
            ),
        )
        await manager.navigate(page, "https://www.linkedin.com/jobs/search/?keywords=python")
        assert manager.started is True

        with pytest.raises(RestrictionDetectedError, match="security checkpoint"):
            await manager.navigate(page, "https://www.linkedin.com/checkpoint/challenge/")

    assert manager.paused is True
    assert manager.pause_reason is not None
    manager.resume()
    await manager.close()

    assert manager.started is False
    assert manager.profile_present() is True
    if os.name != "nt":
        assert settings.browser_profile_path.stat().st_mode & 0o077 == 0


@pytest.mark.timeout(20)
async def test_browser_manager_paces_and_validates_visible_control_navigation(
    tmp_path: Path,
) -> None:
    settings = _live_settings(tmp_path, profile_name="visible-control")
    manager = BrowserManager(settings)

    async with manager.page() as page:
        await page.route(
            "**/*",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body="""
                    <html>
                      <body>
                        <main>Visible people</main>
                        <script>
                          setTimeout(
                            () => history.replaceState(
                              null,
                              "",
                              "/search/results/people/?keywords=python&geoUrn=%5B%22102713980%22%5D"
                            ),
                            1200
                          );
                        </script>
                      </body>
                    </html>
                """,
            ),
        )
        await page.set_content(
            """
            <a href="https://www.linkedin.com/search/results/people/?keywords=python">
              Show results
            </a>
            """
        )
        target = await manager.navigate_via_visible_control(
            page,
            page.get_by_role("link", name="Show results"),
        )
        await page.set_content('<a href="https://example.com/search/">Unsafe results</a>')
        with pytest.raises(InvalidTargetError, match="allowed exact host"):
            await manager.navigate_via_visible_control(
                page,
                page.get_by_role("link", name="Unsafe results"),
            )

    assert target == (
        "https://www.linkedin.com/search/results/people/"
        "?keywords=python&geoUrn=%5B%22102713980%22%5D"
    )
    assert manager.paused is False
    await manager.close()


@pytest.mark.timeout(20)
async def test_browser_manager_pauses_on_expired_login_and_restriction_text(
    tmp_path: Path,
) -> None:
    settings = _live_settings(tmp_path, profile_name="access-errors")
    manager = BrowserManager(settings)
    async with manager.page() as page:
        await page.route(
            "**/*",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body="<html><body>Sign in</body></html>",
            ),
        )
        with pytest.raises(AuthenticationRequiredError, match="expired"):
            await manager.navigate(page, "https://www.linkedin.com/login")
        assert manager.paused is True

        manager.resume()
        await page.unroute("**/*")
        await page.route(
            "**/*",
            lambda route: route.fulfill(
                status=200,
                content_type="text/html",
                body="<html><body>Please verify your identity</body></html>",
            ),
        )
        with pytest.raises(RestrictionDetectedError, match="restriction-shaped"):
            await manager.navigate(page, "https://www.linkedin.com/jobs/search/")
        assert manager.paused is True

    await manager.close(persist_state=False)


@pytest.mark.timeout(20)
async def test_browser_manager_reuses_one_context_with_a_fresh_page_per_operation(
    tmp_path: Path,
) -> None:
    manager = BrowserManager(_live_settings(tmp_path, profile_name="fresh-pages"))

    async with manager.page() as first_page:
        assert manager.started is True
        first_page_reference = first_page
        popup_reference = await first_page.context.new_page()

    assert first_page_reference.is_closed() is True
    assert popup_reference.is_closed() is True
    assert manager.started is True

    async with manager.page() as second_page:
        assert second_page is not first_page_reference

    await manager.close()


@pytest.mark.asyncio
async def test_browser_manager_fails_closed_when_paused(tmp_path: Path) -> None:
    paused = BrowserManager(_live_settings(tmp_path, profile_name="paused"))
    paused.pause("operator review")
    with pytest.raises(AccessPausedError, match="operator review"):
        async with paused.page():
            pass


@pytest.mark.asyncio
@pytest.mark.parametrize("verification_headless", [True, False])
async def test_interactive_login_uses_and_preserves_the_local_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verification_headless: bool,
) -> None:
    settings = _live_settings(tmp_path, profile_name="interactive").model_copy(
        update={"browser_headless": verification_headless}
    )
    _mark_profile_initialized(settings)
    login_page = FakeLoginPage(
        remember_me_present=True,
        remember_me_checked=False,
    )
    verification_page = FakeLoginPage()
    login_context = FakeLoginContext(
        login_page,
        cookies=[_fake_li_at(persistent=True)],
    )
    verification_context = FakeLoginContext(
        verification_page,
        cookies=[_fake_li_at(persistent=True)],
    )
    playwright = FakeLoginPlaywright([login_context, verification_context])

    def fake_async_playwright() -> FakeLoginStarter:
        return FakeLoginStarter(playwright)

    async def no_sleep(_: float) -> None:
        return

    monkeypatch.setattr(manager_module, "async_playwright", cast(Any, fake_async_playwright))
    monkeypatch.setattr(manager_module.asyncio, "sleep", no_sleep)

    await login_interactively(settings)

    assert login_page.visited_urls == ["https://www.linkedin.com/login"]
    assert verification_page.visited_urls == ["https://www.linkedin.com/feed/"]
    assert login_page.remember_me.checked is True
    assert login_page.remember_me.check_timeout == 2_000
    assert playwright.chromium.launches == [
        (str(settings.browser_profile_path), False),
        (str(settings.browser_profile_path), verification_headless),
    ]
    assert login_context.closed is True
    assert verification_context.closed is True
    assert verification_page.closed is True
    assert playwright.stopped is True
    assert settings.browser_profile_path.is_dir()


@pytest.mark.asyncio
async def test_interactive_login_rejects_a_transient_session_cookie(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _live_settings(tmp_path, profile_name="transient")
    _mark_profile_initialized(settings)
    login_page = FakeLoginPage()
    login_context = FakeLoginContext(
        login_page,
        cookies=[_fake_li_at(persistent=False)],
    )
    playwright = FakeLoginPlaywright([login_context])

    def fake_async_playwright() -> FakeLoginStarter:
        return FakeLoginStarter(playwright)

    async def no_sleep(_: float) -> None:
        return

    monkeypatch.setattr(manager_module, "async_playwright", cast(Any, fake_async_playwright))
    monkeypatch.setattr(manager_module.asyncio, "sleep", no_sleep)

    with pytest.raises(AuthenticationRequiredError, match="not saved persistently"):
        await login_interactively(settings)

    assert playwright.chromium.launches == [
        (str(settings.browser_profile_path), False),
    ]
    assert login_context.closed is True
    assert playwright.stopped is True


@pytest.mark.asyncio
async def test_interactive_login_rejects_a_session_lost_during_clean_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _live_settings(tmp_path, profile_name="lost-on-reopen")
    _mark_profile_initialized(settings)
    login_context = FakeLoginContext(
        FakeLoginPage(),
        cookies=[_fake_li_at(persistent=True)],
    )
    verification_page = FakeLoginPage(
        feed_destination="https://www.linkedin.com/login",
    )
    verification_context = FakeLoginContext(
        verification_page,
        cookies=[],
    )
    playwright = FakeLoginPlaywright([login_context, verification_context])

    def fake_async_playwright() -> FakeLoginStarter:
        return FakeLoginStarter(playwright)

    async def no_sleep(_: float) -> None:
        return

    monkeypatch.setattr(manager_module, "async_playwright", cast(Any, fake_async_playwright))
    monkeypatch.setattr(manager_module.asyncio, "sleep", no_sleep)

    with pytest.raises(AuthenticationRequiredError, match="clean browser restart"):
        await login_interactively(settings)

    assert playwright.chromium.launches == [
        (str(settings.browser_profile_path), False),
        (str(settings.browser_profile_path), True),
    ]
    assert login_context.closed is True
    assert verification_context.closed is True
    assert playwright.stopped is True


@pytest.mark.asyncio
async def test_interactive_login_requires_an_explicitly_created_profile(tmp_path: Path) -> None:
    settings = _live_settings(tmp_path, profile_name="missing-for-login")

    with pytest.raises(ConfigurationError, match="profile create"):
        await login_interactively(settings)


@pytest.mark.asyncio
async def test_interactive_logout_uses_visible_controls_and_survives_clean_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _live_settings(tmp_path, profile_name="logout")
    _mark_profile_initialized(settings)
    first_context: FakeLogoutContext

    def clear_session() -> None:
        first_context.cookies_result = []

    account_menu = FakeLogoutControl()
    sign_out = FakeLogoutControl(on_click=clear_session)
    first_page = FakeLogoutPage(
        destination="https://www.linkedin.com/feed/",
        account_controls=[account_menu],
        sign_out_controls=[sign_out],
    )
    first_context = FakeLogoutContext(first_page, cookies=[_fake_li_at(persistent=True)])
    verification_page = FakeLogoutPage(destination="https://www.linkedin.com/login")
    verification_context = FakeLogoutContext(verification_page, cookies=[])
    playwright = FakeLogoutPlaywright([first_context, verification_context])

    async def safe_page(_: object, __: tuple[str, ...]) -> None:
        return

    async def no_sleep(_: float) -> None:
        return

    monkeypatch.setattr(
        manager_module,
        "async_playwright",
        cast(Any, lambda: FakeLogoutStarter(playwright)),
    )
    monkeypatch.setattr(manager_module, "assert_safe_linkedin_page", safe_page)
    monkeypatch.setattr(manager_module.asyncio, "sleep", no_sleep)

    assert await logout_interactively(settings) is True
    assert account_menu.clicked is True
    assert sign_out.clicked is True
    assert playwright.chromium.launches == [
        (str(settings.browser_profile_path), False),
        (str(settings.browser_profile_path), True),
    ]
    assert first_context.closed is True
    assert verification_context.closed is True
    assert playwright.stopped is True


@pytest.mark.asyncio
async def test_interactive_logout_is_idempotent_when_already_logged_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _live_settings(tmp_path, profile_name="already-logged-out")
    _mark_profile_initialized(settings)
    context = FakeLogoutContext(
        FakeLogoutPage(destination="https://www.linkedin.com/login"),
        cookies=[],
    )
    playwright = FakeLogoutPlaywright([context])
    monkeypatch.setattr(
        manager_module,
        "async_playwright",
        cast(Any, lambda: FakeLogoutStarter(playwright)),
    )

    assert await logout_interactively(settings) is False
    assert len(playwright.chromium.launches) == 1
    assert context.closed is True
    assert playwright.stopped is True


@pytest.mark.asyncio
async def test_interactive_logout_fails_closed_when_visible_account_menu_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _live_settings(tmp_path, profile_name="logout-drift")
    _mark_profile_initialized(settings)
    page = FakeLogoutPage(destination="https://www.linkedin.com/feed/")
    context = FakeLogoutContext(page, cookies=[_fake_li_at(persistent=True)])
    playwright = FakeLogoutPlaywright([context])

    async def safe_page(_: object, __: tuple[str, ...]) -> None:
        return

    monkeypatch.setattr(
        manager_module,
        "async_playwright",
        cast(Any, lambda: FakeLogoutStarter(playwright)),
    )
    monkeypatch.setattr(manager_module, "assert_safe_linkedin_page", safe_page)

    with pytest.raises(ParserDriftError, match="account menu"):
        await logout_interactively(settings)

    assert context.closed is True
    assert playwright.stopped is True


@pytest.mark.asyncio
async def test_interactive_logout_rejects_session_that_survives_clean_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _live_settings(tmp_path, profile_name="logout-reopen-failure")
    _mark_profile_initialized(settings)
    first_context: FakeLogoutContext

    def clear_session() -> None:
        first_context.cookies_result = []

    first_page = FakeLogoutPage(
        destination="https://www.linkedin.com/feed/",
        account_controls=[FakeLogoutControl()],
        sign_out_controls=[FakeLogoutControl(on_click=clear_session)],
    )
    first_context = FakeLogoutContext(first_page, cookies=[_fake_li_at(persistent=True)])
    verification_context = FakeLogoutContext(
        FakeLogoutPage(destination="https://www.linkedin.com/feed/"),
        cookies=[_fake_li_at(persistent=True)],
    )
    playwright = FakeLogoutPlaywright([first_context, verification_context])

    async def safe_page(_: object, __: tuple[str, ...]) -> None:
        return

    async def no_sleep(_: float) -> None:
        return

    monkeypatch.setattr(
        manager_module,
        "async_playwright",
        cast(Any, lambda: FakeLogoutStarter(playwright)),
    )
    monkeypatch.setattr(manager_module, "assert_safe_linkedin_page", safe_page)
    monkeypatch.setattr(manager_module.asyncio, "sleep", no_sleep)

    with pytest.raises(BrowserUnavailableError, match="clean browser restart"):
        await logout_interactively(settings)

    assert verification_context.closed is True
    assert playwright.stopped is True
