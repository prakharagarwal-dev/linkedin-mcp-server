"""Run the private shared LinkedIn MCP transport host."""

from __future__ import annotations

import asyncio
import sys

from pydantic import ValidationError

from linkedin_mcp.config import Settings
from linkedin_mcp.errors import LinkedInMCPError
from linkedin_mcp.logging import configure_logging
from linkedin_mcp.transport.host import (
    brokered_host_output_required,
    redirect_brokered_host_output,
    run_host,
    wait_for_host,
)
from linkedin_mcp.transport.lock import inspect_account_runtime


async def run(settings: Settings) -> None:
    """Run the elected host or wait for the process that won the election."""

    values = settings.model_dump()
    values["transport"] = "streamable-http"
    host_settings = Settings.model_validate(values)
    try:
        await run_host(host_settings)
    except LinkedInMCPError:
        status = inspect_account_runtime(host_settings.runtime_lock_path)
        if not status.running:
            raise
        await wait_for_host(host_settings)


def main() -> None:
    try:
        settings = Settings()
        if brokered_host_output_required():
            redirect_brokered_host_output(settings)
        configure_logging(settings.log_level)
        asyncio.run(run(settings))
    except (LinkedInMCPError, ValidationError, ValueError, RuntimeError) as error:
        print(f"linkedin-mcp host: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except Exception as error:
        print("linkedin-mcp host: an unexpected startup failure occurred", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
