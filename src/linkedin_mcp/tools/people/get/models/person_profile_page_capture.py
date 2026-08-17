from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, HttpUrl

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)


class PersonProfilePageCapture(StrictModel):
    source_url: HttpUrl
    page_kind: Literal["profile", "section"]
    section_heading: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    captured_text: Annotated[str, Field(min_length=1)]
    captured_at: datetime
