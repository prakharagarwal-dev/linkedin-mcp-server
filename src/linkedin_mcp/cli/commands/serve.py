"""Start or attach to the configured MCP transport."""

import argparse
import asyncio
import sys

from linkedin_mcp.config import Settings
from linkedin_mcp.host.manager import HostManager


def configure(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=None,
    )
    command.set_defaults(handler=handle)


async def execute(settings: Settings) -> None:
    endpoint = await HostManager(settings).serve()
    if endpoint is not None:
        print(f"LinkedIn MCP shared runtime already available at {endpoint}", file=sys.stderr)


def handle(_: argparse.Namespace, settings: Settings) -> None:
    asyncio.run(execute(settings))
