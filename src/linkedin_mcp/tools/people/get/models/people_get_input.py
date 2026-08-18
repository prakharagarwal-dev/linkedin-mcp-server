from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    Identifier,
    ProfileSlug,
    StrictModel,
)
from linkedin_mcp.tools.people.get.models.person_profile_section_selector import (
    PersonProfileSectionSelector,
)


class PeopleGetInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    profile_slug: ProfileSlug
    sections: Annotated[
        tuple[PersonProfileSectionSelector, ...],
        Field(
            min_length=1,
            max_length=len(PersonProfileSectionSelector),
            description=(
                "Visible profile sections to return. 'all' preserves the complete bounded "
                "profile read and cannot be combined with another selector."
            ),
        ),
    ] = (PersonProfileSectionSelector.ALL,)

    @model_validator(mode="after")
    def validate_sections(self) -> PeopleGetInput:
        if len(set(self.sections)) != len(self.sections):
            raise ValueError("Profile section selectors must not contain duplicates")
        if PersonProfileSectionSelector.ALL in self.sections and len(self.sections) != 1:
            raise ValueError("'all' cannot be combined with another profile section")
        return self
