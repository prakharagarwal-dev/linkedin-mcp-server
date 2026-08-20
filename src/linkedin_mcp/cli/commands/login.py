"""Open the persistent LinkedIn profile for interactive login."""

import argparse
import asyncio

from linkedin_mcp.config import Settings
from linkedin_mcp.host.manager import HostManager


def configure(command: argparse.ArgumentParser) -> None:
    command.set_defaults(handler=handle)


async def execute(settings: Settings) -> None:
    await HostManager(settings).login()


def handle(_: argparse.Namespace, settings: Settings) -> None:
    asyncio.run(execute(settings))
