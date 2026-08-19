"""FastMCP definition for `linkedin.messaging.send`."""

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
from linkedin_mcp.tools.messaging.send.evidence import source_from_action_execution
from linkedin_mcp.tools.messaging.send.models import (
    PROFILE_SLUG_PATTERN,
    ActionCommand,
    ActionOutcome,
    ActionOutput,
    ActionResult,
    ActionType,
    MessageFileInput,
    MessageGifInput,
    MessageSendInput,
    MessageSendPayload,
)
from linkedin_mcp.tools.messaging.send.page import MessageSendPage

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
    request: MessageSendInput,
    page: MessageSendPage,
) -> ActionOutput:
    execution_id = str(uuid.uuid4())
    started_at = datetime.now(UTC)
    inspection = await page.inspect_message(request)
    payload = MessageSendPayload(
        message=request.message,
        attachment_refs=tuple(attachment.asset_ref for attachment in request.attachments),
        gif=request.gif,
        reply_to_message_ref=request.reply_to_message_ref,
    )
    command = ActionCommand(
        action_type=ActionType.MESSAGE_SEND,
        target=inspection.target,
        payload=payload,
    )
    try:
        page_result = await page.perform_message(command)
    except asyncio.CancelledError:
        raise
    except LinkedInMCPError:
        raise
    except Exception as error:
        logger.error(
            "action_execution_interrupted",
            task_name="linkedin.messaging.send",
            error_type=type(error).__name__,
        )
        return ActionOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            result=ActionResult(
                action_type=ActionType.MESSAGE_SEND,
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
        action_type=ActionType.MESSAGE_SEND,
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
    page: MessageSendPage,
) -> None:
    @mcp.tool(
        name="linkedin.messaging.send",
        title="Send LinkedIn Message",
        description=(
            "Send one message in a visible one-to-one standard "
            "conversation, using the exact profile's "
            "Message button for profile targets and accepting its recipient-bound compact "
            "pane or following its exact visible Messaging href in the same operation page, "
            "with exact text/emoji, current desktop file attachments, one exact KLIPY GIF title, "
            "and optionally an exact reply-to message_ref. Group chats, message requests, and "
            "paid InMail are excluded."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )
    async def _send_message(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        message: Annotated[str, Field(min_length=1, max_length=8_000)] | None = None,
        attachments: Annotated[tuple[MessageFileInput, ...], Field(max_length=20)] = (),
        gif: MessageGifInput | None = None,
        reply_to_message_ref: (
            Annotated[str, Field(pattern=r"^message:[0-9a-f]{24}$")] | None
        ) = None,
        profile_slug: (
            Annotated[
                str,
                Field(
                    min_length=3,
                    max_length=200,
                    pattern=PROFILE_SLUG_PATTERN,
                ),
            ]
            | None
        ) = None,
        conversation_id: (
            Annotated[
                str,
                Field(min_length=3, max_length=500, pattern=r"^[A-Za-z0-9_%=-]+$"),
            ]
            | None
        ) = None,
        conversation_ref: (
            Annotated[str, Field(pattern=r"^conversation:[0-9a-f]{24}$")] | None
        ) = None,
    ) -> ActionOutput:
        await ctx.report_progress(0, 100, "Sending LinkedIn message")
        request = MessageSendInput(
            context_id=context_id,
            request_id=request_id,
            profile_slug=profile_slug,
            conversation_id=conversation_id,
            conversation_ref=conversation_ref,
            message=message,
            attachments=attachments,
            gif=gif,
            reply_to_message_ref=reply_to_message_ref,
        )
        task = Task(
            name="linkedin.messaging.send",
            execute=lambda: execute(request, page),
            interruptible=False,
        )
        await scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "Message action reached a terminal outcome")
        return result

    del _send_message
