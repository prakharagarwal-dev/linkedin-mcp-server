"""FastMCP definition for `linkedin.posts.create`."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.errors import InternalServerError, LinkedInMCPError
from linkedin_mcp.infra.queue import Scheduler, Task
from linkedin_mcp.tools.posts.create.evidence import source_from_action_execution
from linkedin_mcp.tools.posts.create.models import (
    ActionCommand,
    ActionOutcome,
    ActionOutput,
    ActionResult,
    ActionType,
    PostAudience,
    PostCollaboratorInput,
    PostCommentControl,
    PostCreateContent,
    PostCreateInput,
    PostCreatePayload,
    PostGroupTarget,
)
from linkedin_mcp.tools.posts.create.page import PostPublishingPage

logger = structlog.get_logger(__name__)


IdentifierArgument = Annotated[
    str,
    Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]


async def tool_result[ResultT](awaitable: Awaitable[ResultT]) -> ResultT:
    try:
        return await awaitable
    except Exception as error:
        safe = error if isinstance(error, LinkedInMCPError) else InternalServerError()
        raise ToolError(f"{safe.code.value}: {safe.safe_message}") from error


async def execute(
    request: PostCreateInput,
    page: PostPublishingPage,
) -> ActionOutput:
    execution_id = str(uuid.uuid4())
    started_at = datetime.now(UTC)
    inspection = await page.inspect_post(request)
    payload = PostCreatePayload(
        content=request.content,
        audience=request.audience,
        group_target=request.group_target,
        comment_control=request.comment_control,
        brand_partnership=request.brand_partnership,
        collaborators=request.collaborators,
        scheduled_at=request.scheduled_at,
    )
    command = ActionCommand(
        action_type=ActionType.POST_CREATE,
        target=inspection.target,
        payload=payload,
    )
    try:
        page_result = await page.perform_post(command)
    except asyncio.CancelledError:
        raise
    except LinkedInMCPError:
        raise
    except Exception as error:
        logger.error(
            "action_execution_interrupted",
            task_name="linkedin.posts.create",
            error_type=type(error).__name__,
        )
        return ActionOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            result=ActionResult(
                action_type=ActionType.POST_CREATE,
                outcome=ActionOutcome.UNCERTAIN,
                performed=None,
                final_state="unknown_after_interruption",
                detail=(
                    "Execution stopped without a verified visible outcome; "
                    "operator review is required."
                ),
                started_at=started_at,
                completed_at=datetime.now(UTC),
            ),
            sources=(),
        )

    result = ActionResult(
        action_type=ActionType.POST_CREATE,
        outcome=page_result.outcome,
        performed=page_result.performed,
        final_state=page_result.final_state,
        detail=page_result.detail,
        started_at=started_at,
        completed_at=datetime.now(UTC),
    )
    source = source_from_action_execution(page_result, execution_id=execution_id)
    return ActionOutput(
        context_id=request.context_id,
        request_id=request.request_id,
        result=result,
        sources=(source,),
    )


def register(
    mcp: FastMCP[None],
    scheduler: Scheduler,
    page: PostPublishingPage,
) -> None:
    @mcp.tool(
        name="linkedin.posts.create",
        title="Create Personal LinkedIn Post",
        description=(
            "Publish or schedule one personal-member post. Supports "
            "typed text/link, up to 20 edited photos with alt text and member/company tags, "
            "video with thumbnail/captions, document, poll, celebration, event, existing-job "
            "hiring, and expert-request content, plus audience/group, comment control, brand "
            "partnership, collaborators, mentions, client-selected files, and scheduling. "
            "The content "
            "discriminator is mode, not kind. Company Page publishing is excluded."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
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
