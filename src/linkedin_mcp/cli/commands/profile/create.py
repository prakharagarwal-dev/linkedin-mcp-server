"""Create a clean persistent Chromium profile."""

import argparse
import asyncio
import json

from linkedin_mcp.browser import BrowserProfileManager
from linkedin_mcp.config import Settings
from linkedin_mcp.host.lock import run_owned_operation


def configure(command: argparse.ArgumentParser) -> None:
    command.set_defaults(handler=handle)


async def execute(settings: Settings) -> None:
    async def create_profile() -> tuple[bool, bool, str]:
        profile = BrowserProfileManager(settings)
        created = await profile.create()
        return created, profile.inspect().initialized, str(profile.path)

    created, initialized, path = await run_owned_operation(
        settings,
        command="profile-create",
        operation=create_profile,
    )
    print(
        json.dumps(
            {
                "created": created,
                "initialized": initialized,
                "path": path,
            },
            indent=2,
            sort_keys=True,
        )
    )


def handle(_: argparse.Namespace, settings: Settings) -> None:
    asyncio.run(execute(settings))
