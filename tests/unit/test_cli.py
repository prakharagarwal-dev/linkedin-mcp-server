from __future__ import annotations

import asyncio
import json
import signal
import sys
from pathlib import Path
from typing import Any, cast

import pytest

import linkedin_mcp.__main__ as cli
from linkedin_mcp.application import (
    AccountProcessLock,
    AccountRuntimeOwner,
    AccountRuntimeStatus,
)
from linkedin_mcp.browser import BrowserProfileResetResult, BrowserProfileStatus
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import ConfigurationError

_TARGETS = (
    ("chromium-", "1234"),
    ("chromium_headless_shell-", "1234"),
)


def _mark_browser_ready(path: Path) -> None:
    for prefix, revision in _TARGETS:
        target = path / f"{prefix}{revision}"
        target.mkdir(parents=True)
        (target / "INSTALLATION_COMPLETE").write_text("", encoding="utf-8")


def test_parser_and_transport_override() -> None:
    arguments = cli.parser().parse_args(["serve", "--transport", "streamable-http"])
    settings = cli._settings(arguments.transport)  # pyright: ignore[reportPrivateUsage]

    assert arguments.command == "serve"
    assert settings.transport == "streamable-http"
    assert cli._settings().transport == "stdio"  # pyright: ignore[reportPrivateUsage]
    assert cli.parser().parse_args(["setup"]).command == "setup"
    assert cli.parser().parse_args(["login"]).command == "login"
    assert cli.parser().parse_args(["logout"]).command == "logout"
    assert cli.parser().parse_args(["doctor"]).command == "doctor"
    assert cli.parser().parse_args(["status"]).command == "status"
    assert cli.parser().parse_args(["stop", "--timeout", "12"]).timeout == 12
    assert cli.parser().parse_args(["profile", "create"]).profile_command == "create"
    assert cli.parser().parse_args(["profile", "status"]).profile_command == "status"
    reset = cli.parser().parse_args(["profile", "reset", "--yes"])
    assert reset.profile_command == "reset"
    assert reset.yes is True


@pytest.mark.asyncio
async def test_doctor_reports_ready_browser_profile_and_process_local_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cache_path = tmp_path / "browsers"
    profile_path = tmp_path / "profile"
    _mark_browser_ready(cache_path)
    profile_path.mkdir()
    (profile_path / "Preferences").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(
        cli.BrowserRuntimeBootstrap,
        "_expected_targets",
        staticmethod(lambda: _TARGETS),
    )
    settings = Settings(
        browser_cache_path=cache_path,
        browser_profile_path=profile_path,
    )

    exit_code = await cli._doctor(settings)  # pyright: ignore[reportPrivateUsage]
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert report["browser_setup"] == "ready"
    assert report["profile_present"] is True
    assert report["operation_state"] == "process_local"


@pytest.mark.asyncio
async def test_doctor_requires_browser_and_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.setattr(
        cli.BrowserRuntimeBootstrap,
        "_expected_targets",
        staticmethod(lambda: _TARGETS),
    )
    settings = Settings(
        browser_cache_path=tmp_path / "missing-browser",
        browser_profile_path=tmp_path / "missing-profile",
    )

    exit_code = await cli._doctor(settings)  # pyright: ignore[reportPrivateUsage]
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert report["browser_setup"] == "not_started"
    assert report["profile_present"] is False
    assert "live_enabled" not in report


@pytest.mark.asyncio
async def test_setup_forces_browser_install_and_reports_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[bool] = []

    class FakeBootstrap:
        def __init__(self, _: Settings) -> None:
            self.cache_path = tmp_path / "browsers"

        async def ensure_ready(self, *, force: bool = False) -> None:
            calls.append(force)

    monkeypatch.setattr(cli, "BrowserRuntimeBootstrap", FakeBootstrap)

    await cli._setup(Settings())  # pyright: ignore[reportPrivateUsage]
    report = json.loads(capsys.readouterr().out)

    assert calls == [True]
    assert report == {"browser": "ready", "cache_path": str(tmp_path / "browsers")}


