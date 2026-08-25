"""FastMCP definition for `linkedin.connections.list`."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.cursors import CursorManager
from linkedin_mcp.errors import InternalServerError, LinkedInMCPError
from linkedin_mcp.operations import OperationManager
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
    operations: OperationManager,
    page: ConnectionsListPage,
    cursors: CursorManager,
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
        sort_by: ConnectionsSortBy = ConnectionsSortBy.RECENTLY_ADDED,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
    ) -> ConnectionsListOutput:
        request = ConnectionsListInput(
            context_id=context_id,
            request_id=request_id,
            sort_by=sort_by,
            page_size=page_size,
            cursor=cursor,
        )
        result = await tool_result(
            operations.run(
                "linkedin.connections.list",
                lambda: execute(
                    request,
                    page=page,
                    cursors=cursors,
                    account_id=account_id,
                ),
            )
        )
        return result

    del _list_connections
