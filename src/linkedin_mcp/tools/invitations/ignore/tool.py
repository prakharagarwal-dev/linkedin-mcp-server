"""FastMCP definition for `linkedin.invitations.ignore`."""

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
from linkedin_mcp.tools.invitations.ignore.models import (
    InvitationIgnoreInput,
)


def register(
    mcp: FastMCP[None],
    container: AppContainer,
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
        result = await tool_result(
            container.worker.ignore_invitation(
                InvitationIgnoreInput(
                    context_id=context_id,
                    request_id=request_id,
                    profile_slug=profile_slug,
                )
            )
        )
        await ctx.report_progress(100, 100, "Ignore action reached a terminal outcome")
        return result

    del _ignore_invitation
