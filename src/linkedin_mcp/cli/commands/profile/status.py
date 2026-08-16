"""Report non-secret persistent Chromium profile state."""

import argparse
import json

from linkedin_mcp.browser import BrowserProfileManager
from linkedin_mcp.config import Settings
from linkedin_mcp.runtime import inspect_account_runtime


def configure(command: argparse.ArgumentParser) -> None:
    command.set_defaults(handler=handle)


def execute(settings: Settings) -> None:
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


def handle(_: argparse.Namespace, settings: Settings) -> None:
    execute(settings)
