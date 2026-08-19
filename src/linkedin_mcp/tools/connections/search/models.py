"""Models owned by `linkedin.connections.search`."""

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


class PersonConnectionDegree(StrEnum):
    FIRST = "first"
    SECOND = "second"
    THIRD_OR_MORE = "third_or_more"
    OUT_OF_NETWORK = "out_of_network"


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


LinkedInFacetId = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern="^[A-Za-z0-9_-]+$")
]


LinkedInFacetIds = Annotated[tuple[LinkedInFacetId, ...], Field(max_length=10)]


LinkedInFacetLabel = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


LinkedInFacetLabels = Annotated[tuple[LinkedInFacetLabel, ...], Field(max_length=10)]


class SourceType(StrEnum):
    PEOPLE_SEARCH = "linkedin_people_search"


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


class PeopleSearchConnectionDegree(StrEnum):
    FIRST = "first"
    SECOND = "second"
    THIRD_OR_MORE = "third_or_more"


class PeopleSearchFilterBase(StrictModel):
    """Shared non-degree filters from LinkedIn's visible People-filter side panel."""

    actively_hiring: bool = Field(
        default=False,
        description="Match people visibly hiring for any job title.",
    )
    actively_hiring_job_title_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact visible Actively-hiring job-title facet IDs.",
    )
    actively_hiring_job_title_names: LinkedInFacetLabels = Field(
        default=(),
        description=(
            "Job titles to resolve through LinkedIn's visible Hiring for job title picker."
        ),
    )
    location_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact LinkedIn geography facet IDs.",
    )
    location_names: LinkedInFacetLabels = Field(
        default=(),
        description="Locations to resolve through LinkedIn's visible location picker.",
    )
    current_company_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact current-company facet IDs.",
    )
    current_company_names: LinkedInFacetLabels = Field(
        default=(),
        description="Current companies to resolve through the visible company picker.",
    )
    connections_of_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact visible member facet IDs for Connections of.",
    )
    connections_of_names: LinkedInFacetLabels = Field(
        default=(),
        description="Member names to resolve through the visible Connections of picker.",
    )
    followers_of_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact visible member facet IDs for Followers of.",
    )
    followers_of_names: LinkedInFacetLabels = Field(
        default=(),
        description="Member names to resolve through the visible Followers of picker.",
    )
    past_company_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact past-company facet IDs.",
    )
    past_company_names: LinkedInFacetLabels = Field(
        default=(),
        description="Past companies to resolve through the visible company picker.",
    )
    school_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact LinkedIn school facet IDs.",
    )
    school_names: LinkedInFacetLabels = Field(
        default=(),
        description="Schools to resolve through LinkedIn's visible school picker.",
    )
    industry_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact LinkedIn industry facet IDs.",
    )
    industry_names: LinkedInFacetLabels = Field(
        default=(),
        description="Industries to resolve through LinkedIn's visible industry picker.",
    )
    profile_language_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact visible profile-language codes.",
    )
    profile_language_names: LinkedInFacetLabels = Field(
        default=(),
        description="Profile languages to resolve from current visible choices.",
    )
    service_category_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact visible service-category facet IDs.",
    )
    service_category_names: LinkedInFacetLabels = Field(
        default=(),
        description="Service categories to resolve through the visible services picker.",
    )
    first_name: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Visible First name keyword filter.",
            ),
        ]
        | None
    ) = None
    last_name: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Visible Last name keyword filter.",
            ),
        ]
        | None
    ) = None
    title: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=300,
                description="Visible Title keyword filter.",
            ),
        ]
        | None
    ) = None
    company: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=300,
                description="Visible Company keyword filter.",
            ),
        ]
        | None
    ) = None
    school: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=300,
                description="Visible School keyword filter.",
            ),
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def reject_duplicate_or_unbounded_values(self) -> PeopleSearchFilterBase:
        sequence_fields = (
            "actively_hiring_job_title_ids",
            "actively_hiring_job_title_names",
            "location_ids",
            "location_names",
            "current_company_ids",
            "current_company_names",
            "connections_of_ids",
            "connections_of_names",
            "followers_of_ids",
            "followers_of_names",
            "past_company_ids",
            "past_company_names",
            "school_ids",
            "school_names",
            "industry_ids",
            "industry_names",
            "profile_language_ids",
            "profile_language_names",
            "service_category_ids",
            "service_category_names",
        )
        for field_name in sequence_fields:
            values = getattr(self, field_name)
            normalized = tuple(
                value.casefold() if isinstance(value, str) else value for value in values
            )
            if len(set(normalized)) != len(normalized):
                raise ValueError(f"{field_name} cannot contain duplicate values")
        for ids_field, names_field in (
            (
                "actively_hiring_job_title_ids",
                "actively_hiring_job_title_names",
            ),
            ("location_ids", "location_names"),
            ("current_company_ids", "current_company_names"),
            ("connections_of_ids", "connections_of_names"),
            ("followers_of_ids", "followers_of_names"),
            ("past_company_ids", "past_company_names"),
            ("school_ids", "school_names"),
            ("industry_ids", "industry_names"),
            ("profile_language_ids", "profile_language_names"),
            ("service_category_ids", "service_category_names"),
        ):
            if len(getattr(self, ids_field)) + len(getattr(self, names_field)) > 10:
                raise ValueError(
                    f"{ids_field} and {names_field} can contain at most ten combined values"
                )
        if self.actively_hiring and (
            self.actively_hiring_job_title_ids or self.actively_hiring_job_title_names
        ):
            raise ValueError(
                "actively_hiring cannot be combined with specific actively-hiring job titles"
            )
        return self

    def has_constraints(self) -> bool:
        return any(value for _, value in self)


