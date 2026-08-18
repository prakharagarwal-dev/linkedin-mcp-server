"""Open the persistent LinkedIn profile for interactive login."""

import argparse
import asyncio

from linkedin_mcp.config import Settings
from linkedin_mcp.tools._shared.browser import login_interactively
from linkedin_mcp.transport.lock import run_owned_operation


def configure(command: argparse.ArgumentParser) -> None:
    command.set_defaults(handler=handle)


async def execute(settings: Settings) -> None:
    await run_owned_operation(
        settings,
        command="login",
        operation=lambda: login_interactively(settings),
    )


def handle(_: argparse.Namespace, settings: Settings) -> None:
    asyncio.run(execute(settings))
