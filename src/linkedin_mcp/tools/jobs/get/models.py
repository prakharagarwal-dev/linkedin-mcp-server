"""Models owned by `linkedin.jobs.get`."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints

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


class JobWorkplaceType(StrEnum):
    ON_SITE = "on_site"
    REMOTE = "remote"
    HYBRID = "hybrid"


Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=200, pattern="^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]


JobId = Annotated[str, StringConstraints(pattern="^[0-9]{5,30}$")]


ProfileSlug = Annotated[
    str, StringConstraints(min_length=3, max_length=200, pattern=PROFILE_SLUG_PATTERN)
]


class SourceType(StrEnum):
    JOB = "linkedin_job"


class SourceReference(StrictModel):
    source_id: Identifier
    source_type: SourceType
    source_url: HttpUrl
    captured_at: datetime


class EvidenceField(StrictModel):
    field: Annotated[str, Field(min_length=1, max_length=100)]
    quote: Annotated[str, Field(min_length=1)]


class JobApplyMethod(StrEnum):
    EASY_APPLY = "easy_apply"
    EXTERNAL = "external"
    UNAVAILABLE = "unavailable"


class JobDetailInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    job_id: JobId


class JobHiringTeamMember(StrictModel):
    profile_slug: ProfileSlug
    profile_url: HttpUrl
    name: Annotated[str, Field(min_length=1, max_length=500)]
    headline: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    connection_degree_text: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    role_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    mutual_connections_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]


class JobDetailObservation(StrictModel):
    job_id: JobId
    job_url: HttpUrl
    title: Annotated[str, Field(min_length=1, max_length=500)]
    company_name: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    company_url: HttpUrl | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    workplace_type: JobWorkplaceType | None = None
    employment_type: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    listed_at_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    applicant_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    description_text: Annotated[str, Field(min_length=1)] | None = None
    apply_method: JobApplyMethod = JobApplyMethod.UNAVAILABLE
    easy_apply: bool | None = None
    promoted: bool = False
    insights: tuple[Annotated[str, Field(min_length=1, max_length=500)], ...] = ()
    hiring_team: tuple[JobHiringTeamMember, ...] = ()
    visible_text: Annotated[str, Field(min_length=1)]
    evidence: tuple[EvidenceField, ...]
    captured_at: datetime


class JobDetailOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    job: JobDetailObservation
    sources: tuple[SourceReference, ...]
