from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)
from linkedin_mcp.tools.people.get.models.person_profile_section_selector import (
    PersonProfileSectionSelector,
)


class PersonProfileCoverage(StrictModel):
    pages_visited: Annotated[int, Field(ge=1)]
    detail_pages_discovered: Annotated[int, Field(ge=0)]
    detail_pages_visited: Annotated[int, Field(ge=0)]
    detail_page_limit: Annotated[int, Field(ge=0)]
    truncated: bool
    captured_at: datetime
    requested_sections: tuple[PersonProfileSectionSelector, ...] = (
        PersonProfileSectionSelector.ALL,
    )
    returned_sections: tuple[str, ...] = ()
    detail_sections_discovered: tuple[str, ...] = ()
    detail_sections_visited: tuple[str, ...] = ()
    unavailable_sections: tuple[PersonProfileSectionSelector, ...] = ()
    truncated_sections: tuple[str, ...] = ()
