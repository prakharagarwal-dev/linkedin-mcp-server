"""Evidence validation for `linkedin.jobs.search`."""

import hashlib
from collections.abc import Iterable
from datetime import datetime

from pydantic import HttpUrl

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools.jobs.search.models import (
    JobSearchCoverage,
    JobSummary,
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


def source_from_job_search(
    *,
    source_url: str,
    captured_text: str,
    jobs: tuple[JobSummary, ...],
    coverage: JobSearchCoverage,
) -> SourceReference:
    for job in jobs:
        for evidence in job.evidence:
            if evidence.quote not in job.visible_text or evidence.quote not in captured_text:
                raise ParserDriftError(
                    f"Evidence for job {job.job_id} field {evidence.field!r} "
                    "is not an exact captured visible-text substring."
                )
    return source_reference(
        source_type=SourceType.JOB_SEARCH,
        source_url=source_url,
        captured_at=coverage.captured_at,
        captured_text=captured_text,
    )
