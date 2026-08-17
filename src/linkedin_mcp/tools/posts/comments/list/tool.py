"""FastMCP definition for `linkedin.posts.comments.list`."""

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
from linkedin_mcp.tools.posts.comments.list.models.comment_sort import CommentSort
from linkedin_mcp.tools.posts.comments.list.models.post_comments_list_input import (
    PostCommentsListInput,
)
from linkedin_mcp.tools.posts.comments.list.models.post_comments_list_output import (
    PostCommentsListOutput,
)


def register(
    mcp: FastMCP[None],
    container: AppContainer,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.posts.comments.list",
        title="Read LinkedIn Post Discussion",
        description=(
            "Read one cursor page of visible top-level comments and bounded nested replies, "
            "with relevant/recent ordering, stable comment references, exact author identities, "
            "visible text, timestamps, reaction/reply counts, and truncation coverage."
        ),
        annotations=annotations,
    )
    async def _list_post_comments(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        post_ref: Annotated[
            str,
            Field(pattern=r"^(?:activity|share|ugc-post):[0-9]{5,30}$"),
        ],
        ctx: Context[Any, Any, Any],
        sort_by: CommentSort = CommentSort.MOST_RELEVANT,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
        max_replies_per_comment: Annotated[int, Field(ge=0, le=100)] = 25,
    ) -> PostCommentsListOutput:
        await ctx.report_progress(0, 100, "Opening visible LinkedIn post discussion")
        result = await tool_result(
            container.worker.list_post_comments(
                PostCommentsListInput(
                    context_id=context_id,
                    request_id=request_id,
                    post_ref=post_ref,
                    sort_by=sort_by,
                    page_size=page_size,
                    cursor=cursor,
                    max_replies_per_comment=max_replies_per_comment,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn post discussion complete")
        return result

    del _list_post_comments
