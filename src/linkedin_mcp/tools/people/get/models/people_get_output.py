from __future__ import annotations

from typing import Literal

from linkedin_mcp.tools._shared.models import (
    Identifier,
    SourceReference,
    StrictModel,
)
from linkedin_mcp.tools.people.get.models.person_profile_observation import PersonProfileObservation


class PeopleGetOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    person: PersonProfileObservation
    sources: tuple[SourceReference, ...]
