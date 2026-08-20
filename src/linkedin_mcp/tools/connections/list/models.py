"""Models owned by `linkedin.connections.list`."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator

PROFILE_SLUG_SEGMENT_PATTERN = r"[A-Za-z0-9][A-Za-z0-9-]{2,199}"


PROFILE_SLUG_PATTERN = rf"^{PROFILE_SLUG_SEGMENT_PATTERN}$"


class StrictModel(BaseModel):
    """Base model that rejects undeclared input and normalizes strings."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
        validate_assignment=True,
    )


PaginationCursor = Annotated[
    str, StringConstraints(min_length=32, max_length=128, pattern="^[A-Za-z0-9_-]+$")
]


class PaginatedInput(StrictModel):
    """Shared public cursor contract for bounded collection capabilities."""

    page_size: Annotated[
        int, Field(ge=1, le=100, description="Maximum unique items returned in this page.")
    ] = 25
    cursor: (
        Annotated[
            PaginationCursor,
            Field(
                description=(
                    "Opaque continuation cursor from the immediately preceding page. "
                    "Cursors are process-local, single-use, filter-bound, and expiring."
                )
            ),
        ]
        | None
    ) = None


Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=200, pattern="^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]


ProfileSlug = Annotated[
    str, StringConstraints(min_length=3, max_length=200, pattern=PROFILE_SLUG_PATTERN)
]


class SourceType(StrEnum):
    CONNECTIONS = "linkedin_connections"


class StopReason(StrEnum):
    RESULT_LIMIT = "result_limit"
    SAFETY_BOUND = "safety_bound"
    NO_NEW_RESULTS = "no_new_results"
    VISIBLE_PAGE_COMPLETE = "visible_page_complete"


class SourceReference(StrictModel):
    source_id: Identifier
    source_type: SourceType
    source_url: HttpUrl
    captured_at: datetime


class PaginationMetadata(StrictModel):
    """Reader-facing state for one page of a process-local live scan."""

    scan_id: Identifier
    page_size: Annotated[int, Field(ge=1, le=100)]
    returned_count: Annotated[int, Field(ge=0, le=100)]
    cumulative_count: Annotated[int, Field(ge=0)]
    has_more: bool
    next_cursor: PaginationCursor | None = None
    cursor_expires_at: datetime | None = None
    truncated: bool = False
    consistency: Literal["live_deduplicated"] = "live_deduplicated"

    @model_validator(mode="after")
    def validate_cursor_state(self) -> PaginationMetadata:
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("has_more must match the presence of next_cursor")
        if self.has_more != (self.cursor_expires_at is not None):
            raise ValueError("has_more must match the cursor expiry")
        if self.returned_count > self.page_size:
            raise ValueError("returned_count cannot exceed page_size")
        return self


class ConnectionSummary(StrictModel):
    profile_slug: ProfileSlug
    profile_url: HttpUrl
    name: Annotated[str, Field(min_length=1, max_length=500)]
    headline: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    connected_at_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]


class ConnectionsSortBy(StrEnum):
    RECENTLY_ADDED = "recently_added"
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"


class ConnectionsListCoverage(StrictModel):
    sort_by: ConnectionsSortBy
    rounds_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    captured_at: datetime


class ConnectionsListInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    sort_by: ConnectionsSortBy = ConnectionsSortBy.RECENTLY_ADDED


class ConnectionsListOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    connections: tuple[ConnectionSummary, ...]
    coverage: ConnectionsListCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]
