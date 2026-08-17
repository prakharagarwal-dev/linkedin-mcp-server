"""FastMCP definition for `linkedin.server.status`."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from linkedin_mcp import __version__
from linkedin_mcp.app.container import AppContainer
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
            connected_clients=container.clients.connected_count,
            queue_depth=container.worker.queue_depth,
            queued_clients=container.worker.queued_clients,
            active_browser_operation=container.worker.active,
            active_capability=container.worker.active_capability,
            accepting_calls=container.worker.accepting,
        )

    del _server_status
