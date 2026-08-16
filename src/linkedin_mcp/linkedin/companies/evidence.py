"""Evidence validation for LinkedIn company results."""

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.linkedin.common import SourceReference, SourceType
from linkedin_mcp.linkedin.companies.models import (
    CompanyProfileObservation,
    CompanyProfilePageCapture,
    CompanySearchCoverage,
    CompanySummary,
)
from linkedin_mcp.linkedin.source import source_reference, verify_visible_items


def source_from_company_search(
    *,
    source_url: str,
    captured_text: str,
    companies: tuple[CompanySummary, ...],
    coverage: CompanySearchCoverage,
) -> SourceReference:
    verify_visible_items(
        captured_text,
        ((company.company_slug, company.visible_text) for company in companies),
        item_kind="company",
    )
    return source_reference(
        source_type=SourceType.COMPANY_SEARCH,
        source_url=source_url,
        captured_at=coverage.captured_at,
        captured_text=captured_text,
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
