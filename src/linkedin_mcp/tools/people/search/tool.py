"""FastMCP definition for `linkedin.people.search`."""

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
from linkedin_mcp.tools.people.search.models import (
    PeopleSearchFilters,
    PeopleSearchInput,
    PeopleSearchOutput,
)
from linkedin_mcp.tools.people.search.page import PeopleSearchPage
from linkedin_mcp.tools.people.search.pagination import execute

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
    page: PeopleSearchPage,
    cursor_store: CursorStore,
    account_id: str,
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
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
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
                page=page,
                cursor_store=cursor_store,
                account_id=account_id,
            ),
        )
        await scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "LinkedIn People search complete")
        return result

    del _search_people
