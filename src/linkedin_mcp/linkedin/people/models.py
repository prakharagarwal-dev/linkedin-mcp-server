from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, StringConstraints, model_validator

from linkedin_mcp.linkedin.common import (
    Identifier,
    LinkedInFacetIds,
    LinkedInFacetLabels,
    PaginatedInput,
    PaginationMetadata,
    ProfileSlug,
    SourceReference,
    StopReason,
    StrictModel,
)


class PersonConnectionDegree(StrEnum):
    FIRST = "first"
    SECOND = "second"
    THIRD_OR_MORE = "third_or_more"
    OUT_OF_NETWORK = "out_of_network"


class PeopleSearchConnectionDegree(StrEnum):
    FIRST = "first"
    SECOND = "second"
    THIRD_OR_MORE = "third_or_more"


class PersonProfileSectionSelector(StrEnum):
    ALL = "all"
    OVERVIEW = "overview"
    ABOUT = "about"
    EXPERIENCE = "experience"
    EDUCATION = "education"
    LICENSES_CERTIFICATIONS = "licenses-certifications"
    PROJECTS = "projects"
    VOLUNTEERING = "volunteering"
    SKILLS = "skills"
    INTERESTS = "interests"
    FEATURED = "featured"
    COURSES = "courses"
    HONORS_AWARDS = "honors-awards"
    LANGUAGES = "languages"
    ORGANIZATIONS = "organizations"
    PUBLICATIONS = "publications"
    PATENTS = "patents"
    RECOMMENDATIONS = "recommendations"
    TEST_SCORES = "test-scores"


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


class PeopleGetInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    profile_slug: ProfileSlug
    sections: Annotated[
        tuple[PersonProfileSectionSelector, ...],
        Field(
            min_length=1,
            max_length=len(PersonProfileSectionSelector),
            description=(
                "Visible profile sections to return. 'all' preserves the complete bounded "
                "profile read and cannot be combined with another selector."
            ),
        ),
    ] = (PersonProfileSectionSelector.ALL,)

    @model_validator(mode="after")
    def validate_sections(self) -> PeopleGetInput:
        if len(set(self.sections)) != len(self.sections):
            raise ValueError("Profile section selectors must not contain duplicates")
        if PersonProfileSectionSelector.ALL in self.sections and len(self.sections) != 1:
            raise ValueError("'all' cannot be combined with another profile section")
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


class PeopleSearchOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    people: tuple[PersonSummary, ...]
    coverage: PeopleSearchCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]


class PersonProfileLink(StrictModel):
    label: Annotated[str, Field(min_length=1, max_length=1_000)]
    url: HttpUrl


class PersonProfileSectionEntry(StrictModel):
    title: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    subtitle: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]
    links: tuple[PersonProfileLink, ...] = ()


class PersonProfileSection(StrictModel):
    key: Annotated[
        str,
        StringConstraints(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$"),
    ]
    heading: Annotated[str, Field(min_length=1, max_length=500)]
    source_url: HttpUrl
    visible_text: Annotated[str, Field(min_length=1)]
    entries: tuple[PersonProfileSectionEntry, ...] = ()


class PersonExperience(StrictModel):
    title: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    organization: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    organization_url: HttpUrl | None = None
    employment_type: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    date_range: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    duration: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    description: Annotated[str, Field(min_length=1)] | None = None
    is_current: bool | None = None
    source_url: HttpUrl
    visible_text: Annotated[str, Field(min_length=1)]


class PersonEducation(StrictModel):
    school: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    school_url: HttpUrl | None = None
    degree: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    field_of_study: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    date_range: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    description: Annotated[str, Field(min_length=1)] | None = None
    source_url: HttpUrl
    visible_text: Annotated[str, Field(min_length=1)]


class PersonProfileEvidence(StrictModel):
    field: Annotated[str, Field(min_length=1, max_length=100)]
    quote: Annotated[str, Field(min_length=1)]
    source_url: HttpUrl


class PersonProfilePageCapture(StrictModel):
    source_url: HttpUrl
    page_kind: Literal["profile", "section"]
    section_heading: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    captured_text: Annotated[str, Field(min_length=1)]
    captured_at: datetime


class PersonProfileCoverage(StrictModel):
    pages_visited: Annotated[int, Field(ge=1)]
    detail_pages_discovered: Annotated[int, Field(ge=0)]
    detail_pages_visited: Annotated[int, Field(ge=0)]
    detail_page_limit: Annotated[int, Field(ge=0)]
    truncated: bool
    captured_at: datetime
    requested_sections: tuple[PersonProfileSectionSelector, ...] = (
        PersonProfileSectionSelector.ALL,
    )
    returned_sections: tuple[str, ...] = ()
    detail_sections_discovered: tuple[str, ...] = ()
    detail_sections_visited: tuple[str, ...] = ()
    unavailable_sections: tuple[PersonProfileSectionSelector, ...] = ()
    truncated_sections: tuple[str, ...] = ()


class PersonProfileObservation(StrictModel):
    profile_slug: ProfileSlug
    profile_url: HttpUrl
    name: Annotated[str, Field(min_length=1, max_length=500)]
    pronouns: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    headline: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    connection_degree: PersonConnectionDegree | None = None
    connection_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    follower_count_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    current_company_text: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    education_summary_text: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    about: Annotated[str, Field(min_length=1)] | None = None
    experiences: tuple[PersonExperience, ...] = ()
    education: tuple[PersonEducation, ...] = ()
    sections: tuple[PersonProfileSection, ...] = ()
    visible_text: Annotated[str, Field(min_length=1)]
    evidence: tuple[PersonProfileEvidence, ...]
    coverage: PersonProfileCoverage
    captured_at: datetime


class PeopleGetOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    person: PersonProfileObservation
    sources: tuple[SourceReference, ...]
