"""FastMCP definition for `linkedin.posts.react`."""

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
from linkedin_mcp.tools.posts.react.evidence import source_from_action_execution
from linkedin_mcp.tools.posts.react.models import (
    ActionCommand,
    ActionInspection,
    ActionOutcome,
    ActionOutput,
    ActionResult,
    ActionType,
    PostReactionInput,
    ReactionSetPayload,
    ReactionState,
)
from linkedin_mcp.tools.posts.react.page import PostReactionPage

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


def _required_reaction(inspection: ActionInspection) -> ReactionState:
    if inspection.existing_reaction is None:
        raise RuntimeError("Reaction inspection captured no visible reaction state.")
    return inspection.existing_reaction


async def execute(
    request: PostReactionInput,
    page: PostReactionPage,
) -> ActionOutput:
    execution_id = str(uuid.uuid4())
    started_at = datetime.now(UTC)
    inspection = await page.inspect_reaction(request)
    payload = ReactionSetPayload(
        post_ref=request.post_ref,
        existing_reaction=_required_reaction(inspection),
        desired_reaction=request.desired_reaction,
    )
    command = ActionCommand(
        action_type=ActionType.REACTION_SET,
        target=inspection.target,
        payload=payload,
    )
    try:
        page_result = await page.perform_reaction(command)
    except asyncio.CancelledError:
        raise
    except LinkedInMCPError:
        raise
    except Exception as error:
        logger.error(
            "action_execution_interrupted",
            task_name="linkedin.posts.react",
            error_type=type(error).__name__,
        )
        return ActionOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            result=ActionResult(
                action_type=ActionType.REACTION_SET,
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
        action_type=ActionType.REACTION_SET,
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
    page: PostReactionPage,
) -> None:
    @mcp.tool(
        name="linkedin.posts.react",
        title="React to LinkedIn Post",
        description=(
            "Set, change, remove, or safely no-op the configured "
            "personal account's reaction on one exact visible post. Supported target states are "
            "none, like, celebrate, support, love, insightful, and funny."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
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
            execute=lambda: execute(request, page),
            interruptible=False,
        )
        await scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "Reaction action reached a terminal outcome")
        return result

    del _react_to_post
