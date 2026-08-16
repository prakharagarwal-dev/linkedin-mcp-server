"""Archive and reset the persistent Chromium profile."""

import argparse
import asyncio
import json
import sys

from linkedin_mcp.browser import BrowserProfileManager
from linkedin_mcp.cli.common import run_owned_operation
from linkedin_mcp.cli.types import Subparsers
from linkedin_mcp.config import Settings


def register(commands: Subparsers) -> None:
    command = commands.add_parser(
        "reset",
        help="Archive the Chromium profile and create a clean replacement",
    )
    command.add_argument(
        "--yes",
        action="store_true",
        help="Confirm resetting the exact configured profile without an interactive prompt",
    )
    command.set_defaults(handler=handle)


def confirm(settings: Settings) -> None:
    if not sys.stdin.isatty():
        raise ValueError(
            "Profile reset requires an interactive terminal or the explicit `--yes` option."
        )
    expected = "RESET"
    response = input(
        f"Archive and reset Chromium profile {settings.browser_profile_path}? "
        f"Type {expected} to continue: "
    )
    if response != expected:
        raise ValueError("Chromium profile reset was cancelled.")


async def execute(settings: Settings, *, confirmed: bool) -> None:
    if not confirmed:
        confirm(settings)
    result = await run_owned_operation(
        settings,
        command="profile-reset",
        operation=lambda: BrowserProfileManager(settings).reset(),
    )
    print(
        json.dumps(
            {
                "archived_path": (
                    str(result.archived_path) if result.archived_path is not None else None
                ),
                "initialized": True,
                "path": str(result.path),
                "reset": True,
            },
            indent=2,
            sort_keys=True,
        )
    )


def handle(arguments: argparse.Namespace, settings: Settings) -> None:
    asyncio.run(execute(settings, confirmed=bool(arguments.yes)))
