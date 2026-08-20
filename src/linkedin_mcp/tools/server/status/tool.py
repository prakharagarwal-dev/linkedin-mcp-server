"""FastMCP definition for `linkedin.server.status`."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from linkedin_mcp import __version__
from linkedin_mcp.config import Settings
from linkedin_mcp.infra.queue import Scheduler
from linkedin_mcp.tools.server.status.models import ServerStatusOutput


def register(
    mcp: FastMCP[None],
    settings: Settings,
    scheduler: Scheduler,
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
            transport=settings.transport,
            queue_depth=scheduler.queue_depth,
            active_browser_operation=scheduler.active,
            active_task=scheduler.active_task,
            accepting_calls=scheduler.accepting,
        )

    del _server_status
