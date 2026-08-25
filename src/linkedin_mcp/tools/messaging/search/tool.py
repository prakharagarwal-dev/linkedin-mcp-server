"""FastMCP definition for `linkedin.messaging.search`."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.cursors import CursorManager
from linkedin_mcp.errors import InternalServerError, LinkedInMCPError
from linkedin_mcp.operations import OperationManager
from linkedin_mcp.tools.messaging.search.models import (
    ConversationCategory,
    ConversationFilter,
    ConversationSearchInput,
    ConversationSearchOutput,
)
from linkedin_mcp.tools.messaging.search.page import ConversationSearchPage
from linkedin_mcp.tools.messaging.search.pagination import execute

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
    operations: OperationManager,
    page: ConversationSearchPage,
    cursors: CursorManager,
    account_id: str,
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
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
    )
    async def _search_messages(
        context_id: IdentifierArgument,
        request_id: IdentifierArgument,
        query: Annotated[str, Field(min_length=1, max_length=500)] | None = None,
        category: ConversationCategory | None = None,
        filter: ConversationFilter | None = None,
        page_size: PageSizeArgument = 25,
        cursor: CursorArgument | None = None,
    ) -> ConversationSearchOutput:
        request = ConversationSearchInput(
            context_id=context_id,
            request_id=request_id,
            query=query,
            category=category,
            filter=filter,
            page_size=page_size,
            cursor=cursor,
        )
        result = await tool_result(
            operations.run(
                "linkedin.messaging.search",
                lambda: execute(
                    request,
                    page=page,
                    cursors=cursors,
                    account_id=account_id,
                ),
            )
        )
        return result

    del _search_messages
