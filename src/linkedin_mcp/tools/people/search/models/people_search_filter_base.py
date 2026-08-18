from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    LinkedInFacetIds,
    LinkedInFacetLabels,
    StrictModel,
)


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
