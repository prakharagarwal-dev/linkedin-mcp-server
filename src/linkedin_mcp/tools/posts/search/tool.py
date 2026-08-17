"""FastMCP definition for `linkedin.posts.search`."""

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
from linkedin_mcp.tools.posts.search.models import (
    PostSearchFilters,
    PostSearchInput,
    PostSearchOutput,
)


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
        result = await tool_result(
            container.worker.search_posts(
                PostSearchInput(
                    context_id=context_id,
                    request_id=request_id,
                    query=query,
                    filters=filters or PostSearchFilters(),
                    page_size=page_size,
                    cursor=cursor,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn post search complete")
        return result

    del _search_posts
