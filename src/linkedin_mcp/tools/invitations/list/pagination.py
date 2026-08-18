"""Pagination and output construction for `linkedin.invitations.list`."""

from __future__ import annotations

from collections.abc import (
    Awaitable,
    Callable,
)

from linkedin_mcp.pagination import (
    PaginationManager,
    select_page,
)
from linkedin_mcp.tools._shared.models import (
    CapabilityName,
    StopReason,
)
from linkedin_mcp.tools.invitations.list.evidence import source_from_invitation_list
from linkedin_mcp.tools.invitations.list.models.invitation_list_input import InvitationListInput
from linkedin_mcp.tools.invitations.list.models.invitation_list_output import InvitationListOutput
from linkedin_mcp.tools.invitations.list.page import InvitationListPage

ProgressReporter = Callable[[int, int, str], Awaitable[None]]


async def execute(
    request: InvitationListInput,
    *,
    page: InvitationListPage,
    pagination: PaginationManager,
    account_id: str,
    progress: ProgressReporter | None = None,
) -> InvitationListOutput:
    state = await pagination.start(
        account_id=account_id,
        capability_name=CapabilityName.INVITATIONS_LIST,
        request=request,
    )
    invitations, coverage, captured_text, source_url = await page.collect(
        request,
        result_limit=pagination.traversal_limit(state, request.page_size),
        progress=progress,
    )
    selected = select_page(
        invitations,
        key=lambda invitation: invitation.invitation_ref,
        seen_keys=state.seen_keys,
        page_size=pagination.page_capacity(state, request.page_size),
    )
    provider_has_more = selected.has_lookahead or coverage.stop_reason in {
        StopReason.RESULT_LIMIT,
        StopReason.SAFETY_BOUND,
    }
    page_stop_reason = (
        StopReason.RESULT_LIMIT
        if selected.has_lookahead or coverage.stop_reason is StopReason.RESULT_LIMIT
        else coverage.stop_reason
    )
    page_coverage = coverage.model_copy(
        update={
            "result_count": len(selected.items),
            "max_results": request.page_size,
            "stop_reason": page_stop_reason,
        }
    )
    advertised_label = captured_text.split("\n\n", maxsplit=1)[0].strip()
    page_text = "\n\n".join((advertised_label, *(item.visible_text for item in selected.items)))
    source = source_from_invitation_list(
        source_url=source_url,
        captured_text=page_text,
        invitations=selected.items,
        coverage=page_coverage,
    )
    metadata = await pagination.finish(
        state,
        page_size=request.page_size,
        returned_keys=selected.keys,
        provider_has_more=provider_has_more,
    )
    return InvitationListOutput(
        context_id=request.context_id,
        request_id=request.request_id,
        invitations=selected.items,
        coverage=page_coverage,
        pagination=metadata,
        sources=(source,),
    )
