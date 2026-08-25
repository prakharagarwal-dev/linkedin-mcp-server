"""Report non-secret persistent Chromium profile state."""

import argparse
import json

from linkedin_mcp.browser import BrowserProfileManager
from linkedin_mcp.config import Settings


def configure(command: argparse.ArgumentParser) -> None:
    command.set_defaults(handler=handle)


def execute(settings: Settings) -> None:
    profile = BrowserProfileManager(settings).inspect()
    print(
        json.dumps(
            {
                "exists": profile.exists,
                "initialized": profile.initialized,
                "path": str(profile.path),
            },
            indent=2,
            sort_keys=True,
        )
    )


def handle(_: argparse.Namespace, settings: Settings) -> None:
    execute(settings)
