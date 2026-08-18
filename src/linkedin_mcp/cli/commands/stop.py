"""Gracefully stop the owning local runtime."""

import argparse
import json

from linkedin_mcp.config import Settings
from linkedin_mcp.host import inspect_account_runtime, stop_account_runtime


def configure(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Seconds to wait for graceful shutdown (default: 30)",
    )
    command.set_defaults(handler=handle)


def execute(settings: Settings, *, timeout_seconds: float) -> None:
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


def handle(arguments: argparse.Namespace, settings: Settings) -> None:
    execute(settings, timeout_seconds=float(arguments.timeout))
