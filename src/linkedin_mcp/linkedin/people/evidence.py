"""Evidence validation for LinkedIn people results."""

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.linkedin.common import SourceReference, SourceType
from linkedin_mcp.linkedin.people.models import (
    PeopleSearchCoverage,
    PersonProfileObservation,
    PersonProfilePageCapture,
    PersonSummary,
)
from linkedin_mcp.linkedin.source import source_reference, verify_visible_items


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


def sources_from_person_profile(
    observation: PersonProfileObservation,
    captures: tuple[PersonProfilePageCapture, ...],
) -> tuple[SourceReference, ...]:
    if not captures:
        raise ParserDriftError("A member profile must retain at least one visible source.")
    captured_by_url = {str(capture.source_url): capture.captured_text for capture in captures}
    for evidence in observation.evidence:
        captured_text = captured_by_url.get(str(evidence.source_url))
        if captured_text is None or evidence.quote not in captured_text:
            raise ParserDriftError(
                f"Evidence for field {evidence.field!r} is not an exact source substring."
            )

    return tuple(
        source_reference(
            source_type=SourceType.MEMBER_PROFILE,
            source_url=str(capture.source_url),
            captured_at=capture.captured_at,
            captured_text=capture.captured_text,
        )
        for capture in captures
    )
