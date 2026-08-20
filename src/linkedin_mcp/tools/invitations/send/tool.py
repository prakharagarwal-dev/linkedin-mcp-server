"""FastMCP definition for `linkedin.invitations.send`."""

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
from linkedin_mcp.tools.invitations.send.evidence import source_from_action_execution
from linkedin_mcp.tools.invitations.send.models import (
    PROFILE_SLUG_PATTERN,
    ActionCommand,
    ActionOutcome,
    ActionOutput,
    ActionResult,
    ActionType,
    InvitationSendInput,
    InvitationSendPayload,
)
from linkedin_mcp.tools.invitations.send.page import SendInvitationPage

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
    request: InvitationSendInput,
    page: SendInvitationPage,
) -> ActionOutput:
    execution_id = str(uuid.uuid4())
    started_at = datetime.now(UTC)
    inspection = await page.inspect_send(request)
    payload = InvitationSendPayload(note=request.note)
    command = ActionCommand(
        action_type=ActionType.INVITATION_SEND,
        target=inspection.target,
        payload=payload,
    )
    try:
        page_result = await page.perform_send(command)
    except asyncio.CancelledError:
        raise
    except LinkedInMCPError:
        raise
    except Exception as error:
        logger.error(
            "action_execution_interrupted",
            task_name="linkedin.invitations.send",
            error_type=type(error).__name__,
        )
        return ActionOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            result=ActionResult(
                action_type=ActionType.INVITATION_SEND,
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
        action_type=ActionType.INVITATION_SEND,
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
    page: SendInvitationPage,
) -> None:
    @mcp.tool(
        name="linkedin.invitations.send",
        title="Send LinkedIn Connection Invitation",
        description=(
            "Send one connection invitation to an exact visible "
            "profile, optionally with a personalized note of up to 200 characters. A fresh "
            "exact-profile read verifies Pending as success and Connect as LinkedIn failure."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def _send_invitation(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        profile_slug: Annotated[
            str,
            Field(
                min_length=3,
                max_length=200,
                pattern=PROFILE_SLUG_PATTERN,
            ),
        ],
        ctx: Context[Any, Any, Any],
        note: Annotated[str, Field(min_length=1, max_length=200)] | None = None,
    ) -> ActionOutput:
        await ctx.report_progress(0, 100, "Sending LinkedIn connection invitation")
        request = InvitationSendInput(
            context_id=context_id,
            request_id=request_id,
            profile_slug=profile_slug,
            note=note,
        )
        task = Task(
            name="linkedin.invitations.send",
            execute=lambda: execute(request, page),
            interruptible=False,
        )
        await scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "Invitation action reached a terminal outcome")
        return result

    del _send_invitation
