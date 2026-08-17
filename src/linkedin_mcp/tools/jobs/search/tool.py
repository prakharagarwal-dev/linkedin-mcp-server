"""FastMCP definition for `linkedin.jobs.search`."""

from __future__ import annotations

from typing import Annotated, Any, Literal

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
from linkedin_mcp.tools.jobs.search.models import (
    JobSearchFilters,
    JobSearchInput,
    JobSearchOutput,
)


def register(
    mcp: FastMCP[None],
    container: AppContainer,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.jobs.search",
        title="Search LinkedIn Jobs",
        description=(
            "Search current visible LinkedIn Jobs pages with optional keywords and typed "
            "location, Date posted, sorting, distance, workplace, experience, job type, "
            "company, industry, function, title, benefit, commitment, Easy Apply, "
            "verification, applicant-count, network, and Fair Chance filters. Hydrates "
            "LinkedIn's virtualized result cards and returns one deduplicated cursor page."
        ),
        annotations=annotations,
    )
    async def _search_jobs(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        query: (
            Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=300,
                    description=(
                        "Optional keywords or a LinkedIn Boolean query using quotes, "
                        "AND, OR, and NOT."
                    ),
                ),
            ]
            | None
        ) = None,
        location: (
            Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=200,
                    description="City, region, country, postal code, or Worldwide.",
                ),
            ]
            | None
        ) = None,
        freshness_hours: Annotated[
            Literal[24, 168, 720] | None,
            Field(
                description=(
                    "Date posted: 24, 168 (past week), 720 (past month), or null for Any time."
                ),
            ),
        ] = None,
        filters: JobSearchFilters | None = None,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
    ) -> JobSearchOutput:
        await ctx.report_progress(0, 100, "Queued LinkedIn job search")
        result = await tool_result(
            container.worker.search_jobs(
                JobSearchInput(
                    context_id=context_id,
                    request_id=request_id,
                    query=query,
                    location=location,
                    freshness_hours=freshness_hours,
                    filters=filters or JobSearchFilters(),
                    page_size=page_size,
                    cursor=cursor,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn job search complete")
        return result

    del _search_jobs
