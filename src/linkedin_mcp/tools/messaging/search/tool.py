"""FastMCP definition for `linkedin.messaging.search`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.infra.cursor import CursorStore
from linkedin_mcp.infra.queue import Scheduler, Task
from linkedin_mcp.tools._shared.tool import (
    CursorArgument,
    IdentifierArgument,
    PageSizeArgument,
    tool_result,
)
from linkedin_mcp.tools.messaging.search.models.conversation_category import ConversationCategory
from linkedin_mcp.tools.messaging.search.models.conversation_filter import ConversationFilter
from linkedin_mcp.tools.messaging.search.models.conversation_search_input import (
    ConversationSearchInput,
)
from linkedin_mcp.tools.messaging.search.models.conversation_search_output import (
    ConversationSearchOutput,
)
from linkedin_mcp.tools.messaging.search.page import ConversationSearchPage
from linkedin_mcp.tools.messaging.search.pagination import execute


def register(
    mcp: FastMCP[None],
    scheduler: Scheduler,
    page: ConversationSearchPage,
    cursor_store: CursorStore,
    account_id: str,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.messaging.search",
        title="Search LinkedIn Messages",
        description=(
            "Search the current desktop inbox by recipient or message keywords, optionally "
            "within Focused, Other, Archived, or Spam and exactly one of Jobs, Unread, "
            "Connections, InMail, or Starred. At least one search criterion is required. "
            "Results are cursor-paginated current conversation cards."
        ),
        annotations=annotations,
    )
    async def _search_messages(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        ctx: Context[Any, Any, Any],
        query: Annotated[str, Field(min_length=1, max_length=500)] | None = None,
        category: ConversationCategory | None = None,
        filter: ConversationFilter | None = None,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
    ) -> ConversationSearchOutput:
        await ctx.report_progress(0, 100, "Queued LinkedIn inbox read")
        request = ConversationSearchInput(
            context_id=context_id,
            request_id=request_id,
            query=query,
            category=category,
            filter=filter,
            page_size=page_size,
            cursor=cursor,
        )
        task = Task(
            name="linkedin.messaging.search",
            execute=lambda: execute(
                request,
                page=page,
                cursor_store=cursor_store,
                account_id=account_id,
            ),
        )
        await scheduler.schedule(task)
        result = await tool_result(task.result())
        await ctx.report_progress(100, 100, "LinkedIn inbox read complete")
        return result

    del _search_messages
