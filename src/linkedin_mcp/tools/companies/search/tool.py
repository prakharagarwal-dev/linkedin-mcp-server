"""FastMCP definition for `linkedin.companies.search`."""

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
from linkedin_mcp.tools.companies.search.models import (
    CompanySearchFilters,
    CompanySearchInput,
    CompanySearchOutput,
)


def register(
    mcp: FastMCP[None],
    container: AppContainer,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.companies.search",
        title="Search LinkedIn Companies",
        description=(
            "Search visible LinkedIn Company results using LinkedIn's complete current "
            "Company-search filter surface: keywords, headquarters location, industry, "
            "company-size range, visible job listings, and first-degree connection presence. "
            "Exact names are resolved only through visible filter controls; callers may "
            "alternatively provide stable facet IDs. Returns one cursor page."
        ),
        annotations=annotations,
    )
    async def _search_companies(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        query: (
            Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=500,
                    description="Natural-language or Boolean Company-search keywords.",
                ),
            ]
            | None
        ) = None,
        filters: CompanySearchFilters | None = None,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
    ) -> CompanySearchOutput:
        await ctx.report_progress(0, 100, "Queued LinkedIn Company search")
        result = await tool_result(
            container.worker.search_companies(
                CompanySearchInput(
                    context_id=context_id,
                    request_id=request_id,
                    query=query,
                    filters=filters or CompanySearchFilters(),
                    page_size=page_size,
                    cursor=cursor,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn Company search complete")
        return result

    del _search_companies
