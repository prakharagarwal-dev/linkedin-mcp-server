"""FastMCP definition for `linkedin.server.status`."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from linkedin_mcp import __version__
from linkedin_mcp.container import AppContainer
from linkedin_mcp.tools.server.status.models.server_status_output import ServerStatusOutput


def register(
    mcp: FastMCP[None],
    container: AppContainer,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.server.status",
        title="LinkedIn MCP Server Status",
        description="Return non-secret server configuration and readiness metadata.",
        annotations=annotations,
    )
    async def _server_status() -> ServerStatusOutput:
        return ServerStatusOutput(
            version=__version__,
            transport=container.settings.transport,
            queue_depth=container.scheduler.queue_depth,
            active_browser_operation=container.scheduler.active,
            active_task=container.scheduler.active_task,
            accepting_calls=container.scheduler.accepting,
        )

    del _server_status
