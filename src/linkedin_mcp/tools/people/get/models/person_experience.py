from __future__ import annotations

from typing import Annotated

from pydantic import Field, HttpUrl

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)


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