def test_main_setup_login_and_serve_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_settings: list[Settings] = []
    login_settings: list[Settings] = []
    serve_settings: list[Settings] = []

    async def fake_setup(settings: Settings) -> None:
        setup_settings.append(settings)

    async def fake_login(settings: Settings) -> None:
        login_settings.append(settings)

    async def fake_serve(settings: Settings) -> None:
        serve_settings.append(settings)

    monkeypatch.setattr(cli, "_setup", fake_setup)
    monkeypatch.setattr(cli, "login_interactively", fake_login)
    monkeypatch.setattr(cli, "_serve", fake_serve)
    monkeypatch.setenv("LINKEDIN_MCP_RUNTIME_LOCK_PATH", str(tmp_path / "runtime.lock"))
    monkeypatch.setattr(sys, "argv", ["linkedin-mcp", "setup"])
    cli.main()
    monkeypatch.setattr(sys, "argv", ["linkedin-mcp", "login"])
    cli.main()

    monkeypatch.setattr(
        sys,
        "argv",
        ["linkedin-mcp", "serve", "--transport", "streamable-http"],
    )
    cli.main()

    assert len(setup_settings) == 1
    assert len(login_settings) == 1
    assert len(serve_settings) == 1
    assert serve_settings[0].transport == "streamable-http"


def test_main_projects_safe_configuration_errors_to_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fail_login(_: Settings) -> None:
        raise ValueError("safe failure")

    monkeypatch.setattr(cli, "login_interactively", fail_login)
    monkeypatch.setenv("LINKEDIN_MCP_RUNTIME_LOCK_PATH", str(tmp_path / "runtime.lock"))
    monkeypatch.setattr(sys, "argv", ["linkedin-mcp", "login"])

    with pytest.raises(SystemExit) as raised:
        cli.main()

    assert raised.value.code == 1
    assert "linkedin-mcp: safe failure" in capsys.readouterr().err


def test_main_does_not_project_unexpected_startup_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class UnexpectedFailure(Exception):
        pass

    async def fail_login(_: Settings) -> None:
        raise UnexpectedFailure("session-cookie-must-not-be-projected")

    monkeypatch.setattr(cli, "login_interactively", fail_login)
    monkeypatch.setenv("LINKEDIN_MCP_RUNTIME_LOCK_PATH", str(tmp_path / "runtime.lock"))
    monkeypatch.setattr(sys, "argv", ["linkedin-mcp", "login"])

    with pytest.raises(SystemExit) as raised:
        cli.main()

    output = capsys.readouterr().err
    assert raised.value.code == 1
    assert "unexpected startup failure" in output
    assert "session-cookie" not in output


@pytest.mark.asyncio
async def test_profile_commands_report_create_status_and_recoverable_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(
        browser_profile_path=tmp_path / "profile",
        runtime_lock_path=tmp_path / "runtime.lock",
    )

    class FakeProfileManager:
        def __init__(self, _: Settings) -> None:
            self.path = settings.browser_profile_path

        def inspect(self) -> BrowserProfileStatus:
            return BrowserProfileStatus(path=self.path, exists=True, initialized=True)

        async def create(self) -> bool:
            return True

        async def reset(self) -> BrowserProfileResetResult:
            return BrowserProfileResetResult(
                path=self.path,
                archived_path=tmp_path / "profile.backup",
            )

    monkeypatch.setattr(cli, "BrowserProfileManager", FakeProfileManager)

    await cli._profile_create(settings)  # pyright: ignore[reportPrivateUsage]
    created = json.loads(capsys.readouterr().out)
    cli._profile_status(settings)  # pyright: ignore[reportPrivateUsage]
    status = json.loads(capsys.readouterr().out)
    await cli._profile_reset(  # pyright: ignore[reportPrivateUsage]
        settings,
        confirmed=True,
    )
    reset = json.loads(capsys.readouterr().out)

    assert created == {
        "created": True,
        "initialized": True,
        "path": str(settings.browser_profile_path),
    }
    assert status["initialized"] is True
    assert status["runtime_running"] is False
    assert reset["archived_path"] == str(tmp_path / "profile.backup")
    assert reset["reset"] is True


def test_runtime_status_and_stop_report_exact_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(runtime_lock_path=tmp_path / "runtime.lock")
    owner = AccountRuntimeOwner(
        pid=4321,
        instance_id="instance-1",
        account_id="personal",
        command="serve",
        transport="stdio",
        started_at="2026-08-03T10:00:00+00:00",
    )
    inspections = 0

    def fake_inspect(_: Path) -> AccountRuntimeStatus:
        nonlocal inspections
        inspections += 1
        return AccountRuntimeStatus(running=True, owner=owner)

    stop_calls: list[tuple[Path, float]] = []

    def fake_stop(path: Path, *, timeout_seconds: float) -> AccountRuntimeStatus:
        stop_calls.append((path, timeout_seconds))
        return AccountRuntimeStatus(running=False, owner=owner)

    monkeypatch.setattr(cli, "inspect_account_runtime", fake_inspect)
    monkeypatch.setattr(cli, "stop_account_runtime", fake_stop)

    cli._status(settings)  # pyright: ignore[reportPrivateUsage]
    status = json.loads(capsys.readouterr().out)
    cli._stop(settings, timeout_seconds=12.5)  # pyright: ignore[reportPrivateUsage]
    stopped = json.loads(capsys.readouterr().out)

    assert status == {
        "account_id": "personal",
        "command": "serve",
        "lock_path": str(settings.runtime_lock_path),
        "pid": 4321,
        "running": True,
        "started_at": "2026-08-03T10:00:00+00:00",
        "transport": "stdio",
    }
    assert stopped == {
        "account_id": "personal",
        "command": "serve",
        "pid": 4321,
        "status": "stopped",
        "stopped": True,
    }
    assert inspections == 2
    assert stop_calls == [(settings.runtime_lock_path, 12.5)]


