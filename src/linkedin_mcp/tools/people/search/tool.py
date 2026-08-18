"""FastMCP definition for `linkedin.people.search`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.container import AppContainer
from linkedin_mcp.execution import Task
from linkedin_mcp.tools._shared.tool import (
    CursorArgument,
    IdentifierArgument,
    PageSizeArgument,
    tool_result,
)
from linkedin_mcp.tools.people.search.models.people_search_filters import PeopleSearchFilters
from linkedin_mcp.tools.people.search.models.people_search_input import PeopleSearchInput
from linkedin_mcp.tools.people.search.models.people_search_output import PeopleSearchOutput
from linkedin_mcp.tools.people.search.pagination import execute


def register(
    mcp: FastMCP[None],
    container: AppContainer,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.people.search",
        title="Search LinkedIn People",
        description=(
            "Search visible LinkedIn People results using natural-language or Boolean keywords, "
            "connection degree, any/specific-title hiring, location, current/past company, "
            "connections-of, followers-of, school, industry, profile-language, service-category, "
            "and exact first-name, last-name, title, company, and school keyword filters. "
            "Returns one cursor page; name-to-ID resolution and traversal safety bounds remain "
            "private."
        ),
        annotations=annotations,
    )
    async def _search_people(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        query: (
            Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=500,
                    description="Natural-language or Boolean People-search keywords.",
                ),
            ]
            | None
        ) = None,
        filters: PeopleSearchFilters | None = None,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
    ) -> PeopleSearchOutput:
        await ctx.report_progress(0, 100, "Queued LinkedIn People search")
        request = PeopleSearchInput(
            context_id=context_id,
            request_id=request_id,
            query=query,
            filters=filters or PeopleSearchFilters(),
            page_size=page_size,
            cursor=cursor,
        )
        task = Task(
            name="linkedin.people.search",
            execute=lambda: execute(
                request,
                page=container.people_search,
                pagination=container.pagination,
                account_id=container.settings.account_id,
            ),
        )
        await container.scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "LinkedIn People search complete")
        return result

    del _search_people
