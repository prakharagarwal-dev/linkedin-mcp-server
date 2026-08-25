"""FastMCP definition for `linkedin.posts.comments.list`."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.cursors import CursorManager
from linkedin_mcp.errors import InternalServerError, LinkedInMCPError
from linkedin_mcp.operations import OperationManager
from linkedin_mcp.tools.posts.comments.list.models import (
    CommentSort,
    PostCommentsListInput,
    PostCommentsListOutput,
)
from linkedin_mcp.tools.posts.comments.list.page import PostCommentsPage
from linkedin_mcp.tools.posts.comments.list.pagination import execute

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
    operations: OperationManager,
    page: PostCommentsPage,
    cursors: CursorManager,
    account_id: str,
) -> None:
    @mcp.tool(
        name="linkedin.posts.comments.list",
        title="Read LinkedIn Post Discussion",
        description=(
            "Read one cursor page of visible top-level comments and bounded nested replies, "
            "with relevant/recent ordering, stable comment references, exact author identities, "
            "visible text, timestamps, reaction/reply counts, and truncation coverage."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    async def _list_post_comments(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        post_ref: Annotated[
            str,
            Field(pattern=r"^(?:activity|share|ugc-post):[0-9]{5,30}$"),
        ],
        sort_by: CommentSort = CommentSort.MOST_RELEVANT,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
        max_replies_per_comment: Annotated[int, Field(ge=0, le=100)] = 25,
    ) -> PostCommentsListOutput:
        request = PostCommentsListInput(
            context_id=context_id,
            request_id=request_id,
            post_ref=post_ref,
            sort_by=sort_by,
            page_size=page_size,
            cursor=cursor,
            max_replies_per_comment=max_replies_per_comment,
        )
        result = await tool_result(
            operations.run(
                "linkedin.posts.comments.list",
                lambda: execute(
                    request,
                    page=page,
                    cursors=cursors,
                    account_id=account_id,
                ),
            )
        )
        return result

    del _list_post_comments
