from __future__ import annotations

from typing import Annotated

from pydantic import Field, HttpUrl, StringConstraints

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)
from linkedin_mcp.tools.people.get.models.person_profile_section_entry import (
    PersonProfileSectionEntry,
)


class PersonProfileSection(StrictModel):
    key: Annotated[
        str,
        StringConstraints(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$"),
    ]
    heading: Annotated[str, Field(min_length=1, max_length=500)]
    source_url: HttpUrl
    visible_text: Annotated[str, Field(min_length=1)]
    entries: tuple[PersonProfileSectionEntry, ...] = ()
