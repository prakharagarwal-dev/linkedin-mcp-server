"""Evidence validation for `linkedin.people.search`."""

from linkedin_mcp.tools._shared.models import SourceReference, SourceType
from linkedin_mcp.tools._shared.source import source_reference, verify_visible_items
from linkedin_mcp.tools.people.search.models.people_search_coverage import PeopleSearchCoverage
from linkedin_mcp.tools.people.search.models.person_summary import PersonSummary


def source_from_people_search(
    *,
    source_url: str,
    captured_text: str,
    people: tuple[PersonSummary, ...],
    coverage: PeopleSearchCoverage,
) -> SourceReference:
    verify_visible_items(
        captured_text,
        ((person.profile_slug, person.visible_text) for person in people),
        item_kind="person",
    )
    return source_reference(
        source_type=SourceType.PEOPLE_SEARCH,
        source_url=source_url,
        captured_at=coverage.captured_at,
        captured_text=captured_text,
    )
