"""Shared primitives used by multiple LinkedIn feature contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    model_validator,
)

from linkedin_mcp.linkedin.identifiers import PROFILE_SLUG_PATTERN


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
    str,
    StringConstraints(
        min_length=32,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]


class PaginatedInput(StrictModel):
    """Shared public cursor contract for bounded collection capabilities."""

    page_size: Annotated[
        int,
        Field(
            ge=1,
            le=100,
            description="Maximum unique items returned in this page.",
        ),
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
    str,
    StringConstraints(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]
AssetReference = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=500,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,499}$",
    ),
]
JobId = Annotated[str, StringConstraints(pattern=r"^[0-9]{5,30}$")]
ProfileSlug = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=200,
        pattern=PROFILE_SLUG_PATTERN,
    ),
]
CompanySlug = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,198}[A-Za-z0-9])?$",
    ),
]
PostReference = Annotated[
    str,
    StringConstraints(pattern=r"^(?:activity|share|ugc-post):[0-9]{5,30}$"),
]
CommentReference = Annotated[
    str,
    StringConstraints(pattern=r"^comment:(?:activity|share|ugc-post):[0-9]{5,30}:[0-9]{1,30}$"),
]
ConversationId = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=500,
        pattern=r"^[A-Za-z0-9_%=-]+$",
    ),
]
LinkedInFacetId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
]
LinkedInFacetIds = Annotated[
    tuple[LinkedInFacetId, ...],
    Field(max_length=10),
]
LinkedInFacetLabel = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
LinkedInFacetLabels = Annotated[
    tuple[LinkedInFacetLabel, ...],
    Field(max_length=10),
]


class CapabilityName(StrEnum):
    JOBS_SEARCH = "linkedin.jobs.search"
    JOBS_GET = "linkedin.jobs.get"
    PEOPLE_SEARCH = "linkedin.people.search"
    PEOPLE_GET = "linkedin.people.get"
    COMPANIES_SEARCH = "linkedin.companies.search"
    COMPANIES_GET = "linkedin.companies.get"
    POSTS_SEARCH = "linkedin.posts.search"
    POSTS_GET = "linkedin.posts.get"
    POST_COMMENTS_LIST = "linkedin.posts.comments.list"
    POSTS_CREATE = "linkedin.posts.create"
    POST_COMMENT = "linkedin.posts.comment"
    POST_REACT = "linkedin.posts.react"
    INVITATIONS_LIST = "linkedin.invitations.list"
    CONNECTIONS_LIST = "linkedin.connections.list"
    CONNECTIONS_SEARCH = "linkedin.connections.search"
    INVITATION_SEND = "linkedin.invitations.send"
    INVITATION_ACCEPT = "linkedin.invitations.accept"
    INVITATION_IGNORE = "linkedin.invitations.ignore"
    MESSAGING_SEARCH = "linkedin.messaging.search"
    MESSAGING_CONVERSATION_GET = "linkedin.messaging.conversation.get"
    MESSAGING_SEND = "linkedin.messaging.send"


class SourceType(StrEnum):
    JOB_SEARCH = "linkedin_job_search"
    JOB = "linkedin_job"
    PEOPLE_SEARCH = "linkedin_people_search"
    MEMBER_PROFILE = "linkedin_member_profile"
    COMPANY_SEARCH = "linkedin_company_search"
    COMPANY_PROFILE = "linkedin_company_profile"
    POST_SEARCH = "linkedin_post_search"
    POST = "linkedin_post"
    POST_COMMENTS = "linkedin_post_comments"
    INVITATIONS = "linkedin_invitations"
    CONNECTIONS = "linkedin_connections"
    MESSAGING_INBOX = "linkedin_messaging_inbox"
    MESSAGING_CONVERSATION = "linkedin_messaging_conversation"
    ACTION_EXECUTION = "linkedin_action_execution"


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


class EvidenceField(StrictModel):
    field: Annotated[str, Field(min_length=1, max_length=100)]
    quote: Annotated[str, Field(min_length=1)]
