"""FastMCP definition for `linkedin.messaging.conversation.get`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.app.container import AppContainer
from linkedin_mcp.tools._shared.identifiers import PROFILE_SLUG_PATTERN
from linkedin_mcp.tools._shared.tool import (
    IdentifierArgument,
    tool_result,
)
from linkedin_mcp.tools.messaging.conversation.get.models.conversation_get_input import (
    ConversationGetInput,
)
from linkedin_mcp.tools.messaging.conversation.get.models.conversation_get_output import (
    ConversationGetOutput,
)


def register(
    mcp: FastMCP[None],
    container: AppContainer,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.messaging.conversation.get",
        title="Read LinkedIn Conversation",
        description=(
            "Traverse LinkedIn's reverse-virtualized visible history and read both incoming "
            "and outgoing messages, attachments, replies, edits, and reaction summaries "
            "by exact profile slug, visible conversation ID, or a conversation_ref returned "
            "by messaging.search. Returns explicit history completeness and truncation "
            "evidence. Opening a conversation may cause LinkedIn to mark it seen."
        ),
        annotations=annotations,
    )
    async def _get_conversation(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
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
        max_messages: Annotated[int, Field(ge=1, le=100)] = 50,
    ) -> ConversationGetOutput:
        await ctx.report_progress(0, 100, "Opening visible LinkedIn conversation")
        result = await tool_result(
            container.worker.get_conversation(
                ConversationGetInput(
                    context_id=context_id,
                    request_id=request_id,
                    profile_slug=profile_slug,
                    conversation_id=conversation_id,
                    conversation_ref=conversation_ref,
                    max_messages=max_messages,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn conversation read complete")
        return result

    del _get_conversation
