"""Evidence validation for `linkedin.jobs.get`."""

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools._shared.models import SourceReference, SourceType
from linkedin_mcp.tools._shared.source import source_reference
from linkedin_mcp.tools.jobs.get.models.job_detail_observation import JobDetailObservation


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
