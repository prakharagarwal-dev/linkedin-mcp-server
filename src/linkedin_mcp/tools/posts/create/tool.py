"""FastMCP definition for `linkedin.posts.create`."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.infra.queue import Scheduler, Task
from linkedin_mcp.tools._shared.actions import ActionOutput, ActionType, PostCreatePayload
from linkedin_mcp.tools._shared.tool import (
    IdentifierArgument,
    tool_result,
)
from linkedin_mcp.tools.action import execute_action
from linkedin_mcp.tools.posts.create.models.post_audience import PostAudience
from linkedin_mcp.tools.posts.create.models.post_collaborator_input import PostCollaboratorInput
from linkedin_mcp.tools.posts.create.models.post_comment_control import PostCommentControl
from linkedin_mcp.tools.posts.create.models.post_create_content import PostCreateContent
from linkedin_mcp.tools.posts.create.models.post_create_input import PostCreateInput
from linkedin_mcp.tools.posts.create.models.post_group_target import PostGroupTarget
from linkedin_mcp.tools.posts.create.page import PostPublishingPage


async def execute(request: PostCreateInput, page: PostPublishingPage) -> ActionOutput:
    return await execute_action(
        task_name="linkedin.posts.create",
        context_id=request.context_id,
        request_id=request.request_id,
        action_type=ActionType.POST_CREATE,
        payload=PostCreatePayload(
            content=request.content,
            audience=request.audience,
            group_target=request.group_target,
            comment_control=request.comment_control,
            brand_partnership=request.brand_partnership,
            collaborators=request.collaborators,
            scheduled_at=request.scheduled_at,
        ),
        inspect=lambda: page.inspect_post(request),
        perform=page.perform_post,
    )


def register(
    mcp: FastMCP[None],
    scheduler: Scheduler,
    page: PostPublishingPage,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.posts.create",
        title="Create Personal LinkedIn Post",
        description=(
            "Publish or schedule one personal-member post. Supports "
            "typed text/link, up to 20 edited photos with alt text and member/company tags, "
            "video with thumbnail/captions, document, poll, celebration, event, existing-job "
            "hiring, and expert-request content, plus audience/group, comment control, brand "
            "partnership, collaborators, mentions, local assets, and scheduling. The content "
            "discriminator is mode, not kind. Company Page publishing is excluded."
        ),
        annotations=annotations,
    )
    async def _create_post(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        content: PostCreateContent,
        ctx: Context[Any, Any, Any],
        audience: PostAudience = PostAudience.ANYONE,
        group_target: PostGroupTarget | None = None,
        comment_control: PostCommentControl = PostCommentControl.ANYONE,
        brand_partnership: bool = False,
        collaborators: Annotated[
            tuple[PostCollaboratorInput, ...],
            Field(max_length=5),
        ] = (),
        scheduled_at: datetime | None = None,
    ) -> ActionOutput:
        await ctx.report_progress(0, 100, "Creating personal LinkedIn post")
        request = PostCreateInput(
            context_id=context_id,
            request_id=request_id,
            content=content,
            audience=audience,
            group_target=group_target,
            comment_control=comment_control,
            brand_partnership=brand_partnership,
            collaborators=collaborators,
            scheduled_at=scheduled_at,
        )
        task = Task(
            name="linkedin.posts.create",
            execute=lambda: execute(request, page),
            interruptible=False,
        )
        await scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "Personal-post action reached a terminal outcome")
        return result

    del _create_post
