"""FastMCP definition for `linkedin.messaging.send`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.container import AppContainer
from linkedin_mcp.queue import Task
from linkedin_mcp.tools._shared.actions import ActionOutput, ActionType, MessageSendPayload
from linkedin_mcp.tools._shared.identifiers import PROFILE_SLUG_PATTERN
from linkedin_mcp.tools._shared.tool import (
    IdentifierArgument,
    tool_result,
)
from linkedin_mcp.tools.action import execute_action
from linkedin_mcp.tools.messaging.send.models.message_file_input import MessageFileInput
from linkedin_mcp.tools.messaging.send.models.message_gif_input import MessageGifInput
from linkedin_mcp.tools.messaging.send.models.message_send_input import MessageSendInput
from linkedin_mcp.tools.messaging.send.page import MessageSendPage


async def execute(request: MessageSendInput, page: MessageSendPage) -> ActionOutput:
    return await execute_action(
        task_name="linkedin.messaging.send",
        context_id=request.context_id,
        request_id=request.request_id,
        action_type=ActionType.MESSAGE_SEND,
        payload=MessageSendPayload(
            message=request.message,
            attachment_refs=tuple(attachment.asset_ref for attachment in request.attachments),
            gif=request.gif,
            reply_to_message_ref=request.reply_to_message_ref,
        ),
        inspect=lambda: page.inspect_message(request),
        perform=page.perform_message,
    )


def register(
    mcp: FastMCP[None],
    container: AppContainer,
    annotations: ToolAnnotations,
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
        annotations=annotations,
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
            execute=lambda: execute(request, container.message_send),
            interruptible=False,
        )
        await container.scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "Message action reached a terminal outcome")
        return result

    del _send_message
