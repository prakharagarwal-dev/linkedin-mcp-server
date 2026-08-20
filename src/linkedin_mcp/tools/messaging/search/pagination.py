"""Pagination and output construction for `linkedin.messaging.search`."""

from __future__ import annotations

from linkedin_mcp.pagination import (
    PaginationManager,
    select_page,
)
from linkedin_mcp.tools._shared.models import (
    CapabilityName,
    StopReason,
)
from linkedin_mcp.tools.messaging.search.evidence import source_from_conversation_search
from linkedin_mcp.tools.messaging.search.models.conversation_search_input import (
    ConversationSearchInput,
)
from linkedin_mcp.tools.messaging.search.models.conversation_search_output import (
    ConversationSearchOutput,
)
from linkedin_mcp.tools.messaging.search.page import ConversationSearchPage


async def execute(
    request: ConversationSearchInput,
    *,
    page: ConversationSearchPage,
    pagination: PaginationManager,
    account_id: str,
) -> ConversationSearchOutput:
    state = await pagination.start(
        account_id=account_id,
        capability_name=CapabilityName.MESSAGING_SEARCH,
        request=request,
    )
    conversations, coverage, captured_text, source_url = await page.collect(
        request,
        result_limit=pagination.traversal_limit(state, request.page_size),
    )
    selected = select_page(
        conversations,
        key=lambda conversation: conversation.conversation_id or conversation.conversation_ref,
        seen_keys=state.seen_keys,
        page_size=pagination.page_capacity(state, request.page_size),
    )
    provider_has_more = selected.has_lookahead or coverage.stop_reason in {
        StopReason.RESULT_LIMIT,
        StopReason.SAFETY_BOUND,
    }
    page_coverage = coverage.model_copy(
        update={
            "result_count": len(selected.items),
            "max_results": request.page_size,
            "stop_reason": (StopReason.RESULT_LIMIT if provider_has_more else coverage.stop_reason),
        }
    )
    source = source_from_conversation_search(
        source_url=source_url,
        captured_text=captured_text,
        conversations=selected.items,
        coverage=page_coverage,
    )
    metadata = await pagination.finish(
        state,
        page_size=request.page_size,
        returned_keys=selected.keys,
        provider_has_more=provider_has_more,
    )
    return ConversationSearchOutput(
        context_id=request.context_id,
        request_id=request.request_id,
        conversations=selected.items,
        coverage=page_coverage,
        pagination=metadata,
        sources=(source,),
    )
