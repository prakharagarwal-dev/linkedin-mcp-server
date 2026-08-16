from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, model_validator

from linkedin_mcp.linkedin.common import (
    CompanySlug,
    Identifier,
    LinkedInFacetIds,
    LinkedInFacetLabels,
    PaginatedInput,
    PaginationMetadata,
    SourceReference,
    StopReason,
    StrictModel,
)


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


class CompanyGetInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    company_slug: CompanySlug


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


class CompanySearchCoverage(StrictModel):
    query: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    filters: CompanySearchFilters = Field(default_factory=CompanySearchFilters)
    pages_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    captured_at: datetime


class CompanySearchOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    companies: tuple[CompanySummary, ...]
    coverage: CompanySearchCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]


class CompanyProfileEvidence(StrictModel):
    field: Annotated[str, Field(min_length=1, max_length=100)]
    quote: Annotated[str, Field(min_length=1)]
    source_url: HttpUrl


class CompanyProfilePageCapture(StrictModel):
    source_url: HttpUrl
    page_kind: Literal["overview", "about"]
    captured_text: Annotated[str, Field(min_length=1)]
    captured_at: datetime


class CompanyProfileCoverage(StrictModel):
    pages_visited: Literal[2] = 2
    returned_sections: tuple[Literal["overview"], Literal["about"]] = (
        "overview",
        "about",
    )
    captured_at: datetime


class CompanyProfileObservation(StrictModel):
    company_slug: CompanySlug
    company_url: HttpUrl
    name: Annotated[str, Field(min_length=1, max_length=500)]
    tagline: Annotated[str, Field(min_length=1, max_length=2_000)] | None = None
    description: Annotated[str, Field(min_length=1)] | None = None
    website_url: HttpUrl | None = None
    industry: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    company_size_range: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    associated_member_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    follower_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    headquarters: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    organization_type: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    founded_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    specialties: tuple[Annotated[str, Field(min_length=1, max_length=500)], ...] = ()
    visible_text: Annotated[str, Field(min_length=1)]
    evidence: tuple[CompanyProfileEvidence, ...]
    coverage: CompanyProfileCoverage
    captured_at: datetime


class CompanyGetOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    company: CompanyProfileObservation
    sources: tuple[SourceReference, ...]
