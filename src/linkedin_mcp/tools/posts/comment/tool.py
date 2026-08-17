"""FastMCP definition for `linkedin.posts.comment`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.app.container import AppContainer
from linkedin_mcp.tools._shared.actions import ActionOutput
from linkedin_mcp.tools._shared.tool import (
    IdentifierArgument,
    tool_result,
)
from linkedin_mcp.tools.posts.comment.models import (
    CommentAttachment,
    PostCommentInput,
    PostMentionInput,
)


def register(
    mcp: FastMCP[None],
    container: AppContainer,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.posts.comment",
        title="Comment on LinkedIn Post",
        description=(
            "Publish one top-level personal-member comment on an "
            "exact visible post. Supports text, links, emoji, exact member/company mentions, "
            "one local photo, or one exact visible GIF result."
        ),
        annotations=annotations,
    )
    async def _comment_on_post(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        post_ref: Annotated[
            str,
            Field(pattern=r"^(?:activity|share|ugc-post):[0-9]{5,30}$"),
        ],
        ctx: Context[Any, Any, Any],
        text: Annotated[str, Field(min_length=1, max_length=3_000)] | None = None,
        mentions: Annotated[tuple[PostMentionInput, ...], Field(max_length=20)] = (),
        attachment: CommentAttachment | None = None,
    ) -> ActionOutput:
        await ctx.report_progress(0, 100, "Publishing LinkedIn comment")
        result = await tool_result(
            container.worker.comment_on_post(
                PostCommentInput(
                    context_id=context_id,
                    request_id=request_id,
                    post_ref=post_ref,
                    text=text,
                    mentions=mentions,
                    attachment=attachment,
                )
            )
        )
        await ctx.report_progress(100, 100, "Comment action reached a terminal outcome")
        return result

    del _comment_on_post
