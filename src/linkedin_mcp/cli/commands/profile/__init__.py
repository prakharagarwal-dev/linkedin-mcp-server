"""Nested Chromium profile commands."""

import argparse

from linkedin_mcp.cli.commands.profile import create, reset, status


def configure(profile: argparse.ArgumentParser) -> None:
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    create.configure(
        profile_commands.add_parser(
            "create",
            help="Create a clean Chromium profile",
        )
    )
    status.configure(
        profile_commands.add_parser(
            "status",
            help="Show non-secret Chromium profile state",
        )
    )
    reset.configure(
        profile_commands.add_parser(
            "reset",
            help="Archive the Chromium profile and create a clean replacement",
        )
    )
