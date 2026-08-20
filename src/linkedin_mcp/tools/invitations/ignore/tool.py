"""FastMCP definition for `linkedin.invitations.ignore`."""

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
from linkedin_mcp.tools.invitations.ignore.evidence import source_from_action_execution
from linkedin_mcp.tools.invitations.ignore.models import (
    PROFILE_SLUG_PATTERN,
    ActionCommand,
    ActionInspection,
    ActionOutcome,
    ActionOutput,
    ActionResult,
    ActionType,
    InvitationIgnoreInput,
    InvitationIgnorePayload,
)
from linkedin_mcp.tools.invitations.ignore.page import IgnoreInvitationPage

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


def _required_invitation_ref(inspection: ActionInspection) -> str:
    invitation_ref = inspection.target.invitation_ref
    if invitation_ref is None:
        raise RuntimeError("Invitation inspection returned no invitation reference.")
    return invitation_ref


async def execute(
    request: InvitationIgnoreInput,
    page: IgnoreInvitationPage,
) -> ActionOutput:
    execution_id = str(uuid.uuid4())
    started_at = datetime.now(UTC)
    inspection = await page.inspect_ignore(request)
    payload = InvitationIgnorePayload(invitation_ref=_required_invitation_ref(inspection))
    command = ActionCommand(
        action_type=ActionType.INVITATION_IGNORE,
        target=inspection.target,
        payload=payload,
    )
    try:
        page_result = await page.perform_ignore(command)
    except asyncio.CancelledError:
        raise
    except LinkedInMCPError:
        raise
    except Exception as error:
        logger.error(
            "action_execution_interrupted",
            task_name="linkedin.invitations.ignore",
            error_type=type(error).__name__,
        )
        return ActionOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            result=ActionResult(
                action_type=ActionType.INVITATION_IGNORE,
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
        action_type=ActionType.INVITATION_IGNORE,
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
    page: IgnoreInvitationPage,
) -> None:
    @mcp.tool(
        name="linkedin.invitations.ignore",
        title="Ignore LinkedIn Connection Invitation",
        description=(
            "Ignore the current incoming connection invitation from "
            "one exact member profile, then verify that its request controls disappear without "
            "creating a connection or outgoing invitation."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def _ignore_invitation(
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
    ) -> ActionOutput:
        await ctx.report_progress(0, 100, "Ignoring LinkedIn connection invitation")
        request = InvitationIgnoreInput(
            context_id=context_id,
            request_id=request_id,
            profile_slug=profile_slug,
        )
        task = Task(
            name="linkedin.invitations.ignore",
            execute=lambda: execute(request, page),
            interruptible=False,
        )
        await scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "Ignore action reached a terminal outcome")
        return result

    del _ignore_invitation
