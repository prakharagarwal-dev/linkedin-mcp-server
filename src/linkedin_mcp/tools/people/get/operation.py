"""Application operation for `linkedin.people.get`."""

from __future__ import annotations

from typing import Protocol

from linkedin_mcp.tools._shared.execution import OperationSupport
from linkedin_mcp.tools.people.get.evidence import sources_from_person_profile
from linkedin_mcp.tools.people.get.models.people_get_input import PeopleGetInput
from linkedin_mcp.tools.people.get.models.people_get_output import PeopleGetOutput
from linkedin_mcp.tools.people.get.models.person_profile_observation import PersonProfileObservation
from linkedin_mcp.tools.people.get.models.person_profile_page_capture import (
    PersonProfilePageCapture,
)


class PersonProfileProvider(Protocol):
    async def read(
        self,
        request: PeopleGetInput,
    ) -> tuple[PersonProfileObservation, tuple[PersonProfilePageCapture, ...]]: ...


class GetPersonOperation(OperationSupport):
    _person_profile: PersonProfileProvider

    async def get_person(self, request: PeopleGetInput) -> PeopleGetOutput:
        person, captures = await self._person_profile.read(request)
        sources = sources_from_person_profile(person, captures)
        return PeopleGetOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            person=person,
            sources=sources,
        )
