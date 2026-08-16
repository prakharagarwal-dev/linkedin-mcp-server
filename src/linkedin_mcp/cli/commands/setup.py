"""Install the managed Playwright browser runtime."""

import argparse
import asyncio
import json

from linkedin_mcp.browser import BrowserRuntimeBootstrap
from linkedin_mcp.config import Settings


def configure(command: argparse.ArgumentParser) -> None:
    command.set_defaults(handler=handle)


async def execute(settings: Settings) -> None:
    bootstrap = BrowserRuntimeBootstrap(settings)
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
