"""FastMCP definition for `linkedin.invitations.ignore`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.infra.queue import Scheduler, Task
from linkedin_mcp.tools._shared.actions import (
    ActionInspection,
    ActionOutput,
    ActionType,
    InvitationIgnorePayload,
)
from linkedin_mcp.tools._shared.identifiers import PROFILE_SLUG_PATTERN
from linkedin_mcp.tools._shared.tool import (
    IdentifierArgument,
    tool_result,
)
from linkedin_mcp.tools.action import execute_action
from linkedin_mcp.tools.invitations.ignore.models.invitation_ignore_input import (
    InvitationIgnoreInput,
)
from linkedin_mcp.tools.invitations.ignore.page import IgnoreInvitationPage


async def execute(request: InvitationIgnoreInput, page: IgnoreInvitationPage) -> ActionOutput:
    def payload(inspection: ActionInspection) -> InvitationIgnorePayload:
        invitation_ref = inspection.target.invitation_ref
        if invitation_ref is None:
            raise RuntimeError("Invitation inspection did not return an invitation reference.")
        return InvitationIgnorePayload(invitation_ref=invitation_ref)

    return await execute_action(
        task_name="linkedin.invitations.ignore",
        context_id=request.context_id,
        request_id=request.request_id,
        action_type=ActionType.INVITATION_IGNORE,
        payload_factory=payload,
        inspect=lambda: page.inspect_ignore(request),
        perform=page.perform_ignore,
    )


def register(
    mcp: FastMCP[None],
    scheduler: Scheduler,
    page: IgnoreInvitationPage,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.invitations.ignore",
        title="Ignore LinkedIn Connection Invitation",
        description=(
            "Ignore the current incoming connection invitation from "
            "one exact member profile, then verify that its request controls disappear without "
            "creating a connection or outgoing invitation."
        ),
        annotations=annotations,
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
