"""FastMCP definition for `linkedin.posts.comments.list`."""

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
from linkedin_mcp.tools.posts.comments.list.models.comment_sort import CommentSort
from linkedin_mcp.tools.posts.comments.list.models.post_comments_list_input import (
    PostCommentsListInput,
)
from linkedin_mcp.tools.posts.comments.list.models.post_comments_list_output import (
    PostCommentsListOutput,
)
from linkedin_mcp.tools.posts.comments.list.page import PostCommentsPage
from linkedin_mcp.tools.posts.comments.list.pagination import execute


def register(
    mcp: FastMCP[None],
    scheduler: Scheduler,
    page: PostCommentsPage,
    cursor_store: CursorStore,
    account_id: str,
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
        request = PostCommentsListInput(
            context_id=context_id,
            request_id=request_id,
            post_ref=post_ref,
            sort_by=sort_by,
            page_size=page_size,
            cursor=cursor,
            max_replies_per_comment=max_replies_per_comment,
        )
        task = Task(
            name="linkedin.posts.comments.list",
            execute=lambda: execute(
                request,
                page=page,
                cursor_store=cursor_store,
                account_id=account_id,
            ),
        )
        await scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "LinkedIn post discussion complete")
        return result

    del _list_post_comments
