"""Assemble and dispatch the LinkedIn MCP command hierarchy."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import cast

from pydantic import ValidationError

from linkedin_mcp.cli import doctor, internal_runtime, login, logout, serve, setup, status, stop
from linkedin_mcp.cli.common import settings_for_transport
from linkedin_mcp.cli.profile import register as register_profile
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import LinkedInMCPError
from linkedin_mcp.observability import configure_logging
from linkedin_mcp.runtime.shared import (
    brokered_runtime_output_required,
    redirect_brokered_runtime_output,
)

type CommandHandler = Callable[[argparse.Namespace, Settings], int | None]


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="linkedin-mcp")
    commands = root.add_subparsers(dest="command", required=True)

    serve.register(commands)
    setup.register(commands)
    register_profile(commands)
    login.register(commands)
    logout.register(commands)
    doctor.register(commands)
    status.register(commands)
    stop.register(commands)
    internal_runtime.register(commands)
    return root


def main() -> None:
    arguments = parser().parse_args()
    try:
        transport = cast(str | None, getattr(arguments, "transport", None))
        settings = settings_for_transport(transport)
        if arguments.command == "_runtime" and brokered_runtime_output_required():
            redirect_brokered_runtime_output(settings)
        configure_logging(settings.log_level)

        handler = cast(CommandHandler, arguments.handler)
        exit_code = handler(arguments, settings)
        if exit_code is not None:
            raise SystemExit(exit_code)
    except (LinkedInMCPError, ValidationError, ValueError, RuntimeError) as error:
        print(f"linkedin-mcp: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except Exception as error:
        print("linkedin-mcp: an unexpected startup failure occurred", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
