from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    LinkedInFacetIds,
    LinkedInFacetLabels,
    StrictModel,
)
from linkedin_mcp.tools.companies.search.models.company_size import CompanySize


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
