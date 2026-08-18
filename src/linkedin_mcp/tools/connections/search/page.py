"""Visible LinkedIn page implementation for `linkedin.connections.search`."""

from __future__ import annotations

from linkedin_mcp.tools._shared.browser import BrowserManager
from linkedin_mcp.tools.connections.search.models.connections_search_input import (
    ConnectionsSearchInput,
)
from linkedin_mcp.tools.people.search.models.people_search_coverage import PeopleSearchCoverage
from linkedin_mcp.tools.people.search.models.person_summary import PersonSummary
from linkedin_mcp.tools.people.search.page import PeopleSearchPage


class ConnectionsSearchPage:
    """Run the first-degree-only connection search on LinkedIn's People surface."""

    def __init__(self, browser: BrowserManager, *, max_pages: int) -> None:
        self._people = PeopleSearchPage(browser, max_pages=max_pages)

    async def collect(
        self,
        request: ConnectionsSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[PersonSummary, ...], PeopleSearchCoverage, str, str]:
        return await self._people.collect(
            request.as_people_search_input(),
            result_limit=result_limit,
        )
