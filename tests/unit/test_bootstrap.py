from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

import linkedin_mcp.browser.bootstrap as bootstrap_module
from linkedin_mcp.browser.bootstrap import BrowserRuntimeBootstrap
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import BrowserUnavailableError
from linkedin_mcp.linkedin.models import BrowserSetupState

_TARGETS = (
    ("chromium-", "1234"),
    ("chromium_headless_shell-", "1234"),
)


@pytest.fixture(autouse=True)
def isolate_playwright_browser_environment() -> Iterator[None]:
    previous = os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
    yield
    if previous is None:
        os.environ.pop("PLAYWRIGHT_BROWSERS_PATH", None)
    else:
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = previous


def _settings(tmp_path: Path, *, auto_install: bool = True) -> Settings:
    return Settings(
        browser_auto_install=auto_install,
        browser_cache_path=tmp_path / "browsers",
    )


def _mark_installed(path: Path) -> None:
    for prefix, revision in _TARGETS:
        target = path / f"{prefix}{revision}"
        target.mkdir(parents=True)
        (target / "INSTALLATION_COMPLETE").write_text("", encoding="utf-8")


def _set_mode(path: Path, mode: int) -> None:
    path.chmod(mode)


def _playwright_registry_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    package_root = tmp_path / "playwright"
    monkeypatch.setattr(bootstrap_module.playwright, "__file__", str(package_root / "__init__.py"))
    registry = package_root / "driver" / "package" / "browsers.json"
    registry.parent.mkdir(parents=True)
    return registry


def _expected_targets() -> tuple[tuple[str, str], ...]:
    return BrowserRuntimeBootstrap._expected_targets()  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_browser_bootstrap_installs_into_shared_user_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(
        BrowserRuntimeBootstrap,
        "_expected_targets",
        staticmethod(lambda: _TARGETS),
    )
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        typed_environment = cast(dict[str, str], environment)
        _mark_installed(Path(typed_environment["PLAYWRIGHT_BROWSERS_PATH"]))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(bootstrap_module.subprocess, "run", fake_run)
    runtime = BrowserRuntimeBootstrap(_settings(tmp_path))

    await runtime.ensure_ready()

    assert runtime.state is BrowserSetupState.READY
    assert runtime.ready is True
    assert commands[0][-4:] == ["-m", "playwright", "install", "chromium"]
    assert runtime.cache_path == tmp_path / "browsers"


@pytest.mark.asyncio
async def test_browser_bootstrap_reuses_matching_install_without_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(
        BrowserRuntimeBootstrap,
        "_expected_targets",
        staticmethod(lambda: _TARGETS),
    )
    settings = _settings(tmp_path)
    _mark_installed(settings.browser_cache_path)

    def unexpected_run(
        command: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        pytest.fail(f"matching install must be reused: {command!r}")

    monkeypatch.setattr(bootstrap_module.subprocess, "run", unexpected_run)
    runtime = BrowserRuntimeBootstrap(settings)

    assert runtime.inspect_state() is BrowserSetupState.READY
    await runtime.ensure_ready()

    assert runtime.state is BrowserSetupState.READY


@pytest.mark.asyncio
async def test_browser_bootstrap_can_delegate_to_an_operator_managed_browser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    runtime = BrowserRuntimeBootstrap(_settings(tmp_path, auto_install=False))

    await runtime.ensure_ready()

    assert runtime.state is BrowserSetupState.DISABLED
    assert runtime.ready is True
    assert "PLAYWRIGHT_BROWSERS_PATH" not in bootstrap_module.os.environ


@pytest.mark.asyncio
async def test_browser_bootstrap_skips_background_start_when_install_is_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    runtime = BrowserRuntimeBootstrap(_settings(tmp_path, auto_install=False))

    assert runtime.inspect_state() is BrowserSetupState.DISABLED
    runtime.start()
    await runtime.close()


@pytest.mark.asyncio
async def test_browser_bootstrap_starts_only_one_pending_background_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = BrowserRuntimeBootstrap(_settings(tmp_path))
    started = asyncio.Event()
    never_complete = asyncio.Event()
    calls = 0

    async def pending_setup(*, force: bool = False) -> None:
        del force
        nonlocal calls
        calls += 1
        started.set()
        await never_complete.wait()

    monkeypatch.setattr(runtime, "ensure_ready", pending_setup)

    runtime.start()
    runtime.start()
    await started.wait()
    assert calls == 1

    await runtime.close()


@pytest.mark.asyncio
async def test_browser_bootstrap_consumes_completed_background_task_before_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = BrowserRuntimeBootstrap(_settings(tmp_path))
    calls = 0

    async def completed_setup(*, force: bool = False) -> None:
        del force
        nonlocal calls
        calls += 1

    monkeypatch.setattr(runtime, "ensure_ready", completed_setup)

    runtime.start()
    await asyncio.sleep(0)
    runtime.start()
    await asyncio.sleep(0)
    await runtime.close()

    assert calls == 2


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode preservation")
@pytest.mark.asyncio
async def test_browser_bootstrap_reuses_operator_managed_read_only_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = tmp_path / "operator-browsers"
    _mark_installed(cache_path)
    _set_mode(cache_path, 0o555)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(cache_path))
    monkeypatch.setattr(
        BrowserRuntimeBootstrap,
        "_expected_targets",
        staticmethod(lambda: _TARGETS),
    )
    runtime = BrowserRuntimeBootstrap(_settings(tmp_path))

    try:
        await runtime.ensure_ready()
        assert cache_path.stat().st_mode & 0o777 == 0o555
    finally:
        _set_mode(cache_path, 0o700)


