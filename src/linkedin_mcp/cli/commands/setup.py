"""Install the managed Playwright browser runtime."""

import argparse
import asyncio
import json

from linkedin_mcp.browser import BrowserBootstrap
from linkedin_mcp.config import Settings


def configure(command: argparse.ArgumentParser) -> None:
    command.set_defaults(handler=handle)


async def execute(settings: Settings) -> None:
    bootstrap = BrowserBootstrap(settings)
    await bootstrap.ensure_ready(force=True)
    print(
        json.dumps(
            {
                "browser": "ready",
                "cache_path": str(bootstrap.cache_path),
            },
            indent=2,
            sort_keys=True,
        )
    )


def handle(_: argparse.Namespace, settings: Settings) -> None:
    asyncio.run(execute(settings))
