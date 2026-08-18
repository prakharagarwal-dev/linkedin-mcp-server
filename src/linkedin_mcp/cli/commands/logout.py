"""Sign out of the persistent LinkedIn profile."""

import argparse
import asyncio
import json

from linkedin_mcp.config import Settings
from linkedin_mcp.host.manager import HostManager


def configure(command: argparse.ArgumentParser) -> None:
    command.set_defaults(handler=handle)


async def execute(settings: Settings) -> None:
    logged_out = await HostManager(settings).logout()
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
