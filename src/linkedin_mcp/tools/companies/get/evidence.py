"""Evidence validation for `linkedin.companies.get`."""

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools._shared.models import SourceReference, SourceType
from linkedin_mcp.tools._shared.source import source_reference
from linkedin_mcp.tools.companies.get.models.company_profile_observation import (
    CompanyProfileObservation,
)
from linkedin_mcp.tools.companies.get.models.company_profile_page_capture import (
    CompanyProfilePageCapture,
)


def sources_from_company_profile(
    observation: CompanyProfileObservation,
    captures: tuple[CompanyProfilePageCapture, ...],
) -> tuple[SourceReference, ...]:
    if tuple(capture.page_kind for capture in captures) != ("overview", "about"):
        raise ParserDriftError(
            "A company profile must retain exactly its overview and About sources."
        )
    captured_by_url = {str(capture.source_url): capture.captured_text for capture in captures}
    for evidence in observation.evidence:
        captured_text = captured_by_url.get(str(evidence.source_url))
        if captured_text is None or evidence.quote not in captured_text:
            raise ParserDriftError(
                f"Evidence for field {evidence.field!r} is not an exact company-source substring."
            )

    return tuple(
        source_reference(
            source_type=SourceType.COMPANY_PROFILE,
            source_url=str(capture.source_url),
            captured_at=capture.captured_at,
            captured_text=capture.captured_text,
        )
        for capture in captures
    )
