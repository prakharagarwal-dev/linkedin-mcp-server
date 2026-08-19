"""Models owned by `linkedin.jobs.search`."""

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


class JobWorkplaceType(StrEnum):
    ON_SITE = "on_site"
    REMOTE = "remote"
    HYBRID = "hybrid"


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


JobId = Annotated[str, StringConstraints(pattern="^[0-9]{5,30}$")]


LinkedInFacetId = Annotated[
    str, StringConstraints(min_length=1, max_length=64, pattern="^[A-Za-z0-9_-]+$")
]


LinkedInFacetIds = Annotated[tuple[LinkedInFacetId, ...], Field(max_length=10)]


LinkedInFacetLabel = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


LinkedInFacetLabels = Annotated[tuple[LinkedInFacetLabel, ...], Field(max_length=10)]


class SourceType(StrEnum):
    JOB_SEARCH = "linkedin_job_search"


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


class JobBenefit(StrEnum):
    MEDICAL_INSURANCE = "medical_insurance"
    VISION_INSURANCE = "vision_insurance"
    DENTAL_INSURANCE = "dental_insurance"
    RETIREMENT_401K = "retirement_401k"
    PENSION_PLAN = "pension_plan"
    PAID_MATERNITY_LEAVE = "paid_maternity_leave"
    PAID_PATERNITY_LEAVE = "paid_paternity_leave"
    COMMUTER_BENEFITS = "commuter_benefits"
    STUDENT_LOAN_ASSISTANCE = "student_loan_assistance"
    TUITION_ASSISTANCE = "tuition_assistance"
    DISABILITY_INSURANCE = "disability_insurance"


class JobCommitment(StrEnum):
    CAREER_GROWTH_AND_LEARNING = "career_growth_and_learning"
    DIVERSITY_EQUITY_AND_INCLUSION = "diversity_equity_and_inclusion"
    ENVIRONMENTAL_SUSTAINABILITY = "environmental_sustainability"
    SOCIAL_IMPACT = "social_impact"
    WORK_LIFE_BALANCE = "work_life_balance"


class JobEmploymentType(StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    TEMPORARY = "temporary"
    INTERNSHIP = "internship"
    VOLUNTEER = "volunteer"
    OTHER = "other"


class JobExperienceLevel(StrEnum):
    INTERNSHIP = "internship"
    ENTRY_LEVEL = "entry_level"
    ASSOCIATE = "associate"
    MID_SENIOR = "mid_senior"
    DIRECTOR = "director"
    EXECUTIVE = "executive"


class JobSearchSort(StrEnum):
    MOST_RELEVANT = "most_relevant"
    MOST_RECENT = "most_recent"


class JobSearchFilters(StrictModel):
    """Typed filters that map only to LinkedIn's visible Jobs search surface."""

    sort_by: JobSearchSort = Field(
        default=JobSearchSort.MOST_RELEVANT,
        description="Order results by LinkedIn relevance or visible posting recency.",
    )
    location_geo_id: (
        Annotated[
            str,
            StringConstraints(pattern=r"^[0-9]{3,30}$"),
        ]
        | None
    ) = Field(
        default=None,
        description="Optional LinkedIn numeric geography ID to disambiguate location.",
    )
    distance_miles: Literal[0, 5, 10, 25, 50, 100] | None = Field(
        default=None,
        description="Visible LinkedIn distance-radius choice for the selected geography.",
    )
    workplace_types: Annotated[tuple[JobWorkplaceType, ...], Field(max_length=3)] = Field(
        default=(),
        description="On-site, remote, and/or hybrid workplace choices.",
    )
    experience_levels: Annotated[tuple[JobExperienceLevel, ...], Field(max_length=6)] = Field(
        default=(),
        description="One or more LinkedIn experience-level choices.",
    )
    employment_types: Annotated[tuple[JobEmploymentType, ...], Field(max_length=7)] = Field(
        default=(),
        description="One or more LinkedIn employment-type choices.",
    )
    location_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten additional exact LinkedIn location facet IDs.",
    )
    location_names: LinkedInFacetLabels = Field(
        default=(),
        description="Additional visible location labels to resolve from current filter options.",
    )
    company_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact LinkedIn company facet IDs.",
    )
    company_names: LinkedInFacetLabels = Field(
        default=(),
        description="Company names to resolve through LinkedIn's visible company filter.",
    )
    industry_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact LinkedIn industry facet IDs.",
    )
    industry_names: LinkedInFacetLabels = Field(
        default=(),
        description="Industry names to resolve through LinkedIn's visible industry filter.",
    )
    job_function_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact LinkedIn job-function facet IDs.",
    )
    job_function_names: LinkedInFacetLabels = Field(
        default=(),
        description="Job-function names to resolve through LinkedIn's visible function filter.",
    )
    job_title_ids: LinkedInFacetIds = Field(
        default=(),
        description="Up to ten exact LinkedIn normalized job-title facet IDs.",
    )
    job_title_names: LinkedInFacetLabels = Field(
        default=(),
        description="Normalized job-title labels to resolve from current filter options.",
    )
    benefits: Annotated[tuple[JobBenefit, ...], Field(max_length=11)] = Field(
        default=(),
        description="One or more visible LinkedIn benefit choices.",
    )
    commitments: Annotated[tuple[JobCommitment, ...], Field(max_length=5)] = Field(
        default=(),
        description="One or more visible LinkedIn corporate-commitment choices.",
    )
    easy_apply_only: bool = Field(
        default=False,
        description="Return only jobs that use LinkedIn Easy Apply.",
    )
    has_verifications: bool = Field(
        default=False,
        description="Return only jobs carrying LinkedIn's available verification signals.",
    )
    under_10_applicants: bool = Field(
        default=False,
        description="Return only jobs shown by LinkedIn as having under ten applicants.",
    )
    in_your_network: bool = Field(
        default=False,
        description="Return only jobs at companies connected to the configured account's network.",
    )
    fair_chance_employer: bool = Field(
        default=False,
        description="Use LinkedIn's region/account-dependent Fair Chance Employer filter.",
    )

    @model_validator(mode="after")
    def reject_duplicate_values(self) -> JobSearchFilters:
        for field_name in (
            "workplace_types",
            "experience_levels",
            "employment_types",
            "location_ids",
            "location_names",
            "company_ids",
            "company_names",
            "industry_ids",
            "industry_names",
            "job_function_ids",
            "job_function_names",
            "job_title_ids",
            "job_title_names",
            "benefits",
            "commitments",
        ):
            values = getattr(self, field_name)
            normalized = tuple(
                value.casefold() if isinstance(value, str) else value for value in values
            )
            if len(set(normalized)) != len(normalized):
                raise ValueError(f"{field_name} cannot contain duplicate values")
        for ids_field, names_field in (
            ("location_ids", "location_names"),
            ("company_ids", "company_names"),
            ("industry_ids", "industry_names"),
            ("job_function_ids", "job_function_names"),
            ("job_title_ids", "job_title_names"),
        ):
            if len(getattr(self, ids_field)) + len(getattr(self, names_field)) > 10:
                raise ValueError(
                    f"{ids_field} and {names_field} can contain at most ten combined values"
                )
        return self


