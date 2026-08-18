"""FastMCP definition for `linkedin.messaging.conversation.get`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.infra.queue import Scheduler, Task
from linkedin_mcp.tools._shared.identifiers import PROFILE_SLUG_PATTERN
from linkedin_mcp.tools._shared.tool import (
    IdentifierArgument,
    tool_result,
)
from linkedin_mcp.tools.messaging.conversation.get.evidence import source_from_conversation
from linkedin_mcp.tools.messaging.conversation.get.models.conversation_get_input import (
    ConversationGetInput,
)
from linkedin_mcp.tools.messaging.conversation.get.models.conversation_get_output import (
    ConversationGetOutput,
)
from linkedin_mcp.tools.messaging.conversation.get.page import ConversationGetPage


async def execute(
    request: ConversationGetInput,
    page: ConversationGetPage,
) -> ConversationGetOutput:
    observation = await page.read(request)
    return ConversationGetOutput(
        context_id=request.context_id,
        request_id=request.request_id,
        conversation=observation,
        sources=(source_from_conversation(observation),),
    )


def register(
    mcp: FastMCP[None],
    scheduler: Scheduler,
    page: ConversationGetPage,
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
        request = ConversationGetInput(
            context_id=context_id,
            request_id=request_id,
            profile_slug=profile_slug,
            conversation_id=conversation_id,
            conversation_ref=conversation_ref,
            max_messages=max_messages,
        )
        task = Task(
            name="linkedin.messaging.conversation.get",
            execute=lambda: execute(request, page),
        )
        await scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "LinkedIn conversation read complete")
        return result

    del _get_conversation
