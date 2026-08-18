"""Sign out of the persistent LinkedIn profile."""

import argparse
import asyncio
import json

from linkedin_mcp.config import Settings
from linkedin_mcp.tools._shared.browser import logout_interactively
from linkedin_mcp.transport.owned_operation import run_owned_operation


def configure(command: argparse.ArgumentParser) -> None:
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
