"""Nested Chromium profile commands."""

from linkedin_mcp.cli.profile import create, reset, status
from linkedin_mcp.cli.types import Subparsers


def register(commands: Subparsers) -> None:
    profile = commands.add_parser("profile", help="Manage the persistent Chromium profile")
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    create.register(profile_commands)
    status.register(profile_commands)
    reset.register(profile_commands)
