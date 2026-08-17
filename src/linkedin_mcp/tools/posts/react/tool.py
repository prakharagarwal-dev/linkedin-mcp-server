"""FastMCP definition for `linkedin.posts.react`."""

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
from linkedin_mcp.tools.posts.react.models import (
    PostReactionInput,
    ReactionState,
)


def register(
    mcp: FastMCP[None],
    container: AppContainer,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.posts.react",
        title="React to LinkedIn Post",
        description=(
            "Set, change, remove, or safely no-op the configured "
            "personal account's reaction on one exact visible post. Supported target states are "
            "none, like, celebrate, support, love, insightful, and funny."
        ),
        annotations=annotations,
    )
    async def _react_to_post(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        post_ref: Annotated[
            str,
            Field(pattern=r"^(?:activity|share|ugc-post):[0-9]{5,30}$"),
        ],
        desired_reaction: ReactionState,
        ctx: Context[Any, Any, Any],
    ) -> ActionOutput:
        await ctx.report_progress(0, 100, "Applying LinkedIn post reaction")
        result = await tool_result(
            container.worker.react_to_post(
                PostReactionInput(
                    context_id=context_id,
                    request_id=request_id,
                    post_ref=post_ref,
                    desired_reaction=desired_reaction,
                )
            )
        )
        await ctx.report_progress(100, 100, "Reaction action reached a terminal outcome")
        return result

    del _react_to_post
