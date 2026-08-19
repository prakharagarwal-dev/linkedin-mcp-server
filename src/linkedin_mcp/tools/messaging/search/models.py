"""Models owned by `linkedin.messaging.search`."""

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


ConversationId = Annotated[
    str, StringConstraints(min_length=3, max_length=500, pattern="^[A-Za-z0-9_%=-]+$")
]


class SourceType(StrEnum):
    MESSAGING_INBOX = "linkedin_messaging_inbox"


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


class ConversationCategory(StrEnum):
    FOCUSED = "focused"
    OTHER = "other"
    ARCHIVED = "archived"
    SPAM = "spam"


class ConversationFilter(StrEnum):
    JOBS = "jobs"
    UNREAD = "unread"
    CONNECTIONS = "connections"
    STARRED = "starred"
    INMAIL = "inmail"


class ConversationSearchCoverage(StrictModel):
    query: str | None
    category: ConversationCategory
    filter: ConversationFilter | None = None
    rounds_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    captured_at: datetime


class ConversationSearchInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    query: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=500,
                description=(
                    "LinkedIn's visible Search messages value. The same field searches "
                    "recipient names and message keywords."
                ),
            ),
        ]
        | None
    ) = None
    category: ConversationCategory | None = Field(
        default=None,
        description=(
            "Optional current desktop inbox category. When omitted, LinkedIn's Focused "
            "category is selected deterministically."
        ),
    )
    filter: ConversationFilter | None = Field(
        default=None,
        description=(
            "Optional current desktop message filter. LinkedIn exposes these as mutually "
            "exclusive pills, so exactly zero or one filter can be selected."
        ),
    )

    @model_validator(mode="after")
    def require_search_criterion(self) -> ConversationSearchInput:
        if self.query is None and self.category is None and self.filter is None:
            raise ValueError(
                "Message search requires query, category, or one visible message filter"
            )
        return self

    @property
    def resolved_category(self) -> ConversationCategory:
        return self.category or ConversationCategory.FOCUSED


class ConversationSummary(StrictModel):
    conversation_ref: Annotated[
        str,
        StringConstraints(pattern=r"^conversation:[0-9a-f]{24}$"),
    ]
    conversation_id: ConversationId | None = None
    participant_profile_slug: ProfileSlug | None = None
    participant_profile_url: HttpUrl | None = None
    participant_name: Annotated[str, Field(min_length=1, max_length=500)]
    is_group: bool = False
    last_message_text: Annotated[str, Field(min_length=1, max_length=8_000)] | None = None
    last_activity_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    unread: bool
    starred: bool = False
    muted: bool = False
    labels: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=200)], ...],
        Field(max_length=10),
    ] = ()
    visible_text: Annotated[str, Field(min_length=1)]


class ConversationSearchOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    conversations: tuple[ConversationSummary, ...]
    coverage: ConversationSearchCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]
