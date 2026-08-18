"""FastMCP definition for `linkedin.invitations.send`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.container import AppContainer
from linkedin_mcp.execution import Task
from linkedin_mcp.tools._shared.actions import (
    ActionOutput,
    ActionType,
    InvitationSendPayload,
)
from linkedin_mcp.tools._shared.identifiers import PROFILE_SLUG_PATTERN
from linkedin_mcp.tools._shared.tool import (
    IdentifierArgument,
    tool_result,
)
from linkedin_mcp.tools.action import execute_action
from linkedin_mcp.tools.invitations.send.models.invitation_send_input import InvitationSendInput
from linkedin_mcp.tools.invitations.send.page import SendInvitationPage


async def execute(request: InvitationSendInput, page: SendInvitationPage) -> ActionOutput:
    return await execute_action(
        task_name="linkedin.invitations.send",
        context_id=request.context_id,
        request_id=request.request_id,
        action_type=ActionType.INVITATION_SEND,
        payload=InvitationSendPayload(note=request.note),
        inspect=lambda: page.inspect_send(request),
        perform=page.perform_send,
    )


def register(
    mcp: FastMCP[None],
    container: AppContainer,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.invitations.send",
        title="Send LinkedIn Connection Invitation",
        description=(
            "Send one connection invitation to an exact visible "
            "profile, optionally with a personalized note of up to 200 characters. A fresh "
            "exact-profile read verifies Pending as success and Connect as LinkedIn failure."
        ),
        annotations=annotations,
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
            execute=lambda: execute(request, container.invitation_send),
            interruptible=False,
        )
        await container.scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "Invitation action reached a terminal outcome")
        return result

    del _send_invitation
