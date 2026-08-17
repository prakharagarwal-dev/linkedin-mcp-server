"""FastMCP definition for `linkedin.connections.search`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.app.container import AppContainer
from linkedin_mcp.tools._shared.tool import (
    CursorArgument,
    IdentifierArgument,
    PageSizeArgument,
    tool_result,
)
from linkedin_mcp.tools.connections.search.models.connections_search_filters import (
    ConnectionsSearchFilters,
)
from linkedin_mcp.tools.connections.search.models.connections_search_input import (
    ConnectionsSearchInput,
)
from linkedin_mcp.tools.connections.search.models.connections_search_output import (
    ConnectionsSearchOutput,
)


def register(
    mcp: FastMCP[None],
    container: AppContainer,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.connections.search",
        title="Search LinkedIn Connections",
        description=(
            "Search only the configured account's established first-degree connections through "
            "LinkedIn's current People surface. The server always enforces first degree. "
            "Supports the remaining current visible People filters: any/specific-title hiring, "
            "locations, current/past companies, connections-of, followers-of, schools, "
            "industries, profile languages, service categories, and first-name, last-name, "
            "title, company, and school keywords. Use linkedin.people.search for broader "
            "second-, third-plus-, or mixed-degree discovery."
        ),
        annotations=annotations,
    )
    async def _search_connections(  # pyright: ignore[reportUnusedFunction]
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        query: (
            Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=500,
                    description="Natural-language or Boolean first-degree connection keywords.",
                ),
            ]
            | None
        ) = None,
        filters: ConnectionsSearchFilters | None = None,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
    ) -> ConnectionsSearchOutput:
        await ctx.report_progress(0, 100, "Queued LinkedIn connection search")
        result = await tool_result(
            container.worker.search_connections(
                ConnectionsSearchInput(
                    context_id=context_id,
                    request_id=request_id,
                    query=query,
                    filters=filters or ConnectionsSearchFilters(),
                    page_size=page_size,
                    cursor=cursor,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn connection search complete")
        return result

    del _search_connections
