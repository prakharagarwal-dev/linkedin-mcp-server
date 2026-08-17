"""FastMCP definition for `linkedin.invitations.send`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.app.container import AppContainer
from linkedin_mcp.tools._shared.actions import ActionOutput
from linkedin_mcp.tools._shared.identifiers import PROFILE_SLUG_PATTERN
from linkedin_mcp.tools._shared.tool import (
    IdentifierArgument,
    tool_result,
)
from linkedin_mcp.tools.invitations.send.models.invitation_send_input import InvitationSendInput


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
        result = await tool_result(
            container.worker.send_invitation(
                InvitationSendInput(
                    context_id=context_id,
                    request_id=request_id,
                    profile_slug=profile_slug,
                    note=note,
                )
            )
        )
        await ctx.report_progress(100, 100, "Invitation action reached a terminal outcome")
        return result

    del _send_invitation
