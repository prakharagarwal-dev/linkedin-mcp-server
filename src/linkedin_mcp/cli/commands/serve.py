"""Start the Streamable HTTP MCP server."""

import argparse

from linkedin_mcp.config import Settings
from linkedin_mcp.main import main


def configure(command: argparse.ArgumentParser) -> None:
    command.set_defaults(handler=handle)


def handle(_: argparse.Namespace, settings: Settings) -> None:
    main(settings)
