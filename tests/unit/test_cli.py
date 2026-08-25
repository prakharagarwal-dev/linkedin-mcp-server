from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast

import pytest

import linkedin_mcp.cli.commands.login as login_command
import linkedin_mcp.cli.commands.logout as logout_command
import linkedin_mcp.cli.commands.serve as serve_command
from linkedin_mcp.cli.manager import CLIManager
from linkedin_mcp.config import Settings


def test_cli_manager_builds_the_nested_command_hierarchy() -> None:
    parser = CLIManager.parser()

    assert parser.parse_args(["serve"]).command == "serve"
    assert parser.parse_args(["profile", "create"]).profile_command == "create"
    assert parser.parse_args(["profile", "reset", "--yes"]).yes is True


@pytest.mark.parametrize("removed", ["status", "stop"])
def test_cli_manager_does_not_expose_detached_host_commands(removed: str) -> None:
    with pytest.raises(SystemExit):
        CLIManager.parser().parse_args([removed])


def test_cli_manager_dispatches_with_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[Settings] = []

    def handler(_: argparse.Namespace, settings: Settings) -> int:
        observed.append(settings)
        return 7

    parser = argparse.ArgumentParser()
    parser.set_defaults(handler=handler)
    monkeypatch.setattr(CLIManager, "parser", staticmethod(lambda: parser))

    assert CLIManager().run([]) == 7
    assert len(observed) == 1


def test_cli_manager_returns_failure_for_configuration_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LINKEDIN_MCP_HTTP_PORT", "invalid")

    assert CLIManager().run(["serve"]) == 1
    assert "linkedin-mcp:" in capsys.readouterr().err


def test_serve_command_runs_the_http_application(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[Settings] = []
    monkeypatch.setattr(serve_command, "main", observed.append)
    settings = Settings()

    serve_command.handle(argparse.Namespace(), settings)

    assert observed == [settings]


@pytest.mark.asyncio
async def test_login_command_owns_and_closes_its_browser(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []

    class FakeBrowser:
        def __init__(self, _: Settings) -> None:
            events.append("created")

        async def login(self) -> None:
            events.append("login")

        async def close(self) -> None:
            events.append("close")

    monkeypatch.setattr(login_command, "BrowserManager", FakeBrowser)
    await login_command.execute(Settings(browser_profile_path=tmp_path / "profile"))

    assert events == ["created", "login", "close"]


@pytest.mark.asyncio
async def test_logout_command_closes_its_browser(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[str] = []

    class FakeBrowser:
        def __init__(self, _: Settings) -> None:
            events.append("created")

        async def logout(self) -> bool:
            events.append("logout")
            return True

        async def close(self) -> None:
            events.append("close")

    monkeypatch.setattr(logout_command, "BrowserManager", FakeBrowser)
    await logout_command.execute(Settings())

    assert events == ["created", "logout", "close"]
    assert '"status": "logged_out"' in capsys.readouterr().out


def test_cli_manager_handles_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = argparse.ArgumentParser()

    def fail(_: argparse.Namespace, __: Settings) -> None:
        raise OSError("secret detail")

    parser.set_defaults(handler=cast(object, fail))
    monkeypatch.setattr(CLIManager, "parser", staticmethod(lambda: parser))

    assert CLIManager().run([]) == 1
    error = capsys.readouterr().err
    assert "unexpected startup failure" in error
    assert "secret detail" not in error
