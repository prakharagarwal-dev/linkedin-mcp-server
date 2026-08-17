"""Application operation for `linkedin.invitations.list`."""

from __future__ import annotations

from collections.abc import (
    Awaitable,
    Callable,
)
from typing import Protocol

from linkedin_mcp.app.pagination import (
    PaginationLease,
    select_page,
)
from linkedin_mcp.tools._shared.execution import OperationSupport
from linkedin_mcp.tools._shared.models import (
    CapabilityName,
    StopReason,
)
from linkedin_mcp.tools.invitations.list.evidence import source_from_invitation_list
from linkedin_mcp.tools.invitations.list.models.invitation_list_coverage import (
    InvitationListCoverage,
)
from linkedin_mcp.tools.invitations.list.models.invitation_list_input import InvitationListInput
from linkedin_mcp.tools.invitations.list.models.invitation_list_output import InvitationListOutput
from linkedin_mcp.tools.invitations.list.models.invitation_summary import InvitationSummary

ProgressReporter = Callable[[int, int, str], Awaitable[None]]


class InvitationListProvider(Protocol):
    async def collect(
        self,
        request: InvitationListInput,
        *,
        result_limit: int | None = None,
        progress: ProgressReporter | None = None,
    ) -> tuple[tuple[InvitationSummary, ...], InvitationListCoverage, str, str]: ...


class ListInvitationsOperation(OperationSupport):
    _invitation_list: InvitationListProvider

    async def list_invitations(
        self,
        request: InvitationListInput,
        progress: ProgressReporter | None = None,
    ) -> InvitationListOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.INVITATIONS_LIST, request)
            invitations, coverage, captured_text, source_url = await self._invitation_list.collect(
                request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
                progress=progress,
            )
            page = select_page(
                invitations,
                key=lambda invitation: invitation.invitation_ref,
                seen_keys=lease.seen_keys,
                page_size=self._pagination.page_capacity(lease, request.page_size),
            )
            provider_has_more = page.has_lookahead or coverage.stop_reason in {
                StopReason.RESULT_LIMIT,
                StopReason.SAFETY_BOUND,
            }
            page_stop_reason = (
                StopReason.RESULT_LIMIT
                if page.has_lookahead or coverage.stop_reason is StopReason.RESULT_LIMIT
                else coverage.stop_reason
            )
            page_coverage = coverage.model_copy(
                update={
                    "result_count": len(page.items),
                    "max_results": request.page_size,
                    "stop_reason": page_stop_reason,
                }
            )
            advertised_label = captured_text.split("\n\n", maxsplit=1)[0].strip()
            page_text = "\n\n".join((advertised_label, *(item.visible_text for item in page.items)))
            source = source_from_invitation_list(
                source_url=source_url,
                captured_text=page_text,
                invitations=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
            )
            return InvitationListOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                invitations=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)
