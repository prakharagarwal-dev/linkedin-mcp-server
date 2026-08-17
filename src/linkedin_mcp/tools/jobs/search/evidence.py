"""Evidence validation for `linkedin.jobs.search`."""

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools._shared.models import SourceReference, SourceType
from linkedin_mcp.tools._shared.source import source_reference
from linkedin_mcp.tools.jobs.search.models import JobSearchCoverage, JobSummary


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
