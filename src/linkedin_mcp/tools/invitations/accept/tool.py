"""FastMCP definition for `linkedin.invitations.accept`."""

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
from linkedin_mcp.tools.invitations.accept.models import (
    InvitationAcceptInput,
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
        result = await tool_result(
            container.worker.accept_invitation(
                InvitationAcceptInput(
                    context_id=context_id,
                    request_id=request_id,
                    profile_slug=profile_slug,
                )
            )
        )
        await ctx.report_progress(100, 100, "Acceptance action reached a terminal outcome")
        return result

    del _accept_invitation
