"""Evidence validation for LinkedIn job results."""

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.linkedin.common import SourceReference, SourceType
from linkedin_mcp.linkedin.jobs.models import (
    JobDetailObservation,
    JobSearchCoverage,
    JobSummary,
)
from linkedin_mcp.linkedin.source import source_reference


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


def source_from_job_detail(observation: JobDetailObservation) -> SourceReference:
    for evidence in observation.evidence:
        if evidence.quote not in observation.visible_text:
            raise ParserDriftError(
                f"Evidence for field {evidence.field!r} is not an exact visible-text substring."
            )
    return source_reference(
        source_type=SourceType.JOB,
        source_url=str(observation.job_url),
        captured_at=observation.captured_at,
        captured_text=observation.visible_text,
    )
