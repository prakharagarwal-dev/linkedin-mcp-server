"""Evidence validation for `linkedin.people.get`."""

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools._shared.models import SourceReference, SourceType
from linkedin_mcp.tools._shared.source import source_reference
from linkedin_mcp.tools.people.get.models.person_profile_observation import PersonProfileObservation
from linkedin_mcp.tools.people.get.models.person_profile_page_capture import (
    PersonProfilePageCapture,
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
