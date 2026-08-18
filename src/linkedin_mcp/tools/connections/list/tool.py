"""FastMCP definition for `linkedin.connections.list`."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from linkedin_mcp.container import AppContainer
from linkedin_mcp.queue import Task
from linkedin_mcp.tools._shared.tool import (
    CursorArgument,
    IdentifierArgument,
    PageSizeArgument,
    tool_result,
)
from linkedin_mcp.tools.connections.list.models.connections_list_input import ConnectionsListInput
from linkedin_mcp.tools.connections.list.models.connections_list_output import ConnectionsListOutput
from linkedin_mcp.tools.connections.list.models.connections_sort_by import ConnectionsSortBy
from linkedin_mcp.tools.connections.list.pagination import execute


def register(
    mcp: FastMCP[None],
    container: AppContainer,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.connections.list",
        title="List LinkedIn Connections",
        description=(
            "List one cursor page of the configured account's visible first-degree connection "
            "inventory in LinkedIn's selected visible sort order. This tool does not search."
        ),
        annotations=annotations,
    )
    async def _list_connections(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        sort_by: ConnectionsSortBy = ConnectionsSortBy.RECENTLY_ADDED,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
    ) -> ConnectionsListOutput:
        await ctx.report_progress(0, 100, "Queued LinkedIn connections read")
        request = ConnectionsListInput(
            context_id=context_id,
            request_id=request_id,
            sort_by=sort_by,
            page_size=page_size,
            cursor=cursor,
        )
        task = Task(
            name="linkedin.connections.list",
            execute=lambda: execute(
                request,
                page=container.connections_list,
                pagination=container.pagination,
                account_id=container.settings.account_id,
            ),
        )
        await container.scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "LinkedIn connections read complete")
        return result

    del _list_connections
