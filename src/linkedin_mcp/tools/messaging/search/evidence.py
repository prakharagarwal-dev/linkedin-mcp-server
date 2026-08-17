"""Evidence validation for `linkedin.messaging.search`."""

from linkedin_mcp.tools._shared.models import SourceReference, SourceType
from linkedin_mcp.tools._shared.source import source_reference, verify_visible_items
from linkedin_mcp.tools.messaging.search.models import (
    ConversationSearchCoverage,
    ConversationSummary,
)


def source_from_conversation_search(
    *,
    source_url: str,
    captured_text: str,
    conversations: tuple[ConversationSummary, ...],
    coverage: ConversationSearchCoverage,
) -> SourceReference:
    verify_visible_items(
        captured_text,
        (
            (conversation.conversation_ref, conversation.visible_text)
            for conversation in conversations
        ),
        item_kind="conversation",
    )
    return source_reference(
        source_type=SourceType.MESSAGING_INBOX,
        source_url=source_url,
        captured_at=coverage.captured_at,
        captured_text=captured_text,
    )
