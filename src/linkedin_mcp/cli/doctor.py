"""Report non-secret local runtime readiness."""

import argparse
import asyncio
import json

from linkedin_mcp.browser import (
    BrowserProfileManager,
    BrowserRuntimeBootstrap,
    BrowserSetupState,
)
from linkedin_mcp.cli.types import Subparsers
from linkedin_mcp.config import Settings
from linkedin_mcp.runtime import inspect_account_runtime


def register(commands: Subparsers) -> None:
    command = commands.add_parser("doctor", help="Check non-secret local runtime readiness")
    command.set_defaults(handler=handle)


async def execute(settings: Settings) -> int:
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


def handle(_: argparse.Namespace, settings: Settings) -> int:
    return asyncio.run(execute(settings))
