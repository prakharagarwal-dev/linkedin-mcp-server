"""FastMCP definition for `linkedin.connections.list`."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.errors import InternalServerError, LinkedInMCPError
from linkedin_mcp.infra.cursor import CursorStore
from linkedin_mcp.infra.queue import Scheduler, Task
from linkedin_mcp.tools.connections.list.models import (
    ConnectionsListInput,
    ConnectionsListOutput,
    ConnectionsSortBy,
)
from linkedin_mcp.tools.connections.list.page import ConnectionsListPage
from linkedin_mcp.tools.connections.list.pagination import execute

IdentifierArgument = Annotated[
    str,
    Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]


PageSizeArgument = Annotated[
    int,
    Field(
        ge=1,
        le=100,
        description="Number of unique items to return in this page.",
    ),
]


CursorArgument = Annotated[
    str,
    Field(
        min_length=32,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
        description=(
            "Opaque continuation cursor returned as pagination.next_cursor by the preceding page."
        ),
    ),
]


async def tool_result[ResultT](awaitable: Awaitable[ResultT]) -> ResultT:
    try:
        return await awaitable
    except Exception as error:
        safe = error if isinstance(error, LinkedInMCPError) else InternalServerError()
        raise ToolError(f"{safe.code.value}: {safe.safe_message}") from error


def register(
    mcp: FastMCP[None],
    scheduler: Scheduler,
    page: ConnectionsListPage,
    cursor_store: CursorStore,
    account_id: str,
) -> None:
    @mcp.tool(
        name="linkedin.connections.list",
        title="List LinkedIn Connections",
        description=(
            "List one cursor page of the configured account's visible first-degree connection "
            "inventory in LinkedIn's selected visible sort order. This tool does not search."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
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
                page=page,
                cursor_store=cursor_store,
                account_id=account_id,
            ),
        )
        await scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "LinkedIn connections read complete")
        return result

    del _list_connections
