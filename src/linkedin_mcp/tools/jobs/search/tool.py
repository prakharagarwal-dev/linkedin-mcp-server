"""FastMCP definition for `linkedin.jobs.search`."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.errors import InternalServerError, LinkedInMCPError
from linkedin_mcp.infra.cursor import CursorStore
from linkedin_mcp.infra.queue import Scheduler, Task
from linkedin_mcp.tools.jobs.search.models import JobSearchFilters, JobSearchInput, JobSearchOutput
from linkedin_mcp.tools.jobs.search.page import JobSearchPage
from linkedin_mcp.tools.jobs.search.pagination import execute

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
    page: JobSearchPage,
    cursor_store: CursorStore,
    account_id: str,
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
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
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
        request = JobSearchInput(
            context_id=context_id,
            request_id=request_id,
            query=query,
            location=location,
            freshness_hours=freshness_hours,
            filters=filters or JobSearchFilters(),
            page_size=page_size,
            cursor=cursor,
        )
        task = Task(
            name="linkedin.jobs.search",
            execute=lambda: execute(
                request,
                page=page,
                cursor_store=cursor_store,
                account_id=account_id,
            ),
        )
        await scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "LinkedIn job search complete")
        return result

    del _search_jobs
