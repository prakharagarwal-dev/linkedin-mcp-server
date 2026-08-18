"""FastMCP definition for `linkedin.invitations.accept`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.container import AppContainer
from linkedin_mcp.queue import Task
from linkedin_mcp.tools._shared.actions import (
    ActionInspection,
    ActionOutput,
    ActionType,
    InvitationAcceptPayload,
)
from linkedin_mcp.tools._shared.identifiers import PROFILE_SLUG_PATTERN
from linkedin_mcp.tools._shared.tool import (
    IdentifierArgument,
    tool_result,
)
from linkedin_mcp.tools.action import execute_action
from linkedin_mcp.tools.invitations.accept.models.invitation_accept_input import (
    InvitationAcceptInput,
)
from linkedin_mcp.tools.invitations.accept.page import AcceptInvitationPage


async def execute(request: InvitationAcceptInput, page: AcceptInvitationPage) -> ActionOutput:
    def payload(inspection: ActionInspection) -> InvitationAcceptPayload:
        invitation_ref = inspection.target.invitation_ref
        if invitation_ref is None:
            raise RuntimeError("Invitation inspection did not return an invitation reference.")
        return InvitationAcceptPayload(invitation_ref=invitation_ref)

    return await execute_action(
        task_name="linkedin.invitations.accept",
        context_id=request.context_id,
        request_id=request.request_id,
        action_type=ActionType.INVITATION_ACCEPT,
        payload_factory=payload,
        inspect=lambda: page.inspect_accept(request),
        perform=page.perform_accept,
    )


def register(
    mcp: FastMCP[None],
    container: AppContainer,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.invitations.accept",
        title="Accept LinkedIn Connection Invitation",
        description=(
            "Accept the current incoming connection invitation from "
            "one exact member profile, then verify that the request controls disappear and the "
            "profile visibly becomes a first-degree connection."
        ),
        annotations=annotations,
    )
    async def _accept_invitation(
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
        await ctx.report_progress(0, 100, "Accepting LinkedIn connection invitation")
        request = InvitationAcceptInput(
            context_id=context_id,
            request_id=request_id,
            profile_slug=profile_slug,
        )
        task = Task(
            name="linkedin.invitations.accept",
            execute=lambda: execute(request, container.invitation_accept),
            interruptible=False,
        )
        await container.scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "Acceptance action reached a terminal outcome")
        return result

    del _accept_invitation
