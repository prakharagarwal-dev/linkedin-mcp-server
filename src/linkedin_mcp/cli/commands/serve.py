"""Start or attach to the configured MCP transport."""

import argparse
import asyncio
import sys

from linkedin_mcp.config import Settings
from linkedin_mcp.errors import LinkedInMCPError
from linkedin_mcp.transport import inspect_account_runtime
from linkedin_mcp.transport.host import (
    ensure_host,
    run_host,
    wait_for_host,
)
from linkedin_mcp.transport.stdio import run_stdio_proxy


def configure(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=None,
    )
    command.set_defaults(handler=handle)


async def execute(settings: Settings) -> None:
    if settings.transport == "stdio":
        endpoint = await ensure_host(settings)
        await run_stdio_proxy(endpoint)
        return

    status = inspect_account_runtime(settings.runtime_lock_path)
    if status.running:
        endpoint = await wait_for_host(settings)
        print(f"LinkedIn MCP shared runtime already available at {endpoint}", file=sys.stderr)
        return

    try:
        await run_host(settings)
    except LinkedInMCPError:
        status = inspect_account_runtime(settings.runtime_lock_path)
        if not status.running:
            raise
        endpoint = await wait_for_host(settings)
        print(f"LinkedIn MCP shared runtime already available at {endpoint}", file=sys.stderr)


def handle(_: argparse.Namespace, settings: Settings) -> None:
    asyncio.run(execute(settings))
