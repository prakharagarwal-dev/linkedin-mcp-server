"""FastMCP definition for `linkedin.messaging.search`."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.app.container import AppContainer
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


def register(
    mcp: FastMCP[None],
    container: AppContainer,
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
        result = await tool_result(
            container.worker.search_messages(
                ConversationSearchInput(
                    context_id=context_id,
                    request_id=request_id,
                    query=query,
                    category=category,
                    filter=filter,
                    page_size=page_size,
                    cursor=cursor,
                )
            )
        )
        await ctx.report_progress(100, 100, "LinkedIn inbox read complete")
        return result

    del _search_messages