class JobSearchCoverage(StrictModel):
    query: str | None
    location: str | None
    freshness_hours: Literal[24, 168, 720] | None
    filters: JobSearchFilters = Field(default_factory=JobSearchFilters)
    pages_visited: Annotated[int, Field(ge=1)]
    result_count: Annotated[int, Field(ge=0)]
    max_results: Annotated[int, Field(ge=1)]
    stop_reason: StopReason
    advertised_result_count: Annotated[int, Field(ge=0)] | None = None
    advertised_result_count_is_lower_bound: bool = False
    captured_at: datetime


class JobSearchInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    query: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=300,
                description="Keywords or a LinkedIn Boolean query using quotes, AND, OR, and NOT.",
            ),
        ]
        | None
    ) = None
    location: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Visible location text such as a city, region, country, or Worldwide.",
            ),
        ]
        | None
    ) = None
    freshness_hours: Literal[24, 168, 720] | None = Field(
        default=None,
        description=(
            "LinkedIn's visible Date posted choice: 24 hours, 168 hours (past week), "
            "720 hours (past month), or null for Any time."
        ),
    )
    filters: JobSearchFilters = Field(
        default_factory=JobSearchFilters,
        description="Optional structured LinkedIn Jobs filters.",
    )

    @model_validator(mode="after")
    def validate_distance_context(self) -> JobSearchInput:
        if (
            self.filters.distance_miles is not None
            and self.location is None
            and self.filters.location_geo_id is None
        ):
            raise ValueError("distance_miles requires location or filters.location_geo_id")
        return self


class JobSummary(StrictModel):
    job_id: JobId
    job_url: HttpUrl
    title: Annotated[str, Field(min_length=1, max_length=500)]
    company_name: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    company_url: HttpUrl | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    workplace_type: JobWorkplaceType | None = None
    listed_at_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    easy_apply: bool = False
    verified: bool = False
    promoted: bool = False
    insights: tuple[Annotated[str, Field(min_length=1, max_length=500)], ...] = ()
    visible_text: Annotated[str, Field(min_length=1)]
    evidence: tuple[EvidenceField, ...] = ()


class JobSearchOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    jobs: tuple[JobSummary, ...]
    coverage: JobSearchCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]
