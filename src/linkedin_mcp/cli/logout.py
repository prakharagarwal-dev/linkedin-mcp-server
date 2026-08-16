"""Sign out of the persistent LinkedIn profile."""

import argparse
import asyncio
import json

from linkedin_mcp.cli.common import run_owned_operation
from linkedin_mcp.cli.types import Subparsers
from linkedin_mcp.config import Settings
from linkedin_mcp.linkedin.browser import logout_interactively


def register(commands: Subparsers) -> None:
    command = commands.add_parser(
        "logout",
        help="Sign out of LinkedIn in the persistent browser profile",
    )
    command.set_defaults(handler=handle)


async def execute(settings: Settings) -> None:
    logged_out = await run_owned_operation(
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


def handle(_: argparse.Namespace, settings: Settings) -> None:
    asyncio.run(execute(settings))
