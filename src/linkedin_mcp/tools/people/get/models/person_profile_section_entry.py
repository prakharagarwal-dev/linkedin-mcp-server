from __future__ import annotations

from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)
from linkedin_mcp.tools.people.get.models.person_profile_link import PersonProfileLink


class PersonProfileSectionEntry(StrictModel):
    title: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    subtitle: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    visible_text: Annotated[str, Field(min_length=1)]
    links: tuple[PersonProfileLink, ...] = ()
