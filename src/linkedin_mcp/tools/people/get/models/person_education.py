from __future__ import annotations

from typing import Annotated

from pydantic import Field, HttpUrl

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)


class PersonEducation(StrictModel):
    school: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    school_url: HttpUrl | None = None
    degree: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    field_of_study: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    date_range: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    description: Annotated[str, Field(min_length=1)] | None = None
    source_url: HttpUrl
    visible_text: Annotated[str, Field(min_length=1)]
