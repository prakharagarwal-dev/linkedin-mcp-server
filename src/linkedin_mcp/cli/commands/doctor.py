"""Report non-secret local runtime readiness."""

import argparse
import asyncio
import json

from linkedin_mcp.browser import (
    BrowserBootstrap,
    BrowserProfileManager,
    BrowserSetupState,
)
from linkedin_mcp.config import Settings


def configure(command: argparse.ArgumentParser) -> None:
    command.set_defaults(handler=handle)


async def execute(settings: Settings) -> int:
    bootstrap = BrowserBootstrap(settings)
    browser_state = bootstrap.inspect_state()
    profile = BrowserProfileManager(settings).inspect()
    report: dict[str, object] = {
        "automatic_browser_install": settings.browser_auto_install,
        "browser_setup": browser_state.value,
        "configuration": "valid",
        "operation_state": "process_local",
        "profile_initialized": profile.initialized,
        "profile_path": str(profile.path),
        "profile_present": profile.initialized,
        "transport": "streamable-http",
    }
    ready = browser_state in {
        BrowserSetupState.DISABLED,
        BrowserSetupState.READY,
    }
    return_code = 1 if not ready or not profile.initialized else 0
    print(json.dumps(report, indent=2, sort_keys=True))
    return return_code


def handle(_: argparse.Namespace, settings: Settings) -> int:
    return asyncio.run(execute(settings))
