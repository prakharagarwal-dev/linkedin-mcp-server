from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from linkedin_mcp.tools._shared.models import (
    LinkedInFacetIds,
    LinkedInFacetLabels,
    StrictModel,
)
from linkedin_mcp.tools.jobs.models.job_workplace_type import JobWorkplaceType
from linkedin_mcp.tools.jobs.search.models.job_benefit import JobBenefit
from linkedin_mcp.tools.jobs.search.models.job_commitment import JobCommitment
from linkedin_mcp.tools.jobs.search.models.job_employment_type import JobEmploymentType
from linkedin_mcp.tools.jobs.search.models.job_experience_level import JobExperienceLevel
from linkedin_mcp.tools.jobs.search.models.job_search_sort import JobSearchSort


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