@pytest.mark.asyncio
async def test_browser_bootstrap_projects_only_a_safe_install_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(
        BrowserRuntimeBootstrap,
        "_expected_targets",
        staticmethod(lambda: _TARGETS),
    )

    def fake_run(
        command: list[str],
        **_: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "COOKIE=must-not-leak")

    monkeypatch.setattr(bootstrap_module.subprocess, "run", fake_run)
    runtime = BrowserRuntimeBootstrap(_settings(tmp_path))

    with pytest.raises(BrowserUnavailableError) as raised:
        await runtime.ensure_ready()

    assert runtime.state is BrowserSetupState.FAILED
    assert "must-not-leak" not in str(raised.value)

    with pytest.raises(BrowserUnavailableError) as repeated:
        runtime._raise_if_failed()  # pyright: ignore[reportPrivateUsage]
    assert repeated.value is raised.value


def test_browser_bootstrap_reads_supported_targets_from_playwright_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _playwright_registry_path(tmp_path, monkeypatch)
    registry.write_text(
        """
        {
          "browsers": [
            {"name": "chromium", "revision": "1234"},
            {"name": "chromium-headless-shell", "revision": 1234},
            {"name": "firefox", "revision": "9999"},
            {"name": 12, "revision": "ignored"},
            {"name": "chromium"},
            "not-an-entry"
          ]
        }
        """,
        encoding="utf-8",
    )

    assert _expected_targets() == _TARGETS


def test_browser_bootstrap_rejects_missing_malformed_or_wrong_shaped_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = _playwright_registry_path(tmp_path, monkeypatch)

    registry.write_text("not-json", encoding="utf-8")
    assert _expected_targets() == ()

    registry.write_text("[]", encoding="utf-8")
    assert _expected_targets() == ()

    registry.write_text('{"browsers": {}}', encoding="utf-8")
    assert _expected_targets() == ()

    registry.unlink()
    assert _expected_targets() == ()


def test_browser_bootstrap_reports_no_install_when_registry_has_no_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        BrowserRuntimeBootstrap,
        "_expected_targets",
        staticmethod(lambda: ()),
    )

    assert BrowserRuntimeBootstrap(_settings(tmp_path)).inspect_state() is (
        BrowserSetupState.NOT_STARTED
    )


def test_browser_bootstrap_projects_operating_system_install_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        BrowserRuntimeBootstrap,
        "_expected_targets",
        staticmethod(lambda: _TARGETS),
    )

    def unavailable_run(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        raise OSError("sensitive operating-system detail")

    monkeypatch.setattr(bootstrap_module.subprocess, "run", unavailable_run)
    runtime = BrowserRuntimeBootstrap(_settings(tmp_path))

    with pytest.raises(BrowserUnavailableError) as raised:
        runtime._install()  # pyright: ignore[reportPrivateUsage]

    assert "sensitive operating-system detail" not in str(raised.value)
