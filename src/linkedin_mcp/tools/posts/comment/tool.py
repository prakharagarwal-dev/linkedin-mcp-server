"""FastMCP definition for `linkedin.posts.comment`."""

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
from linkedin_mcp.tools.posts.comment.evidence import source_from_action_execution
from linkedin_mcp.tools.posts.comment.models import (
    ActionCommand,
    ActionOutcome,
    ActionOutput,
    ActionResult,
    ActionType,
    CommentAttachment,
    CommentCreatePayload,
    PostCommentInput,
    PostMentionInput,
)
from linkedin_mcp.tools.posts.comment.page import PostCommentPage

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
    request: PostCommentInput,
    page: PostCommentPage,
) -> ActionOutput:
    execution_id = str(uuid.uuid4())
    started_at = datetime.now(UTC)
    inspection = await page.inspect_comment(request)
    payload = CommentCreatePayload(
        post_ref=request.post_ref,
        text=request.text,
        mentions=request.mentions,
        attachment=request.attachment,
    )
    command = ActionCommand(
        action_type=ActionType.COMMENT_CREATE,
        target=inspection.target,
        payload=payload,
    )
    try:
        page_result = await page.perform_comment(command)
    except asyncio.CancelledError:
        raise
    except LinkedInMCPError:
        raise
    except Exception as error:
        logger.error(
            "action_execution_interrupted",
            task_name="linkedin.posts.comment",
            error_type=type(error).__name__,
        )
        return ActionOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            result=ActionResult(
                action_type=ActionType.COMMENT_CREATE,
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
        action_type=ActionType.COMMENT_CREATE,
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
    page: PostCommentPage,
) -> None:
    @mcp.tool(
        name="linkedin.posts.comment",
        title="Comment on LinkedIn Post",
        description=(
            "Publish one top-level personal-member comment on an "
            "exact visible post. Supports text, links, emoji, exact member/company mentions, "
            "one local photo, or one exact visible GIF result."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
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
        request = PostCommentInput(
            context_id=context_id,
            request_id=request_id,
            post_ref=post_ref,
            text=text,
            mentions=mentions,
            attachment=attachment,
        )
        task = Task(
            name="linkedin.posts.comment",
            execute=lambda: execute(request, page),
            interruptible=False,
        )
        await scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "Comment action reached a terminal outcome")
        return result

    del _comment_on_post
