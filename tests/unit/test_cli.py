from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import cast

import pytest
from mcp.server.fastmcp import FastMCP

import linkedin_mcp.__main__ as cli
from linkedin_mcp.config import Settings
from linkedin_mcp.container import AppContainer

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
    assert cli.parser().parse_args(["doctor"]).command == "doctor"


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
        live_enabled=True,
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
async def test_doctor_requires_browser_and_profile_only_when_live_is_enabled(
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
        live_enabled=True,
        browser_cache_path=tmp_path / "missing-browser",
        browser_profile_path=tmp_path / "missing-profile",
    )

    live_code = await cli._doctor(settings)  # pyright: ignore[reportPrivateUsage]
    live_report = json.loads(capsys.readouterr().out)
    disabled_code = await cli._doctor(  # pyright: ignore[reportPrivateUsage]
        settings.model_copy(update={"live_enabled": False})
    )
    disabled_report = json.loads(capsys.readouterr().out)

    assert live_code == 1
    assert live_report["browser_setup"] == "not_started"
    assert live_report["profile_present"] is False
    assert disabled_code == 0
    assert disabled_report["live_enabled"] is False


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


def test_main_setup_login_and_serve_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    setup_settings: list[Settings] = []
    login_settings: list[Settings] = []

    async def fake_setup(settings: Settings) -> None:
        setup_settings.append(settings)

    async def fake_login(settings: Settings) -> None:
        login_settings.append(settings)

    monkeypatch.setattr(cli, "_setup", fake_setup)
    monkeypatch.setattr(cli, "login_interactively", fake_login)
    monkeypatch.setattr(sys, "argv", ["linkedin-mcp", "setup"])
    cli.main()
    monkeypatch.setattr(sys, "argv", ["linkedin-mcp", "login"])
    cli.main()

    class FakeMCP:
        def __init__(self) -> None:
            self.transport: str | None = None

        def run(self, *, transport: str) -> None:
            self.transport = transport

    fake_mcp = FakeMCP()

    def fake_container_factory(_: Settings) -> AppContainer:
        return cast(AppContainer, object())

    def fake_server_factory(_: AppContainer) -> FastMCP[None]:
        return cast(FastMCP[None], fake_mcp)

    monkeypatch.setattr(cli, "create_production_container", fake_container_factory)
    monkeypatch.setattr(cli, "create_mcp_server", fake_server_factory)
    monkeypatch.setattr(
        sys,
        "argv",
        ["linkedin-mcp", "serve", "--transport", "streamable-http"],
    )
    cli.main()

    assert len(setup_settings) == 1
    assert len(login_settings) == 1
    assert fake_mcp.transport == "streamable-http"


def test_main_projects_safe_configuration_errors_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def fail_login(_: Settings) -> None:
        raise ValueError("safe failure")

    monkeypatch.setattr(cli, "login_interactively", fail_login)
    monkeypatch.setattr(sys, "argv", ["linkedin-mcp", "login"])

    with pytest.raises(SystemExit) as raised:
        cli.main()

    assert raised.value.code == 1
    assert "linkedin-mcp: safe failure" in capsys.readouterr().err


def test_main_does_not_project_unexpected_startup_details(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class UnexpectedFailure(Exception):
        pass

    async def fail_login(_: Settings) -> None:
        raise UnexpectedFailure("session-cookie-must-not-be-projected")

    monkeypatch.setattr(cli, "login_interactively", fail_login)
    monkeypatch.setattr(sys, "argv", ["linkedin-mcp", "login"])

    with pytest.raises(SystemExit) as raised:
        cli.main()

    output = capsys.readouterr().err
    assert raised.value.code == 1
    assert "unexpected startup failure" in output
    assert "session-cookie" not in output
