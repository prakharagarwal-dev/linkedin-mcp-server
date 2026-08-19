"""Evidence validation for `linkedin.companies.search`."""

import hashlib
from collections.abc import Iterable
from datetime import datetime

from pydantic import HttpUrl

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools.companies.search.models import (
    CompanySearchCoverage,
    CompanySummary,
    SourceReference,
    SourceType,
)


def stable_source_id(
    source_type: SourceType,
    source_url: str,
    captured_at: datetime,
    captured_text: str,
    *,
    identity: str | None = None,
) -> str:
    fields = [source_type.value, source_url, captured_at.isoformat(), captured_text]
    if identity is not None:
        fields.append(identity)
    payload = "\x1f".join(fields).encode()
    digest = hashlib.sha256(payload).hexdigest()[:24]
    return f"{source_type.value}:{digest}"


def source_reference(
    *,
    source_type: SourceType,
    source_url: str,
    captured_at: datetime,
    captured_text: str,
    identity: str | None = None,
) -> SourceReference:
    return SourceReference(
        source_id=stable_source_id(
            source_type,
            source_url,
            captured_at,
            captured_text,
            identity=identity,
        ),
        source_type=source_type,
        source_url=HttpUrl(source_url),
        captured_at=captured_at,
    )


def verify_visible_items(
    captured_text: str,
    items: Iterable[tuple[str, str]],
    *,
    item_kind: str,
) -> None:
    for reference, visible_text in items:
        if visible_text not in captured_text:
            raise ParserDriftError(
                f"Captured {item_kind} {reference!r} is not an exact source substring."
            )


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
