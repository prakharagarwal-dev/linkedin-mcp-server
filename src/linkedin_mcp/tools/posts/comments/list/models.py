"""Models owned by `linkedin.posts.comments.list`."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, model_validator


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


PostReference = Annotated[
    str, StringConstraints(pattern="^(?:activity|share|ugc-post):[0-9]{5,30}$")
]


CommentReference = Annotated[
    str, StringConstraints(pattern="^comment:(?:activity|share|ugc-post):[0-9]{5,30}:[0-9]{1,30}$")
]


class SourceType(StrEnum):
    POST_COMMENTS = "linkedin_post_comments"


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


PostProfileSlug = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{2,199}$",
    ),
]


PostCompanySlug = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,198}[A-Za-z0-9])?$"),
]


class PostAuthorType(StrEnum):
    MEMBER = "member"
    COMPANY = "company"
    UNKNOWN = "unknown"


class PostAuthor(StrictModel):
    author_type: PostAuthorType
    name: Annotated[str, Field(min_length=1, max_length=500)]
    profile_slug: PostProfileSlug | None = None
    company_slug: PostCompanySlug | None = None
    author_url: HttpUrl | None = None
    headline: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    relationship_text: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    follower_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    verified: bool = False
    viewer_is_author: bool = False

    @model_validator(mode="after")
    def validate_typed_identity(self) -> PostAuthor:
        if self.author_type is PostAuthorType.MEMBER and not self.profile_slug:
            raise ValueError("A member post author requires profile_slug")
        if self.author_type is PostAuthorType.COMPANY and not self.company_slug:
            raise ValueError("A company post author requires company_slug")
        return self


class CommentAttachmentType(StrEnum):
    PHOTO = "photo"
    GIF = "gif"


class CommentAttachmentObservation(StrictModel):
    attachment_type: CommentAttachmentType
    accessible_label: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    resource_url: HttpUrl | None = None
    visible_text: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def require_visible_attachment_identity(self) -> CommentAttachmentObservation:
        if self.accessible_label is None and self.resource_url is None:
            raise ValueError("A comment attachment requires visible identity evidence")
        return self


class CommentObservation(StrictModel):
    comment_ref: CommentReference
    post_ref: PostReference
    parent_comment_ref: CommentReference | None = None
    author: PostAuthor
    text: Annotated[str, Field(min_length=1)] | None = None
    attachments: Annotated[
        tuple[CommentAttachmentObservation, ...],
        Field(max_length=10),
    ] = ()
    posted_at_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    edited: bool = False
    reaction_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    reply_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def require_visible_comment_content(self) -> CommentObservation:
        if self.text is None and not self.attachments:
            raise ValueError("A comment observation requires text or a visible attachment")
        return self


class CommentSort(StrEnum):
    MOST_RELEVANT = "most_relevant"
    MOST_RECENT = "most_recent"


class CommentThread(StrictModel):
    comment: CommentObservation
    replies: tuple[CommentObservation, ...] = ()


class PostCommentsCoverage(StrictModel):
    post_ref: PostReference
    discussion_post_ref: PostReference
    sort_by: CommentSort
    expansion_rounds: Annotated[int, Field(ge=0)]
    top_level_visible: Annotated[int, Field(ge=0)]
    top_level_returned: Annotated[int, Field(ge=0)]
    replies_visible: Annotated[int, Field(ge=0)]
    replies_returned: Annotated[int, Field(ge=0)]
    max_comments: Annotated[int, Field(ge=1)]
    max_replies_per_comment: Annotated[int, Field(ge=0)]
    truncated: bool
    captured_at: datetime


class PostCommentsListInput(PaginatedInput):
    page_size: Annotated[
        int,
        Field(
            ge=1,
            le=100,
            description="Maximum top-level comment threads returned in this page.",
        ),
    ] = 25
    context_id: Identifier
    request_id: Identifier
    post_ref: PostReference
    sort_by: CommentSort = CommentSort.MOST_RELEVANT
    max_replies_per_comment: Annotated[int, Field(ge=0, le=100)] = 25


class PostCommentsListOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    threads: tuple[CommentThread, ...]
    coverage: PostCommentsCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]
