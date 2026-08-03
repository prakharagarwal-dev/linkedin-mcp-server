"""Command-line entrypoint for server, runtime, profile, and authentication lifecycle."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager, suppress
from typing import cast

import anyio
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from linkedin_mcp.application import (
    AccountProcessLock,
    inspect_account_runtime,
    stop_account_runtime,
)
from linkedin_mcp.browser import (
    BrowserProfileManager,
    BrowserRuntimeBootstrap,
    login_interactively,
    logout_interactively,
)
from linkedin_mcp.config import Settings
from linkedin_mcp.container import AppContainer, create_production_container
from linkedin_mcp.domain.models import BrowserSetupState
from linkedin_mcp.errors import LinkedInMCPError
from linkedin_mcp.observability import configure_logging
from linkedin_mcp.server import create_mcp_server


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="linkedin-mcp")
    commands = root.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="Run the MCP server")
    serve.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=None,
    )
    commands.add_parser("setup", help="Install the managed Playwright Chromium runtime")
    profile = commands.add_parser("profile", help="Manage the persistent Chromium profile")
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    profile_commands.add_parser("create", help="Create a clean Chromium profile")
    profile_commands.add_parser("status", help="Show non-secret Chromium profile state")
    profile_reset = profile_commands.add_parser(
        "reset",
        help="Archive the Chromium profile and create a clean replacement",
    )
    profile_reset.add_argument(
        "--yes",
        action="store_true",
        help="Confirm resetting the exact configured profile without an interactive prompt",
    )
    commands.add_parser("login", help="Open LinkedIn in the persistent local browser profile")
    commands.add_parser("logout", help="Sign out of LinkedIn in the persistent browser profile")
    commands.add_parser("doctor", help="Check non-secret local runtime readiness")
    commands.add_parser("status", help="Show local LinkedIn MCP runtime ownership")
    stop = commands.add_parser("stop", help="Gracefully stop the owning local MCP runtime")
    stop.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for graceful shutdown (default: 30)",
    )
    return root


def _settings(transport: str | None = None) -> Settings:
    settings = Settings()
    if transport is None:
        return settings
    values = settings.model_dump()
    values["transport"] = transport
    return Settings.model_validate(values)


async def _setup(settings: Settings) -> None:
    bootstrap = BrowserRuntimeBootstrap(settings)
    await bootstrap.ensure_ready(force=True)
    print(
        json.dumps(
            {
                "browser": "ready",
                "cache_path": str(bootstrap.cache_path),
            },
            indent=2,
            sort_keys=True,
        )
    )


async def _login(settings: Settings) -> None:
    await _run_owned_operation(
        settings,
        command="login",
        operation=lambda: login_interactively(settings),
    )


async def _logout(settings: Settings) -> None:
    logged_out = await _run_owned_operation(
        settings,
        command="logout",
        operation=lambda: logout_interactively(settings),
    )
    print(
        json.dumps(
            {
                "logged_out": logged_out,
                "status": "logged_out" if logged_out else "already_logged_out",
            },
            indent=2,
            sort_keys=True,
        )
    )


@contextmanager
def _claim_account_runtime(settings: Settings, *, command: str) -> Generator[None, None, None]:
    lock = AccountProcessLock(
        settings.runtime_lock_path,
        account_id=settings.account_id,
        command=command,
    )
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


async def _run_owned_operation[ResultT](
    settings: Settings,
    *,
    command: str,
    operation: Callable[[], Awaitable[ResultT]],
) -> ResultT:
    with _claim_account_runtime(settings, command=command):
        operation_task = asyncio.ensure_future(operation())
        signal_task = asyncio.create_task(_wait_for_stop_signal())
        try:
            done, _ = await asyncio.wait(
                (operation_task, signal_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if operation_task in done:
                return await operation_task

            received = await signal_task
            if operation_task.done():
                return await operation_task
            operation_task.cancel()
            await asyncio.gather(operation_task, return_exceptions=True)
            raise RuntimeError(f"The {command} operation was interrupted by {received.name}.")
        finally:
            if not operation_task.done():
                operation_task.cancel()
            if not signal_task.done():
                signal_task.cancel()
            await asyncio.gather(operation_task, signal_task, return_exceptions=True)


async def _profile_create(settings: Settings) -> None:
    async def create_profile() -> tuple[bool, bool, str]:
        profile = BrowserProfileManager(settings)
        created = await profile.create()
        return created, profile.inspect().initialized, str(profile.path)

    created, initialized, path = await _run_owned_operation(
        settings,
        command="profile-create",
        operation=create_profile,
    )
    print(
        json.dumps(
            {
                "created": created,
                "initialized": initialized,
                "path": path,
            },
            indent=2,
            sort_keys=True,
        )
    )


def _profile_status(settings: Settings) -> None:
    profile = BrowserProfileManager(settings).inspect()
    runtime = inspect_account_runtime(settings.runtime_lock_path)
    print(
        json.dumps(
            {
                "exists": profile.exists,
                "initialized": profile.initialized,
                "path": str(profile.path),
                "runtime_command": runtime.owner.command if runtime.owner else None,
                "runtime_owner_pid": runtime.owner.pid if runtime.owner else None,
                "runtime_running": runtime.running,
            },
            indent=2,
            sort_keys=True,
        )
    )


def _confirm_profile_reset(settings: Settings) -> None:
    if not sys.stdin.isatty():
        raise ValueError(
            "Profile reset requires an interactive terminal or the explicit `--yes` option."
        )
    expected = "RESET"
    response = input(
        f"Archive and reset Chromium profile {settings.browser_profile_path}? "
        f"Type {expected} to continue: "
    )
    if response != expected:
        raise ValueError("Chromium profile reset was cancelled.")


async def _profile_reset(settings: Settings, *, confirmed: bool) -> None:
    if not confirmed:
        _confirm_profile_reset(settings)
    result = await _run_owned_operation(
        settings,
        command="profile-reset",
        operation=lambda: BrowserProfileManager(settings).reset(),
    )
    print(
        json.dumps(
            {
                "archived_path": (
                    str(result.archived_path) if result.archived_path is not None else None
                ),
                "initialized": True,
                "path": str(result.path),
                "reset": True,
            },
            indent=2,
            sort_keys=True,
        )
    )


async def _doctor(settings: Settings) -> int:
    bootstrap = BrowserRuntimeBootstrap(settings)
    browser_state = bootstrap.inspect_state()
    profile = BrowserProfileManager(settings).inspect()
    runtime = inspect_account_runtime(settings.runtime_lock_path)
    report: dict[str, object] = {
        "automatic_browser_install": settings.browser_auto_install,
        "automatic_login": settings.auto_login_on_start,
        "browser_setup": browser_state.value,
        "configuration": "valid",
        "operation_state": "process_local",
        "profile_initialized": profile.initialized,
        "profile_path": str(profile.path),
        "profile_present": profile.initialized,
        "runtime_command": runtime.owner.command if runtime.owner else None,
        "runtime_owner_pid": runtime.owner.pid if runtime.owner else None,
        "runtime_running": runtime.running,
        "transport": settings.transport,
    }
    ready = browser_state in {
        BrowserSetupState.DISABLED,
        BrowserSetupState.READY,
    }
    return_code = 1 if not ready or not profile.initialized else 0
    print(json.dumps(report, indent=2, sort_keys=True))
    return return_code


def _runtime_report(settings: Settings) -> dict[str, object]:
    status = inspect_account_runtime(settings.runtime_lock_path)
    owner = status.owner
    return {
        "account_id": owner.account_id if owner and owner.account_id else settings.account_id,
        "command": owner.command if owner else None,
        "lock_path": str(settings.runtime_lock_path),
        "pid": owner.pid if owner else None,
        "running": status.running,
        "started_at": owner.started_at if owner else None,
        "transport": owner.transport if owner else None,
    }


def _status(settings: Settings) -> None:
    print(json.dumps(_runtime_report(settings), indent=2, sort_keys=True))


def _stop(settings: Settings, *, timeout_seconds: float) -> None:
    before = inspect_account_runtime(settings.runtime_lock_path)
    result = stop_account_runtime(
        settings.runtime_lock_path,
        timeout_seconds=timeout_seconds,
    )
    owner = result.owner or before.owner
    print(
        json.dumps(
            {
                "account_id": (
                    owner.account_id if owner and owner.account_id else settings.account_id
                ),
                "command": owner.command if owner else None,
                "pid": owner.pid if owner else None,
                "status": "stopped" if before.running else "not_running",
                "stopped": before.running,
            },
            indent=2,
            sort_keys=True,
        )
    )


async def _wait_for_stop_signal() -> signal.Signals:
    with anyio.open_signal_receiver(signal.SIGINT, signal.SIGTERM) as signals:
        async for received in signals:
            return received
    raise RuntimeError("The signal receiver closed unexpectedly.")


async def _serve_stdio(server: FastMCP[None], container: AppContainer) -> None:
    server_task = asyncio.create_task(server.run_stdio_async())
    signal_task = asyncio.create_task(_wait_for_stop_signal())
    done, _ = await asyncio.wait(
        (server_task, signal_task),
        return_when=asyncio.FIRST_COMPLETED,
    )
    if server_task in done:
        signal_task.cancel()
        with suppress(asyncio.CancelledError):
            await signal_task
        await server_task
        return

    await signal_task
    try:
        await container.quiesce()
    finally:
        server_task.cancel()
        with suppress(asyncio.CancelledError):
            await server_task


async def _serve(settings: Settings) -> None:
    container = create_production_container(settings)
    if settings.transport == "stdio":
        server = create_mcp_server(container)
        await _serve_stdio(server, container)
    else:
        server = create_mcp_server(
            container,
            manage_container_lifecycle=False,
        )
        await container.start()
        try:
            await server.run_streamable_http_async()
        finally:
            await container.close()


def main() -> None:
    arguments = parser().parse_args()
    try:
        settings = _settings(cast(str | None, getattr(arguments, "transport", None)))
        configure_logging(settings.log_level)
        if arguments.command == "setup":
            asyncio.run(_setup(settings))
            return
        if arguments.command == "profile":
            profile_command = cast(str, arguments.profile_command)
            if profile_command == "create":
                asyncio.run(_profile_create(settings))
                return
            if profile_command == "status":
                _profile_status(settings)
                return
            if profile_command == "reset":
                asyncio.run(_profile_reset(settings, confirmed=cast(bool, arguments.yes)))
                return
            raise RuntimeError("Unknown profile command")
        if arguments.command == "login":
            asyncio.run(_login(settings))
            return
        if arguments.command == "logout":
            asyncio.run(_logout(settings))
            return
        if arguments.command == "doctor":
            raise SystemExit(asyncio.run(_doctor(settings)))
        if arguments.command == "status":
            _status(settings)
            return
        if arguments.command == "stop":
            _stop(settings, timeout_seconds=cast(float, arguments.timeout))
            return
        if arguments.command == "serve":
            asyncio.run(_serve(settings))
            return
        raise RuntimeError("Unknown command")
    except (LinkedInMCPError, ValidationError, ValueError, RuntimeError) as error:
        print(f"linkedin-mcp: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except Exception as error:
        print("linkedin-mcp: an unexpected startup failure occurred", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
