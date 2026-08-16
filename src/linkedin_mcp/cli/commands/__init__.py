"""Register the public LinkedIn MCP commands."""

import argparse

from linkedin_mcp.cli.commands import doctor, login, logout, profile, serve, setup, status, stop


def register(root: argparse.ArgumentParser) -> None:
    commands = root.add_subparsers(dest="command", required=True)

    serve.configure(commands.add_parser("serve", help="Run the MCP server"))
    setup.configure(
        commands.add_parser(
            "setup",
            help="Install the managed Playwright Chromium runtime",
        )
    )
    profile.configure(
        commands.add_parser(
            "profile",
            help="Manage the persistent Chromium profile",
        )
    )
    login.configure(
        commands.add_parser(
            "login",
            help="Open LinkedIn in the persistent local browser profile",
        )
    )
    logout.configure(
        commands.add_parser(
            "logout",
            help="Sign out of LinkedIn in the persistent browser profile",
        )
    )
    doctor.configure(
        commands.add_parser(
            "doctor",
            help="Check non-secret local runtime readiness",
        )
    )
    status.configure(
        commands.add_parser(
            "status",
            help="Show local LinkedIn MCP runtime ownership",
        )
    )
    stop.configure(
        commands.add_parser(
            "stop",
            help="Gracefully stop the owning local MCP runtime",
        )
    )
