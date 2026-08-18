from __future__ import annotations

import asyncio
import json
import signal
import sys
from pathlib import Path
from typing import Any, cast

import pytest

import linkedin_mcp.cli.commands.doctor as doctor_command
import linkedin_mcp.cli.commands.login as login_command
import linkedin_mcp.cli.commands.logout as logout_command
import linkedin_mcp.cli.commands.profile.create as profile_create_command
import linkedin_mcp.cli.commands.profile.reset as profile_reset_command
import linkedin_mcp.cli.commands.profile.status as profile_status_command
import linkedin_mcp.cli.commands.serve as serve_command
import linkedin_mcp.cli.commands.setup as setup_command
import linkedin_mcp.cli.commands.status as status_command
import linkedin_mcp.cli.commands.stop as stop_command
import linkedin_mcp.cli.main as cli
import linkedin_mcp.transport.lock as owned_operation
from linkedin_mcp.browser import BrowserProfileResetResult, BrowserProfileStatus
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import ConfigurationError
from linkedin_mcp.transport import (
    AccountProcessLock,
    AccountRuntimeOwner,
    AccountRuntimeStatus,
    inspect_account_runtime,
)

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

    assert arguments.command == "serve"
    assert arguments.transport == "streamable-http"
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
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["_runtime"])


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
        doctor_command.BrowserRuntimeBootstrap,
        "_expected_targets",
        staticmethod(lambda: _TARGETS),
    )
    settings = Settings(
        browser_cache_path=cache_path,
        browser_profile_path=profile_path,
    )

    exit_code = await doctor_command.execute(settings)
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
        doctor_command.BrowserRuntimeBootstrap,
        "_expected_targets",
        staticmethod(lambda: _TARGETS),
    )
    settings = Settings(
        browser_cache_path=tmp_path / "missing-browser",
        browser_profile_path=tmp_path / "missing-profile",
    )

    exit_code = await doctor_command.execute(settings)
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

    monkeypatch.setattr(setup_command, "BrowserRuntimeBootstrap", FakeBootstrap)

    await setup_command.execute(Settings())
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

    monkeypatch.setattr(setup_command, "execute", fake_setup)
    monkeypatch.setattr(login_command, "login_interactively", fake_login)
    monkeypatch.setattr(serve_command, "execute", fake_serve)
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


def test_main_dispatches_every_remaining_current_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def record_async(name: str) -> None:
        calls.append(name)

    async def fake_profile_create(_: Settings) -> None:
        await record_async("profile-create")

    async def fake_logout(_: Settings) -> None:
        await record_async("logout")

    async def fake_status(_: Settings) -> None:
        await record_async("status")

    async def fake_profile_reset(_: Settings, *, confirmed: bool) -> None:
        assert confirmed is True
        calls.append("profile-reset")

    def fake_profile_status(_: Settings) -> None:
        calls.append("profile-status")

    def fake_stop(_: Settings, *, timeout_seconds: float) -> None:
        assert timeout_seconds == 4
        calls.append("stop")

    async def successful_doctor(_: Settings) -> int:
        calls.append("doctor")
        return 0

    monkeypatch.setattr(profile_create_command, "execute", fake_profile_create)
    monkeypatch.setattr(profile_status_command, "execute", fake_profile_status)
    monkeypatch.setattr(profile_reset_command, "execute", fake_profile_reset)
    monkeypatch.setattr(logout_command, "execute", fake_logout)
    monkeypatch.setattr(doctor_command, "execute", successful_doctor)
    monkeypatch.setattr(status_command, "execute", fake_status)
    monkeypatch.setattr(stop_command, "execute", fake_stop)
    monkeypatch.setenv("LINKEDIN_MCP_RUNTIME_LOCK_PATH", str(tmp_path / "runtime.lock"))

    invocations = (
        (["linkedin-mcp", "profile", "create"], None),
        (["linkedin-mcp", "profile", "status"], None),
        (["linkedin-mcp", "profile", "reset", "--yes"], None),
        (["linkedin-mcp", "logout"], None),
        (["linkedin-mcp", "doctor"], 0),
        (["linkedin-mcp", "status"], None),
        (["linkedin-mcp", "stop", "--timeout", "4"], None),
    )
    for argv, expected_exit in invocations:
        monkeypatch.setattr(sys, "argv", argv)
        if expected_exit is None:
            cli.main()
        else:
            with pytest.raises(SystemExit) as raised:
                cli.main()
            assert raised.value.code == expected_exit

    assert calls == [
        "profile-create",
        "profile-status",
        "profile-reset",
        "logout",
        "doctor",
        "status",
        "stop",
    ]


@pytest.mark.asyncio
async def test_logout_and_owned_operation_complete_without_a_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(runtime_lock_path=tmp_path / "runtime.lock")

    async def no_signal() -> signal.Signals:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def logged_out(_: Settings) -> bool:
        return True

    monkeypatch.setattr(
        "linkedin_mcp.transport.lock._wait_for_stop_signal",
        no_signal,
    )
    monkeypatch.setattr(logout_command, "logout_interactively", logged_out)

    await logout_command.execute(settings)

    assert json.loads(capsys.readouterr().out) == {
        "logged_out": True,
        "status": "logged_out",
    }


