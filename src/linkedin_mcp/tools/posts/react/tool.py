"""FastMCP definition for `linkedin.posts.react`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.container import AppContainer
from linkedin_mcp.queue import Task
from linkedin_mcp.tools._shared.actions import (
    ActionInspection,
    ActionOutput,
    ActionPayload,
    ActionType,
    ReactionSetPayload,
)
from linkedin_mcp.tools._shared.tool import (
    IdentifierArgument,
    tool_result,
)
from linkedin_mcp.tools.action import execute_action
from linkedin_mcp.tools.posts.react.models.post_reaction_input import PostReactionInput
from linkedin_mcp.tools.posts.react.models.reaction_state import ReactionState
from linkedin_mcp.tools.posts.react.page import PostReactionPage


async def execute(request: PostReactionInput, page: PostReactionPage) -> ActionOutput:
    def payload(inspection: ActionInspection) -> ActionPayload:
        if inspection.existing_reaction is None:
            raise RuntimeError("Reaction inspection captured no visible reaction state.")
        return ReactionSetPayload(
            post_ref=request.post_ref,
            existing_reaction=inspection.existing_reaction,
            desired_reaction=request.desired_reaction,
        )

    return await execute_action(
        task_name="linkedin.posts.react",
        context_id=request.context_id,
        request_id=request.request_id,
        action_type=ActionType.REACTION_SET,
        payload_factory=payload,
        inspect=lambda: page.inspect_reaction(request),
        perform=page.perform_reaction,
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
        request = PostReactionInput(
            context_id=context_id,
            request_id=request_id,
            post_ref=post_ref,
            desired_reaction=desired_reaction,
        )
        task = Task(
            name="linkedin.posts.react",
            execute=lambda: execute(request, container.post_reaction),
            interruptible=False,
        )
        await container.scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "Reaction action reached a terminal outcome")
        return result

    del _react_to_post
