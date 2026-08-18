"""Source metadata for completed LinkedIn account-changing actions."""

from linkedin_mcp.tools._shared.actions import ActionPageResult
from linkedin_mcp.tools._shared.models import SourceReference, SourceType
from linkedin_mcp.tools._shared.source import source_reference


def source_from_action_execution(
    page_result: ActionPageResult,
    *,
    execution_id: str,
) -> SourceReference:
    return source_reference(
        source_type=SourceType.ACTION_EXECUTION,
        source_url=str(page_result.source_url),
        captured_at=page_result.captured_at,
        captured_text=page_result.captured_text,
        identity=execution_id,
    )
