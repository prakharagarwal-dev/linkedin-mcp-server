"""FastMCP definition for `linkedin.companies.search`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.infra.cursor import CursorStore
from linkedin_mcp.infra.queue import Scheduler, Task
from linkedin_mcp.tools._shared.tool import (
    CursorArgument,
    IdentifierArgument,
    PageSizeArgument,
    tool_result,
)
from linkedin_mcp.tools.companies.search.models.company_search_filters import CompanySearchFilters
from linkedin_mcp.tools.companies.search.models.company_search_input import CompanySearchInput
from linkedin_mcp.tools.companies.search.models.company_search_output import CompanySearchOutput
from linkedin_mcp.tools.companies.search.page import CompanySearchPage
from linkedin_mcp.tools.companies.search.pagination import execute


def register(
    mcp: FastMCP[None],
    scheduler: Scheduler,
    page: CompanySearchPage,
    cursor_store: CursorStore,
    account_id: str,
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