def test_login_refuses_to_open_profile_owned_by_running_server(
    tmp_path: Path,
) -> None:
    settings = Settings(runtime_lock_path=tmp_path / "runtime.lock")
    owner = AccountProcessLock(settings.runtime_lock_path, command="serve")
    owner.acquire()
    try:
        with (
            pytest.raises(ConfigurationError, match="linkedin-mcp stop"),
            cli._claim_account_runtime(  # pyright: ignore[reportPrivateUsage]
                settings,
                command="login",
            ),
        ):
            raise AssertionError("The conflicting lock must not be acquired.")
    finally:
        owner.release()


def test_profile_reset_confirmation_requires_exact_interactive_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(browser_profile_path=tmp_path / "profile")

    class InteractiveInput:
        @staticmethod
        def isatty() -> bool:
            return True

    def reject_reset(_: str) -> str:
        return "no"

    def confirm_reset(_: str) -> str:
        return "RESET"

    monkeypatch.setattr(sys, "stdin", cast(Any, InteractiveInput()))
    monkeypatch.setattr("builtins.input", reject_reset)
    with pytest.raises(ValueError, match="cancelled"):
        cli._confirm_profile_reset(settings)  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr("builtins.input", confirm_reset)
    cli._confirm_profile_reset(settings)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.asyncio
async def test_owned_cli_operation_cleans_up_before_releasing_lock_on_stop_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(runtime_lock_path=tmp_path / "runtime.lock")
    started = asyncio.Event()
    finalized = asyncio.Event()

    async def blocking_operation() -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            finalized.set()

    async def signal_after_start() -> signal.Signals:
        await started.wait()
        return signal.SIGTERM

    monkeypatch.setattr(cli, "_wait_for_stop_signal", signal_after_start)

    with pytest.raises(RuntimeError, match="SIGTERM"):
        await cli._run_owned_operation(  # pyright: ignore[reportPrivateUsage]
            settings,
            command="login",
            operation=blocking_operation,
        )

    assert finalized.is_set() is True
    assert cli.inspect_account_runtime(settings.runtime_lock_path).running is False


@pytest.mark.asyncio
async def test_stdio_signal_quiesces_before_server_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeServer:
        async def run_stdio_async(self) -> None:
            events.append("server-started")
            try:
                await asyncio.Event().wait()
            finally:
                events.append("server-stopped")

    class FakeContainer:
        async def quiesce(self) -> None:
            events.append("quiesced")

    async def immediate_signal() -> signal.Signals:
        await asyncio.sleep(0)
        return signal.SIGTERM

    monkeypatch.setattr(cli, "_wait_for_stop_signal", immediate_signal)

    await cli._serve_stdio(  # pyright: ignore[reportPrivateUsage]
        cast(Any, FakeServer()),
        cast(Any, FakeContainer()),
    )

    assert events == ["server-started", "quiesced", "server-stopped"]


@pytest.mark.asyncio
async def test_streamable_http_owns_one_container_for_listener_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    lifecycle_flags: list[bool] = []

    class FakeContainer:
        async def start(self) -> None:
            events.append("container-started")

        async def close(self) -> None:
            events.append("container-closed")

    class FakeServer:
        async def run_streamable_http_async(self) -> None:
            events.append("http-running")

    container = FakeContainer()

    def fake_container_factory(_: Settings) -> object:
        return container

    def fake_server_factory(
        _: object,
        *,
        manage_container_lifecycle: bool = True,
    ) -> object:
        lifecycle_flags.append(manage_container_lifecycle)
        return FakeServer()

    monkeypatch.setattr(cli, "create_production_container", cast(Any, fake_container_factory))
    monkeypatch.setattr(cli, "create_mcp_server", cast(Any, fake_server_factory))

    await cli._serve(  # pyright: ignore[reportPrivateUsage]
        Settings(transport="streamable-http")
    )

    assert lifecycle_flags == [False]
    assert events == ["container-started", "http-running", "container-closed"]