class PeopleSearchFilters(PeopleSearchFilterBase):
    """All-network filters from LinkedIn's current visible People-filter side panel."""

    connection_degrees: Annotated[
        tuple[PeopleSearchConnectionDegree, ...],
        Field(max_length=3),
    ] = Field(
        default=(),
        description="First-, second-, and/or third-plus-degree visible network filters.",
    )

    @model_validator(mode="after")
    def reject_duplicate_degrees(self) -> PeopleSearchFilters:
        if len(set(self.connection_degrees)) != len(self.connection_degrees):
            raise ValueError("connection_degrees cannot contain duplicate values")
        return self


class PeopleSearchCoverage(StrictModel):
    query: str | None
    filters: PeopleSearchFilters = Field(default_factory=PeopleSearchFilters)
    pages_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    unidentifiable_result_count: Annotated[int, Field(ge=0)] = Field(
        default=0,
        description=(
            "Visible LinkedIn Member cards omitted because LinkedIn exposed no profile identity."
        ),
    )
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    captured_at: datetime


class PeopleSearchInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    query: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=500,
                description="Natural-language or Boolean keywords for visible People search.",
            ),
        ]
        | None
    ) = None
    filters: PeopleSearchFilters = Field(
        default_factory=PeopleSearchFilters,
        description="Optional structured filters from LinkedIn's visible People search.",
    )

    @model_validator(mode="after")
    def require_a_search_criterion(self) -> PeopleSearchInput:
        if not self.query and not self.filters.has_constraints():
            raise ValueError("People search requires query or at least one filter")
        return self


class PersonSummary(StrictModel):
    profile_slug: ProfileSlug
    profile_url: HttpUrl
    name: Annotated[str, Field(min_length=1, max_length=500)]
    headline: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    connection_degree: PersonConnectionDegree | None = None
    mutual_connections_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]


class PeopleSearchOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    people: tuple[PersonSummary, ...]
    coverage: PeopleSearchCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]


class ConnectionsSearchFilters(PeopleSearchFilterBase):
    """People filters for established connections; first degree is server-enforced."""

    def as_people_search_filters(self) -> PeopleSearchFilters:
        return PeopleSearchFilters.model_validate(
            {
                **self.model_dump(mode="python"),
                "connection_degrees": (PeopleSearchConnectionDegree.FIRST,),
            }
        )


class ConnectionsSearchInput(PaginatedInput):
    """Search established first-degree connections through LinkedIn People search."""

    context_id: Identifier
    request_id: Identifier
    query: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=500,
                description="Natural-language or Boolean keywords for connection search.",
            ),
        ]
        | None
    ) = None
    filters: ConnectionsSearchFilters = Field(
        default_factory=ConnectionsSearchFilters,
        description=(
            "Optional visible People filters. First-degree connection filtering is always "
            "enforced by the server and cannot be overridden."
        ),
    )

    @model_validator(mode="after")
    def require_a_search_criterion(self) -> ConnectionsSearchInput:
        if not self.query and not self.filters.has_constraints():
            raise ValueError("Connection search requires query or at least one filter")
        return self

    def as_people_search_input(self) -> PeopleSearchInput:
        return PeopleSearchInput(
            context_id=self.context_id,
            request_id=self.request_id,
            query=self.query,
            filters=self.filters.as_people_search_filters(),
            page_size=self.page_size,
        )


class ConnectionsSearchOutput(PeopleSearchOutput):
    """People-shaped results from LinkedIn's broad Connections search entry point."""
