from __future__ import annotations

from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools._shared.models import (
    ProfileSlug,
    StrictModel,
)


class EventSpeakerInput(StrictModel):
    profile_slug: ProfileSlug
    display_name: Annotated[str, Field(min_length=1, max_length=500)]
