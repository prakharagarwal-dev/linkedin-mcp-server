"""Evidence construction for `linkedin.messaging.send`."""

import hashlib

from pydantic import HttpUrl

from linkedin_mcp.tools.messaging.send.models import (
    ActionPageResult,
    SourceReference,
    SourceType,
)


def source_from_action_execution(
    page_result: ActionPageResult,
    *,
    execution_id: str,
) -> SourceReference:
    fields = (
        SourceType.ACTION_EXECUTION.value,
        str(page_result.source_url),
        page_result.captured_at.isoformat(),
        page_result.captured_text,
        execution_id,
    )
    digest = hashlib.sha256("\x1f".join(fields).encode()).hexdigest()[:24]
    return SourceReference(
        source_id=f"{SourceType.ACTION_EXECUTION.value}:{digest}",
        source_type=SourceType.ACTION_EXECUTION,
        source_url=HttpUrl(str(page_result.source_url)),
        captured_at=page_result.captured_at,
    )
