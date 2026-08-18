from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    LinkedInFacetIds,
    LinkedInFacetLabels,
    StrictModel,
)
from linkedin_mcp.tools.posts.search.models.post_search_content_type import PostSearchContentType
from linkedin_mcp.tools.posts.search.models.post_search_date import PostSearchDate
from linkedin_mcp.tools.posts.search.models.post_search_posted_by import PostSearchPostedBy
from linkedin_mcp.tools.posts.search.models.post_search_sort import PostSearchSort


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
