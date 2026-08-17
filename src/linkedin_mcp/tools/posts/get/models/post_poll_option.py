from __future__ import annotations

from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)


class PostPollOption(StrictModel):
    text: Annotated[str, Field(min_length=1, max_length=500)]
    percentage_text: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    vote_count_text: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    selected: bool | None = None
    visible_text: Annotated[str, Field(min_length=1)]
