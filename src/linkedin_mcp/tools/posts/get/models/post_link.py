from __future__ import annotations

from typing import Annotated

from pydantic import Field, HttpUrl

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)


class PostLink(StrictModel):
    label: Annotated[str, Field(min_length=1, max_length=2_000)]
    url: HttpUrl
