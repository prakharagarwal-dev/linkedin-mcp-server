"""Start the private shared LinkedIn MCP runtime process."""

from __future__ import annotations

import asyncio
import sys

from pydantic import ValidationError

from linkedin_mcp.config import Settings
from linkedin_mcp.errors import LinkedInMCPError
from linkedin_mcp.logging import configure_logging
from linkedin_mcp.runtime.ownership import inspect_account_runtime
from linkedin_mcp.runtime.shared import (
    brokered_runtime_output_required,
    redirect_brokered_runtime_output,
    run_shared_runtime,
    wait_for_shared_runtime,
)


async def run(settings: Settings) -> None:
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


def main() -> None:
    try:
        settings = Settings()
        if brokered_runtime_output_required():
            redirect_brokered_runtime_output(settings)
        configure_logging(settings.log_level)
        asyncio.run(run(settings))
    except (LinkedInMCPError, ValidationError, ValueError, RuntimeError) as error:
        print(f"linkedin-mcp runtime: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except Exception as error:
        print("linkedin-mcp runtime: an unexpected startup failure occurred", file=sys.stderr)
        raise SystemExit(1) from error
