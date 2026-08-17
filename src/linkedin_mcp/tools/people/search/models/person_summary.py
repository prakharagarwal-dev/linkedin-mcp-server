from __future__ import annotations

from typing import Annotated

from pydantic import Field, HttpUrl

from linkedin_mcp.tools._shared.models import (
    ProfileSlug,
    StrictModel,
)
from linkedin_mcp.tools.people.models.person_connection_degree import PersonConnectionDegree


class PersonSummary(StrictModel):
    profile_slug: ProfileSlug
    profile_url: HttpUrl
    name: Annotated[str, Field(min_length=1, max_length=500)]
    headline: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    connection_degree: PersonConnectionDegree | None = None
    mutual_connections_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]
