"""FastMCP definition for `linkedin.posts.search`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.container import AppContainer
from linkedin_mcp.queue import Task
from linkedin_mcp.tools._shared.tool import (
    CursorArgument,
    IdentifierArgument,
    PageSizeArgument,
    tool_result,
)
from linkedin_mcp.tools.posts.search.models.post_search_filters import PostSearchFilters
from linkedin_mcp.tools.posts.search.models.post_search_input import PostSearchInput
from linkedin_mcp.tools.posts.search.models.post_search_output import PostSearchOutput
from linkedin_mcp.tools.posts.search.pagination import execute


def register(
    mcp: FastMCP[None],
    container: AppContainer,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.posts.search",
        title="Search LinkedIn Posts",
        description=(
            "Search visible LinkedIn content using keywords plus sort, date, content type, "
            "From-member/company, posted-by relationship, mentioning-member/company, "
            "author-industry/company, and Author Keywords filters. Content type follows "
            "LinkedIn's current single-choice Videos, Images, Job posts, Live videos, or "
            "Documents control. Names resolve only through exact visible choices. Returns "
            "one cursor page while browser traversal remains privately bounded."
        ),
        annotations=annotations,
    )
    async def _search_posts(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        query: (
            Annotated[
                str,
                Field(
                    min_length=1,
                    max_length=500,
                    description="Natural-language or Boolean post-search keywords.",
                ),
            ]
            | None
        ) = None,
        filters: PostSearchFilters | None = None,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
    ) -> PostSearchOutput:
        await ctx.report_progress(0, 100, "Queued LinkedIn post search")
        request = PostSearchInput(
            context_id=context_id,
            request_id=request_id,
            query=query,
            filters=filters or PostSearchFilters(),
            page_size=page_size,
            cursor=cursor,
        )
        task = Task(
            name="linkedin.posts.search",
            execute=lambda: execute(
                request,
                page=container.post_search,
                pagination=container.pagination,
                account_id=container.settings.account_id,
            ),
        )
        await container.scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "LinkedIn post search complete")
        return result

    del _search_posts
