"""FastMCP definition for `linkedin.server.status`."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from linkedin_mcp import __version__
from linkedin_mcp.operations import OperationManager
from linkedin_mcp.tools.server.status.models import ServerStatusOutput


def register(
    mcp: FastMCP[None],
    operations: OperationManager,
) -> None:
    @mcp.tool(
        name="linkedin.server.status",
        title="LinkedIn MCP Server Status",
        description="Return non-secret server configuration and readiness metadata.",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def _server_status() -> ServerStatusOutput:
        return ServerStatusOutput(
            version=__version__,
            waiting_operations=operations.waiting_operations,
            active_browser_operation=operations.active,
            active_operation=operations.active_operation,
        )

    del _server_status
