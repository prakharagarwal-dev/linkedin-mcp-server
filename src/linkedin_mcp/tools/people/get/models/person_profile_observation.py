from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field, HttpUrl

from linkedin_mcp.tools._shared.models import (
    ProfileSlug,
    StrictModel,
)
from linkedin_mcp.tools.people.get.models.person_education import PersonEducation
from linkedin_mcp.tools.people.get.models.person_experience import PersonExperience
from linkedin_mcp.tools.people.get.models.person_profile_coverage import PersonProfileCoverage
from linkedin_mcp.tools.people.get.models.person_profile_evidence import PersonProfileEvidence
from linkedin_mcp.tools.people.get.models.person_profile_section import PersonProfileSection
from linkedin_mcp.tools.people.models.person_connection_degree import PersonConnectionDegree


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