def test_main_projects_safe_configuration_errors_to_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fail_login(_: Settings) -> None:
        raise ValueError("safe failure")

    monkeypatch.setattr(login_command, "login_interactively", fail_login)
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

    monkeypatch.setattr(login_command, "login_interactively", fail_login)
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

    monkeypatch.setattr(profile_create_command, "BrowserProfileManager", FakeProfileManager)
    monkeypatch.setattr(profile_status_command, "BrowserProfileManager", FakeProfileManager)
    monkeypatch.setattr(profile_reset_command, "BrowserProfileManager", FakeProfileManager)

    await profile_create_command.execute(settings)
    created = json.loads(capsys.readouterr().out)
    profile_status_command.execute(settings)
    status = json.loads(capsys.readouterr().out)
    await profile_reset_command.execute(
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


@pytest.mark.asyncio
async def test_runtime_status_and_stop_report_exact_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(runtime_lock_path=tmp_path / "runtime.lock")
    owner = AccountRuntimeOwner(
        pid=4321,
        instance_id="instance-1",
        account_id="personal",
        command="shared-runtime",
        transport="shared-loopback",
        started_at="2026-08-03T10:00:00+00:00",
        endpoint="http://127.0.0.1:8000/mcp",
        version="0.16.0",
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

    monkeypatch.setattr(status_command, "inspect_account_runtime", fake_inspect)
    monkeypatch.setattr(stop_command, "inspect_account_runtime", fake_inspect)
    monkeypatch.setattr(stop_command, "stop_account_runtime", fake_stop)

    async def fake_runtime_status(_: str) -> dict[str, object]:
        return {
            "queue_depth": 3,
            "active_browser_operation": True,
            "active_task": "linkedin.jobs.search",
            "accepting_calls": True,
        }

    monkeypatch.setattr(status_command, "read_host_status", fake_runtime_status)

    await status_command.execute(settings)
    status = json.loads(capsys.readouterr().out)
    stop_command.execute(settings, timeout_seconds=12.5)
    stopped = json.loads(capsys.readouterr().out)

    assert status == {
        "account_id": "personal",
        "accepting_calls": True,
        "active_browser_operation": True,
        "active_task": "linkedin.jobs.search",
        "command": "shared-runtime",
        "endpoint": "http://127.0.0.1:8000/mcp",
        "healthy": True,
        "lock_path": str(settings.runtime_lock_path),
        "pid": 4321,
        "queue_depth": 3,
        "running": True,
        "started_at": "2026-08-03T10:00:00+00:00",
        "transport": "shared-loopback",
        "version": "0.16.0",
    }
    assert stopped == {
        "account_id": "personal",
        "command": "shared-runtime",
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
            owned_operation.claim_account_runtime(
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
        profile_reset_command.confirm(settings)

    monkeypatch.setattr("builtins.input", confirm_reset)
    profile_reset_command.confirm(settings)


def test_profile_reset_confirmation_rejects_a_noninteractive_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NonInteractiveInput:
        @staticmethod
        def isatty() -> bool:
            return False

    monkeypatch.setattr(sys, "stdin", cast(Any, NonInteractiveInput()))
    with pytest.raises(ValueError, match="interactive terminal"):
        profile_reset_command.confirm(Settings(browser_profile_path=tmp_path / "profile"))


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

    monkeypatch.setattr(
        "linkedin_mcp.transport.lock._wait_for_stop_signal",
        signal_after_start,
    )

    with pytest.raises(RuntimeError, match="SIGTERM"):
        await owned_operation.run_owned_operation(
            settings,
            command="login",
            operation=blocking_operation,
        )

    assert finalized.is_set() is True
    assert inspect_account_runtime(settings.runtime_lock_path).running is False


@pytest.mark.asyncio
async def test_stdio_serve_attaches_proxy_to_shared_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, str | None]] = []

    async def fake_ensure(_: Settings) -> str:
        events.append(("runtime-ready", None))
        return "http://127.0.0.1:8123/mcp"

    async def fake_proxy(endpoint: str) -> None:
        events.append(("proxy-running", endpoint))

    monkeypatch.setattr(serve_command, "ensure_host", fake_ensure)
    monkeypatch.setattr(serve_command, "run_stdio_proxy", fake_proxy)

    await serve_command.execute(Settings(transport="stdio"))

    assert events == [
        ("runtime-ready", None),
        ("proxy-running", "http://127.0.0.1:8123/mcp"),
    ]


@pytest.mark.asyncio
async def test_streamable_http_starts_shared_runtime_when_no_owner_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []

    def fake_inspect(_: Path) -> AccountRuntimeStatus:
        return AccountRuntimeStatus(running=False)

    async def fake_runtime(_: Settings) -> None:
        events.append("runtime-running")

    monkeypatch.setattr(serve_command, "inspect_account_runtime", fake_inspect)
    monkeypatch.setattr(serve_command, "run_host", fake_runtime)

    await serve_command.execute(
        Settings(
            transport="streamable-http",
            runtime_lock_path=tmp_path / "runtime.lock",
        )
    )

    assert events == ["runtime-running"]


@pytest.mark.asyncio
async def test_streamable_http_reuses_an_owner_and_recovers_an_election_race(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = Settings(
        transport="streamable-http",
        runtime_lock_path=tmp_path / "runtime.lock",
    )
    endpoint = "http://127.0.0.1:8000/mcp"

    def running(_: Path) -> AccountRuntimeStatus:
        return AccountRuntimeStatus(running=True)

    async def wait(_: Settings) -> str:
        return endpoint

    monkeypatch.setattr(serve_command, "inspect_account_runtime", running)
    monkeypatch.setattr(serve_command, "wait_for_host", wait)
    await serve_command.execute(settings)
    assert endpoint in capsys.readouterr().err

    inspections = iter(
        (
            AccountRuntimeStatus(running=False),
            AccountRuntimeStatus(running=True),
        )
    )

    def racing(_: Path) -> AccountRuntimeStatus:
        return next(inspections)

    async def lose_election(_: Settings) -> None:
        raise ConfigurationError("another owner won")

    monkeypatch.setattr(serve_command, "inspect_account_runtime", racing)
    monkeypatch.setattr(serve_command, "run_host", lose_election)
    await serve_command.execute(settings)
    assert endpoint in capsys.readouterr().err
