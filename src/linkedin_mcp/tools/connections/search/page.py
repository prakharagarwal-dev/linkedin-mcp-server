"""Visible LinkedIn page implementation for `linkedin.connections.search`."""

from __future__ import annotations

from linkedin_mcp.tools.connections.search.models import (
    ConnectionsSearchInput,
    PeopleSearchCoverage,
    PersonSummary,
)
from linkedin_mcp.tools.people.search.models import PeopleSearchInput as ProviderSearchInput
from linkedin_mcp.tools.people.search.page import PeopleSearchPage
from linkedin_mcp.ui import LinkedInPlaywright


class ConnectionsSearchPage:
    """Run the first-degree-only connection search on LinkedIn's People surface."""

    def __init__(self, playwright: LinkedInPlaywright, *, max_pages: int) -> None:
        self._people = PeopleSearchPage(playwright, max_pages=max_pages)

    async def collect(
        self,
        request: ConnectionsSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[PersonSummary, ...], PeopleSearchCoverage, str, str]:
        provider_request = ProviderSearchInput.model_validate(
            request.as_people_search_input().model_dump(mode="python")
        )
        people, coverage, captured_text, source_url = await self._people.collect(
            provider_request,
            result_limit=result_limit,
        )
        return (
            tuple(PersonSummary.model_validate(person.model_dump()) for person in people),
            PeopleSearchCoverage.model_validate(coverage.model_dump()),
            captured_text,
            source_url,
        )
