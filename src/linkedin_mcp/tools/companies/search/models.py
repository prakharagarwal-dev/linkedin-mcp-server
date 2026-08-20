"""Models owned by `linkedin.companies.search`."""

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


CompanySlug = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=200, pattern="^[A-Za-z0-9](?:[A-Za-z0-9-]{0,198}[A-Za-z0-9])?$"
    ),
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
    COMPANY_SEARCH = "linkedin_company_search"


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


class CompanySize(StrEnum):
    EMPLOYEES_1_10 = "1-10"
    EMPLOYEES_11_50 = "11-50"
    EMPLOYEES_51_200 = "51-200"
    EMPLOYEES_201_500 = "201-500"
    EMPLOYEES_501_1000 = "501-1000"
    EMPLOYEES_1001_5000 = "1001-5000"
    EMPLOYEES_5001_10000 = "5001-10000"
    EMPLOYEES_10001_PLUS = "10001+"


class CompanySearchFilters(StrictModel):
    location_ids: LinkedInFacetIds = Field(
        default=(),
        description="Stable LinkedIn headquarters-location facet IDs.",
    )
    location_names: LinkedInFacetLabels = Field(
        default=(),
        description=(
            "Exact visible headquarters-location labels resolved through LinkedIn's "
            "Company-search filter UI."
        ),
    )
    industry_ids: LinkedInFacetIds = Field(
        default=(),
        description="Stable LinkedIn industry facet IDs.",
    )
    industry_names: LinkedInFacetLabels = Field(
        default=(),
        description=(
            "Exact visible industry labels resolved through LinkedIn's Company-search filter UI."
        ),
    )
    company_sizes: Annotated[
        tuple[CompanySize, ...],
        Field(
            max_length=len(CompanySize),
            description="Any combination of LinkedIn's eight visible company-size buckets.",
        ),
    ] = ()
    has_job_listings: bool = Field(
        default=False,
        description=("Require LinkedIn's visible 'Job listings on LinkedIn: Yes' Company filter."),
    )
    has_first_degree_connections: bool = Field(
        default=False,
        description="Require LinkedIn's visible 'Connections: 1st' Company filter.",
    )

    @model_validator(mode="after")
    def validate_filters(self) -> CompanySearchFilters:
        for label, values in (
            ("location", (*self.location_ids, *self.location_names)),
            ("industry", (*self.industry_ids, *self.industry_names)),
            ("company size", self.company_sizes),
        ):
            normalized = tuple(value.casefold() for value in values)
            if len(set(normalized)) != len(normalized):
                raise ValueError(f"{label} filters must not contain duplicates")
        if len(self.location_ids) + len(self.location_names) > 10:
            raise ValueError("At most 10 combined location IDs and names are allowed")
        if len(self.industry_ids) + len(self.industry_names) > 10:
            raise ValueError("At most 10 combined industry IDs and names are allowed")
        return self

    def has_constraints(self) -> bool:
        return any(
            (
                self.location_ids,
                self.location_names,
                self.industry_ids,
                self.industry_names,
                self.company_sizes,
                self.has_job_listings,
                self.has_first_degree_connections,
            )
        )


class CompanySearchCoverage(StrictModel):
    query: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    filters: CompanySearchFilters = Field(default_factory=CompanySearchFilters)
    pages_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    captured_at: datetime


class CompanySearchInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    query: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=500,
                description="Natural-language or Boolean keywords for visible Company search.",
            ),
        ]
        | None
    ) = None
    filters: CompanySearchFilters = Field(default_factory=CompanySearchFilters)

    @model_validator(mode="after")
    def require_a_search_criterion(self) -> CompanySearchInput:
        if not self.query and not self.filters.has_constraints():
            raise ValueError("Company search requires query or at least one filter")
        return self


class CompanySummary(StrictModel):
    company_slug: CompanySlug
    company_url: HttpUrl
    name: Annotated[str, Field(min_length=1, max_length=500)]
    tagline: Annotated[str, Field(min_length=1, max_length=2_000)] | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    industry: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    follower_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    associated_member_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]


class CompanySearchOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    companies: tuple[CompanySummary, ...]
    coverage: CompanySearchCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]
