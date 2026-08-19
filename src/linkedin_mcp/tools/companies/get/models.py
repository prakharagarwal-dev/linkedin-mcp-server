"""Models owned by `linkedin.companies.get`."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints


class StrictModel(BaseModel):
    """Base model that rejects undeclared input and normalizes strings."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
        validate_assignment=True,
    )


Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=200, pattern="^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]


CompanySlug = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=200, pattern="^[A-Za-z0-9](?:[A-Za-z0-9-]{0,198}[A-Za-z0-9])?$"
    ),
]


class SourceType(StrEnum):
    COMPANY_PROFILE = "linkedin_company_profile"


class SourceReference(StrictModel):
    source_id: Identifier
    source_type: SourceType
    source_url: HttpUrl
    captured_at: datetime


class CompanyGetInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    company_slug: CompanySlug


class CompanyProfileCoverage(StrictModel):
    pages_visited: Literal[2] = 2
    returned_sections: tuple[Literal["overview"], Literal["about"]] = (
        "overview",
        "about",
    )
    captured_at: datetime


class CompanyProfileEvidence(StrictModel):
    field: Annotated[str, Field(min_length=1, max_length=100)]
    quote: Annotated[str, Field(min_length=1)]
    source_url: HttpUrl


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


class CompanyProfilePageCapture(StrictModel):
    source_url: HttpUrl
    page_kind: Literal["overview", "about"]
    captured_text: Annotated[str, Field(min_length=1)]
    captured_at: datetime
