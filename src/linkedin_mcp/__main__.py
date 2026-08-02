"""Command-line entrypoint for serving, browser setup, login, and diagnostics."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import cast

from pydantic import ValidationError

from linkedin_mcp.browser import (
    BrowserRuntimeBootstrap,
    login_interactively,
)
from linkedin_mcp.config import Settings
from linkedin_mcp.container import create_production_container
from linkedin_mcp.domain.models import BrowserSetupState
from linkedin_mcp.errors import LinkedInMCPError
from linkedin_mcp.observability import configure_logging
from linkedin_mcp.server import create_mcp_server


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="linkedin-mcp")
    commands = root.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="Run the MCP server")
    serve.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=None,
    )
    commands.add_parser("setup", help="Install the managed Playwright Chromium runtime")
    commands.add_parser("login", help="Open LinkedIn in the persistent local browser profile")
    commands.add_parser("doctor", help="Check non-secret local runtime readiness")
    return root


def _settings(transport: str | None = None) -> Settings:
    settings = Settings()
    if transport is None:
        return settings
    values = settings.model_dump()
    values["transport"] = transport
    return Settings.model_validate(values)


def _profile_present(settings: Settings) -> bool:
    path = settings.browser_profile_path
    return path.is_dir() and any(path.iterdir())


async def _setup(settings: Settings) -> None:
    bootstrap = BrowserRuntimeBootstrap(settings)
    await bootstrap.ensure_ready(force=True)
    print(
        json.dumps(
            {
                "browser": "ready",
                "cache_path": str(bootstrap.cache_path),
            },
            indent=2,
            sort_keys=True,
        )
    )


async def _doctor(settings: Settings) -> int:
    bootstrap = BrowserRuntimeBootstrap(settings)
    browser_state = bootstrap.inspect_state()
    profile_present = _profile_present(settings)
    report: dict[str, object] = {
        "automatic_browser_install": settings.browser_auto_install,
        "automatic_login": settings.auto_login_on_start,
        "browser_setup": browser_state.value,
        "configuration": "valid",
        "operation_state": "process_local",
        "profile_present": profile_present,
        "transport": settings.transport,
    }
    ready = browser_state in {
        BrowserSetupState.DISABLED,
        BrowserSetupState.READY,
    }
    return_code = 1 if not ready or not profile_present else 0
    print(json.dumps(report, indent=2, sort_keys=True))
    return return_code


def main() -> None:
    arguments = parser().parse_args()
    try:
        settings = _settings(cast(str | None, getattr(arguments, "transport", None)))
        configure_logging(settings.log_level)
        if arguments.command == "setup":
            asyncio.run(_setup(settings))
            return
        if arguments.command == "login":
            asyncio.run(login_interactively(settings))
            return
        if arguments.command == "doctor":
            raise SystemExit(asyncio.run(_doctor(settings)))
        if arguments.command == "serve":
            container = create_production_container(settings)
            create_mcp_server(container).run(transport=settings.transport)
            return
        raise RuntimeError("Unknown command")
    except (LinkedInMCPError, ValidationError, ValueError, RuntimeError) as error:
        print(f"linkedin-mcp: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except Exception as error:
        print("linkedin-mcp: an unexpected startup failure occurred", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
