"""Compose and run the Streamable HTTP LinkedIn MCP server."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP

from linkedin_mcp import __version__
from linkedin_mcp.browser import BrowserManager
from linkedin_mcp.config import Settings
from linkedin_mcp.cursors import CursorManager
from linkedin_mcp.logging import configure_logging
from linkedin_mcp.operations import OperationManager
from linkedin_mcp.tools import ToolManager
from linkedin_mcp.ui.manager import UIManager


def main(settings: Settings | None = None) -> None:
    """Create app-scoped components and let FastMCP run its HTTP server."""

    settings = settings or Settings()
    configure_logging(settings.log_level)
    browser = BrowserManager(settings)
    ui = UIManager(browser, settings.browser_action_delay_seconds)
    operations = OperationManager()
    cursors = CursorManager(
        ttl_seconds=settings.pagination_cursor_ttl_seconds,
        max_active_cursors=settings.pagination_max_active_cursors,
        max_seen_items_per_cursor=settings.pagination_max_seen_items_per_cursor,
    )

    @asynccontextmanager
    async def lifespan(_: FastMCP[None]) -> AsyncGenerator[None]:
        await browser.start()
        try:
            yield None
        finally:
            await browser.close()

    mcp: FastMCP[None] = FastMCP(
        "linkedin-mcp-server",
        instructions=(
            "Each account-changing tool performs one complete LinkedIn action. Every invocation "
            "is new, so do not retry an uncertain action blindly. Use only registered typed "
            "LinkedIn capabilities. Every read invocation executes freshly."
        ),
        json_response=True,
        stateless_http=False,
        host=settings.http_host,
        port=settings.http_port,
        log_level=settings.log_level,
        lifespan=lifespan,
    )
    mcp._mcp_server.version = __version__  # pyright: ignore[reportPrivateUsage]
    ToolManager(
        mcp,
        settings=settings,
        browser=browser,
        ui=ui,
        operations=operations,
        cursors=cursors,
    ).register_all()
    mcp.run(transport="streamable-http")
