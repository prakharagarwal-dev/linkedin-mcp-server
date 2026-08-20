"""Models owned by `linkedin.posts.search`."""

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


LinkedInFacetId = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern="^[A-Za-z0-9_-]+$")
]


LinkedInFacetIds = Annotated[tuple[LinkedInFacetId, ...], Field(max_length=10)]


LinkedInFacetLabel = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


LinkedInFacetLabels = Annotated[tuple[LinkedInFacetLabel, ...], Field(max_length=10)]


class SourceType(StrEnum):
    POST_SEARCH = "linkedin_post_search"


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


class PostContentType(StrEnum):
    TEXT = "text"
    LINK = "link"
    ARTICLE = "article"
    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    LIVE_VIDEO = "live_video"
    NEWSLETTER = "newsletter"
    EVENT = "event"
    JOB = "job"
    POLL = "poll"
    REPOST = "repost"
    CELEBRATION = "celebration"
    OTHER = "other"


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


class PostSearchContentType(StrEnum):
    VIDEOS = "videos"
    IMAGES = "images"
    JOB_POSTS = "job_posts"
    LIVE_VIDEOS = "live_videos"
    DOCUMENTS = "documents"


class PostSearchDate(StrEnum):
    ANY_TIME = "any_time"
    PAST_24_HOURS = "past_24_hours"
    PAST_WEEK = "past_week"
    PAST_MONTH = "past_month"


class PostSearchPostedBy(StrEnum):
    ME = "me"
    FIRST_CONNECTIONS = "first_connections"
    PEOPLE_YOU_FOLLOW = "people_you_follow"


class PostSearchSort(StrEnum):
    TOP_MATCH = "top_match"
    LATEST = "latest"


class PostSearchFilters(StrictModel):
    """Every filter in LinkedIn's current visible Posts All-filters panel."""

    sort_by: PostSearchSort = Field(
        default=PostSearchSort.TOP_MATCH,
        description="Sort by LinkedIn's visible Top Match or Latest choice.",
    )
    date_posted: PostSearchDate = Field(
        default=PostSearchDate.ANY_TIME,
        description=(
            "Limit posts to the past 24 hours, week, or month; Any time leaves "
            "LinkedIn's date filter unset."
        ),
    )
    content_type: PostSearchContentType | None = Field(
        default=None,
        description=(
            "One current visible content type: videos, images, job posts, live videos, "
            "or documents."
        ),
    )
    from_member_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact LinkedIn member facet IDs for From member.",
    )
    from_member_names: LinkedInFacetLabels = Field(
        default=(),
        description="Member names to resolve through the visible From member picker.",
    )
    from_company_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact LinkedIn organization facet IDs for From company.",
    )
    from_company_names: LinkedInFacetLabels = Field(
        default=(),
        description="Company names to resolve through the visible From company picker.",
    )
    posted_by: Annotated[
        tuple[PostSearchPostedBy, ...],
        Field(max_length=len(PostSearchPostedBy)),
    ] = Field(
        default=(),
        description="Posts by the configured member, first-degree connections, and/or follows.",
    )
    mentioning_member_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact member facet IDs for Mentioning member.",
    )
    mentioning_member_names: LinkedInFacetLabels = Field(
        default=(),
        description="Member names to resolve through the visible Mentioning member picker.",
    )
    mentioning_company_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact organization facet IDs for Mentioning company.",
    )
    mentioning_company_names: LinkedInFacetLabels = Field(
        default=(),
        description="Company names to resolve through the visible Mentioning company picker.",
    )
    author_industry_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact industry facet IDs for Author industry.",
    )
    author_industry_names: LinkedInFacetLabels = Field(
        default=(),
        description="Industries to resolve through the visible Author industry picker.",
    )
    author_company_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact organization facet IDs for Author company.",
    )
    author_company_names: LinkedInFacetLabels = Field(
        default=(),
        description="Companies to resolve through the visible Author company picker.",
    )
    author_keywords: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=300,
                description="Visible Author Keywords text applied to the author's title.",
            ),
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def validate_filters(self) -> PostSearchFilters:
        sequence_fields = (
            "from_member_ids",
            "from_member_names",
            "from_company_ids",
            "from_company_names",
            "posted_by",
            "mentioning_member_ids",
            "mentioning_member_names",
            "mentioning_company_ids",
            "mentioning_company_names",
            "author_industry_ids",
            "author_industry_names",
            "author_company_ids",
            "author_company_names",
        )
        for field_name in sequence_fields:
            values = getattr(self, field_name)
            normalized = tuple(
                value.casefold() if isinstance(value, str) else value for value in values
            )
            if len(set(normalized)) != len(normalized):
                raise ValueError(f"{field_name} cannot contain duplicate values")
        for ids_field, names_field in (
            ("from_member_ids", "from_member_names"),
            ("from_company_ids", "from_company_names"),
            ("mentioning_member_ids", "mentioning_member_names"),
            ("mentioning_company_ids", "mentioning_company_names"),
            ("author_industry_ids", "author_industry_names"),
            ("author_company_ids", "author_company_names"),
        ):
            if len(getattr(self, ids_field)) + len(getattr(self, names_field)) > 10:
                raise ValueError(
                    f"{ids_field} and {names_field} can contain at most ten combined values"
                )
        return self

    def has_constraints(self) -> bool:
        return (
            self.date_posted is not PostSearchDate.ANY_TIME
            or self.content_type is not None
            or bool(self.posted_by)
            or self.author_keywords is not None
            or any(
                getattr(self, field_name)
                for field_name in (
                    "from_member_ids",
                    "from_member_names",
                    "from_company_ids",
                    "from_company_names",
                    "mentioning_member_ids",
                    "mentioning_member_names",
                    "mentioning_company_ids",
                    "mentioning_company_names",
                    "author_industry_ids",
                    "author_industry_names",
                    "author_company_ids",
                    "author_company_names",
                )
            )
        )


class PostSearchCoverage(StrictModel):
    query: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    filters: PostSearchFilters = Field(default_factory=PostSearchFilters)
    pages_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    unsupported_result_count: Annotated[int, Field(ge=0)] = Field(
        default=0,
        description=(
            "Selected visible post cards omitted because their stable post or author "
            "identity is outside the typed public contract."
        ),
    )
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    captured_at: datetime


class PostSearchInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    query: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    filters: PostSearchFilters = Field(default_factory=PostSearchFilters)

    @model_validator(mode="after")
    def require_a_search_criterion(self) -> PostSearchInput:
        if not self.query and not self.filters.has_constraints():
            raise ValueError("Post search requires query or at least one substantive filter")
        return self


class PostSummary(StrictModel):
    post_ref: PostReference
    post_url: HttpUrl
    author: PostAuthor
    text: Annotated[str, Field(min_length=1)] | None = None
    posted_at_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    content_type: PostContentType = PostContentType.TEXT
    reaction_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    comment_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    repost_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]


class PostSearchOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    posts: tuple[PostSummary, ...]
    coverage: PostSearchCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]
