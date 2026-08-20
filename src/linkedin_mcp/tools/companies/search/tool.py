"""FastMCP definition for `linkedin.companies.search`."""

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
from linkedin_mcp.tools.companies.search.models import (
    CompanySearchFilters,
    CompanySearchInput,
    CompanySearchOutput,
)
from linkedin_mcp.tools.companies.search.page import CompanySearchPage
from linkedin_mcp.tools.companies.search.pagination import execute

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
    page: CompanySearchPage,
    cursor_store: CursorStore,
    account_id: str,
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
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
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
        request = CompanySearchInput(
            context_id=context_id,
            request_id=request_id,
            query=query,
            filters=filters or CompanySearchFilters(),
            page_size=page_size,
            cursor=cursor,
        )
        task = Task(
            name="linkedin.companies.search",
            execute=lambda: execute(
                request,
                page=page,
                cursor_store=cursor_store,
                account_id=account_id,
            ),
        )
        await scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "LinkedIn Company search complete")
        return result

    del _search_companies
