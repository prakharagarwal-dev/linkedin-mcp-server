from __future__ import annotations

from typing import Literal

from linkedin_mcp.tools._shared.models import (
    Identifier,
    PaginationMetadata,
    SourceReference,
    StrictModel,
)
from linkedin_mcp.tools.messaging.search.models.conversation_search_coverage import (
    ConversationSearchCoverage,
)
from linkedin_mcp.tools.messaging.search.models.conversation_summary import ConversationSummary


class ConversationSearchOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    conversations: tuple[ConversationSummary, ...]
    coverage: ConversationSearchCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]
