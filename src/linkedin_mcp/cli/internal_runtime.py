"""Hidden shared-runtime command launched by the stdio bridge."""

import argparse
import asyncio

from linkedin_mcp.cli.types import Subparsers
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import LinkedInMCPError
from linkedin_mcp.runtime import inspect_account_runtime
from linkedin_mcp.runtime.shared import run_shared_runtime, wait_for_shared_runtime


def register(commands: Subparsers) -> None:
    command = commands.add_parser("_runtime", help=argparse.SUPPRESS)
    command.set_defaults(handler=handle)


async def execute(settings: Settings) -> None:
    runtime_values = settings.model_dump()
    runtime_values["transport"] = "streamable-http"
    runtime_settings = Settings.model_validate(runtime_values)
    try:
        await run_shared_runtime(runtime_settings)
    except LinkedInMCPError:
        status = inspect_account_runtime(runtime_settings.runtime_lock_path)
        if not status.running:
            raise
        await wait_for_shared_runtime(runtime_settings)


def handle(_: argparse.Namespace, settings: Settings) -> None:
    asyncio.run(execute(settings))
