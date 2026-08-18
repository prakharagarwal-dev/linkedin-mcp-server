from __future__ import annotations

from typing import Annotated

from pydantic import Field, HttpUrl

from linkedin_mcp.tools._shared.models import (
    ProfileSlug,
    StrictModel,
)


class JobHiringTeamMember(StrictModel):
    profile_slug: ProfileSlug
    profile_url: HttpUrl
    name: Annotated[str, Field(min_length=1, max_length=500)]
    headline: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    connection_degree_text: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    role_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    mutual_connections_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]
