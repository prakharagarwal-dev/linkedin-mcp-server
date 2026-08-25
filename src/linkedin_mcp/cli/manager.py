"""Build and dispatch the public LinkedIn MCP command hierarchy."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from typing import cast

from pydantic import ValidationError

from linkedin_mcp.cli.commands import register as register_commands
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import LinkedInMCPError
from linkedin_mcp.logging import configure_logging

type CommandHandler = Callable[[argparse.Namespace, Settings], int | None]


class CLIManager:
    """Parse one CLI invocation and dispatch it to a focused command module."""

    @staticmethod
    def parser() -> argparse.ArgumentParser:
        root = argparse.ArgumentParser(prog="linkedin-mcp")
        register_commands(root)
        return root

    def run(self, argv: Sequence[str] | None = None) -> int:
        try:
            arguments = self.parser().parse_args(argv)
            settings = Settings()
            configure_logging(settings.log_level)
            handler = cast(CommandHandler, arguments.handler)
            return handler(arguments, settings) or 0
        except (LinkedInMCPError, ValidationError, ValueError, RuntimeError) as error:
            print(f"linkedin-mcp: {error}", file=sys.stderr)
            return 1
        except Exception:
            print("linkedin-mcp: an unexpected startup failure occurred", file=sys.stderr)
            return 1


def run_cli() -> None:
    raise SystemExit(CLIManager().run())
