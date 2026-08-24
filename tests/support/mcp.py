"""Offline FastMCP composition without starting Playwright or an HTTP listener."""

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP

from linkedin_mcp import __version__
from linkedin_mcp.browser import BrowserManager
from linkedin_mcp.config import Settings
from linkedin_mcp.cursors import CursorManager
from linkedin_mcp.operations import OperationManager
from linkedin_mcp.tools import ToolManager
from linkedin_mcp.ui.manager import UIManager


@dataclass(frozen=True, slots=True)
class MCPFixture:
    mcp: FastMCP[None]
    tools: ToolManager
    operations: OperationManager
    cursors: CursorManager


def create_mcp_fixture(settings: Settings, browser: BrowserManager) -> MCPFixture:
    operations = OperationManager()
    cursors = CursorManager(
        ttl_seconds=settings.pagination_cursor_ttl_seconds,
        max_active_cursors=settings.pagination_max_active_cursors,
        max_seen_items_per_cursor=settings.pagination_max_seen_items_per_cursor,
    )
    mcp: FastMCP[None] = FastMCP(
        "linkedin-mcp-server",
        instructions=(
            "Each account-changing tool performs one complete LinkedIn action. Every invocation "
            "is new, so do not retry an uncertain action blindly. Use only registered typed "
            "LinkedIn capabilities. Every read invocation executes freshly."
        ),
    )
    mcp._mcp_server.version = __version__  # pyright: ignore[reportPrivateUsage]
    tools = ToolManager(
        mcp,
        settings=settings,
        browser=browser,
        ui=UIManager(browser, 0),
        operations=operations,
        cursors=cursors,
    )
    return MCPFixture(mcp=mcp, tools=tools, operations=operations, cursors=cursors)
