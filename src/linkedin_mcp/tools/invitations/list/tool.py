"""FastMCP definition for `linkedin.invitations.list`."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.errors import InternalServerError, LinkedInMCPError
from linkedin_mcp.infra.cursor import CursorStore
from linkedin_mcp.infra.queue import Scheduler, Task
from linkedin_mcp.tools.invitations.list.models import (
    InvitationDirection,
    InvitationFilter,
    InvitationListInput,
    InvitationListOutput,
)
from linkedin_mcp.tools.invitations.list.page import InvitationListPage
from linkedin_mcp.tools.invitations.list.pagination import execute

IdentifierArgument = Annotated[
    str,
    Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]


PageSizeArgument = Annotated[
    int,
    Field(
        ge=1,
        le=100,
        description="Number of unique items to return in this page.",
    ),
]


CursorArgument = Annotated[
    str,
    Field(
        min_length=32,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
        description=(
            "Opaque continuation cursor returned as pagination.next_cursor by the preceding page."
        ),
    ),
]


async def tool_result[ResultT](awaitable: Awaitable[ResultT]) -> ResultT:
    try:
        return await awaitable
    except Exception as error:
        safe = error if isinstance(error, LinkedInMCPError) else InternalServerError()
        raise ToolError(f"{safe.code.value}: {safe.safe_message}") from error


def register(
    mcp: FastMCP[None],
    scheduler: Scheduler,
    page: InvitationListPage,
    cursor_store: CursorStore,
    account_id: str,
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
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
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

        request = InvitationListInput(
            context_id=context_id,
            request_id=request_id,
            direction=direction,
            invitation_filter=invitation_filter,
            page_size=page_size,
            cursor=cursor,
        )
        task = Task(
            name="linkedin.invitations.list",
            execute=lambda: execute(
                request,
                page=page,
                cursor_store=cursor_store,
                account_id=account_id,
                progress=report_progress,
            ),
        )
        await scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "LinkedIn invitation read complete")
        return result

    del _list_invitations
