"""FastMCP definition for `linkedin.invitations.list`."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from linkedin_mcp.app.container import AppContainer
from linkedin_mcp.tools._shared.tool import (
    CursorArgument,
    IdentifierArgument,
    PageSizeArgument,
    tool_result,
)
from linkedin_mcp.tools.invitations.list.models.invitation_direction import InvitationDirection
from linkedin_mcp.tools.invitations.list.models.invitation_filter import InvitationFilter
from linkedin_mcp.tools.invitations.list.models.invitation_list_input import InvitationListInput
from linkedin_mcp.tools.invitations.list.models.invitation_list_output import InvitationListOutput


def register(
    mcp: FastMCP[None],
    container: AppContainer,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.invitations.list",
        title="List LinkedIn Invitations",
        description=(
            "Read one live cursor page from the current received or sent invitation inventory, "
            "including the deduplicated union of LinkedIn's current Focused, Other, Verified, "
            "Mutual Connections, Your Company, and Your School received views when "
            "invitation_filter is all. Continuations rescan a bounded live prefix, suppress "
            "stable identities already returned, and claim completion only after the selected "
            "visible counts reconcile."
        ),
        annotations=annotations,
    )
    async def _list_invitations(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        direction: InvitationDirection = InvitationDirection.RECEIVED,
        invitation_filter: InvitationFilter | None = None,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
    ) -> InvitationListOutput:
        await ctx.report_progress(0, 100, "Queued LinkedIn invitation read")

        async def report_progress(current: int, total: int, message: str) -> None:
            ratio = 1.0 if total == 0 else min(1.0, current / total)
            await ctx.report_progress(5 + round(90 * ratio), 100, message)

        result = await tool_result(
            container.worker.list_invitations(
                InvitationListInput(
                    context_id=context_id,
                    request_id=request_id,
                    direction=direction,
                    invitation_filter=invitation_filter,
                    page_size=page_size,
                    cursor=cursor,
                ),
                progress=report_progress,
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn invitation read complete")
        return result

    del _list_invitations
