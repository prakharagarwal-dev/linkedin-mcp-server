"""Open the persistent LinkedIn profile for interactive login."""

import argparse
import asyncio

from linkedin_mcp.cli.common import run_owned_operation
from linkedin_mcp.cli.types import Subparsers
from linkedin_mcp.config import Settings
from linkedin_mcp.linkedin.browser import login_interactively


def register(commands: Subparsers) -> None:
    command = commands.add_parser(
        "login",
        help="Open LinkedIn in the persistent local browser profile",
    )
    command.set_defaults(handler=handle)


async def execute(settings: Settings) -> None:
    await run_owned_operation(
        settings,
        command="login",
        operation=lambda: login_interactively(settings),
    )


def handle(_: argparse.Namespace, settings: Settings) -> None:
    asyncio.run(execute(settings))
