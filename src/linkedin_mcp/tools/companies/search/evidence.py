"""Evidence validation for `linkedin.companies.search`."""

from linkedin_mcp.tools._shared.models import SourceReference, SourceType
from linkedin_mcp.tools._shared.source import source_reference, verify_visible_items
from linkedin_mcp.tools.companies.search.models import CompanySearchCoverage, CompanySummary


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
