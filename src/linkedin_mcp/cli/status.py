"""Report shared runtime ownership and health."""

import argparse
import asyncio
import json

from linkedin_mcp.cli.types import Subparsers
from linkedin_mcp.config import Settings
from linkedin_mcp.runtime import inspect_account_runtime
from linkedin_mcp.runtime.shared import read_shared_runtime_status


def register(commands: Subparsers) -> None:
    command = commands.add_parser("status", help="Show local LinkedIn MCP runtime ownership")
    command.set_defaults(handler=handle)


def runtime_report(settings: Settings) -> dict[str, object]:
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
        "endpoint": owner.endpoint if owner else None,
        "version": owner.version if owner else None,
    }


async def execute(settings: Settings) -> None:
    report = runtime_report(settings)
    endpoint = report["endpoint"]
    runtime_status = (
        await read_shared_runtime_status(endpoint) if isinstance(endpoint, str) else None
    )
    report["healthy"] = runtime_status is not None
    if runtime_status is not None:
        report["connected_clients"] = runtime_status.get("connected_clients")
        report["queue_depth"] = runtime_status.get("queue_depth")
        report["queued_clients"] = runtime_status.get("queued_clients")
        report["active_browser_operation"] = runtime_status.get("active_browser_operation")
        report["active_capability"] = runtime_status.get("active_capability")
        report["accepting_calls"] = runtime_status.get("accepting_calls")
    print(json.dumps(report, indent=2, sort_keys=True))


def handle(_: argparse.Namespace, settings: Settings) -> None:
    asyncio.run(execute(settings))
