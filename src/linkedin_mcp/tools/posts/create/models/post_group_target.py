from __future__ import annotations

from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)


class PostGroupTarget(StrictModel):
    group_id: Annotated[str, Field(pattern=r"^[0-9]{3,30}$")]
    display_name: Annotated[str, Field(min_length=1, max_length=500)]
