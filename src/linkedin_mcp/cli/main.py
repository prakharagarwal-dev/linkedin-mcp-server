"""Assemble and dispatch the public LinkedIn MCP command hierarchy."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from typing import cast

from pydantic import ValidationError

from linkedin_mcp.cli.commands import register as register_commands
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import LinkedInMCPError
from linkedin_mcp.logging import configure_logging

type CommandHandler = Callable[[argparse.Namespace, Settings], int | None]


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="linkedin-mcp")
    register_commands(root)
    return root


def _settings_for_transport(transport: str | None = None) -> Settings:
    settings = Settings()
    if transport is None:
        return settings
    values = settings.model_dump()
    values["transport"] = transport
    return Settings.model_validate(values)


def main() -> None:
    arguments = parser().parse_args()
    try:
        transport = cast(str | None, getattr(arguments, "transport", None))
        settings = _settings_for_transport(transport)
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
