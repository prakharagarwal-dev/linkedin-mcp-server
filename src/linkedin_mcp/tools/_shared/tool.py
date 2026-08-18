"""Common FastMCP adapter types used by capability-owned tool modules."""

from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Annotated

from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.errors import InternalServerError, LinkedInMCPError

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


@dataclass(frozen=True, slots=True)
class ToolAnnotationSet:
    local_read: ToolAnnotations
    linkedin_read: ToolAnnotations
    messaging_read: ToolAnnotations
    linkedin_write: ToolAnnotations


def tool_annotations() -> ToolAnnotationSet:
    return ToolAnnotationSet(
        local_read=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        linkedin_read=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
        messaging_read=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=True,
        ),
        linkedin_write=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=True,
        ),
    )


async def tool_result[ResultT](awaitable: Awaitable[ResultT]) -> ResultT:
    try:
        return await awaitable
    except Exception as error:
        safe = safe_capability_error(error)
        raise ToolError(f"{safe.code.value}: {safe.safe_message}") from error


def safe_capability_error(error: Exception) -> LinkedInMCPError:
    """Project unexpected failures to the public, non-secret tool error contract."""

    if isinstance(error, LinkedInMCPError):
        return error
    return InternalServerError()
