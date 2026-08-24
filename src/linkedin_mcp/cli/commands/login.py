"""Open the persistent LinkedIn profile for interactive login."""

import argparse
import asyncio

from linkedin_mcp.browser import BrowserManager
from linkedin_mcp.config import Settings


def configure(command: argparse.ArgumentParser) -> None:
    command.set_defaults(handler=handle)


async def execute(settings: Settings) -> None:
    browser = BrowserManager(settings)
    try:
        await browser.login()
    finally:
        await browser.close()


def handle(_: argparse.Namespace, settings: Settings) -> None:
    asyncio.run(execute(settings))
