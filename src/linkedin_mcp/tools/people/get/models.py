"""Models owned by `linkedin.people.get`."""

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


Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=200, pattern="^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]


ProfileSlug = Annotated[
    str, StringConstraints(min_length=3, max_length=200, pattern=PROFILE_SLUG_PATTERN)
]


class SourceType(StrEnum):
    MEMBER_PROFILE = "linkedin_member_profile"


class SourceReference(StrictModel):
    source_id: Identifier
    source_type: SourceType
    source_url: HttpUrl
    captured_at: datetime


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


class PersonEducation(StrictModel):
    school: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    school_url: HttpUrl | None = None
    degree: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    field_of_study: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    date_range: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    description: Annotated[str, Field(min_length=1)] | None = None
    source_url: HttpUrl
    visible_text: Annotated[str, Field(min_length=1)]


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


class PersonProfileEvidence(StrictModel):
    field: Annotated[str, Field(min_length=1, max_length=100)]
    quote: Annotated[str, Field(min_length=1)]
    source_url: HttpUrl


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


class PersonProfilePageCapture(StrictModel):
    source_url: HttpUrl
    page_kind: Literal["profile", "section"]
    section_heading: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    captured_text: Annotated[str, Field(min_length=1)]
    captured_at: datetime
