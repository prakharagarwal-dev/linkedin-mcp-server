"""Models for `linkedin_mcp.tools.invitations.list`."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from linkedin_mcp.tools._shared.models import (
    Identifier,
    PaginationMetadata,
    SourceReference,
    StopReason,
    StrictModel,
)
from linkedin_mcp.tools.invitations.list.models.invitation_list_coverage import (
    InvitationListCoverage,
)
from linkedin_mcp.tools.invitations.list.models.invitation_summary import InvitationSummary


class InvitationListOutput(StrictModel):
    status: Literal["completed"] = "completed"
    context_id: Identifier
    request_id: Identifier
    invitations: tuple[InvitationSummary, ...]
    coverage: InvitationListCoverage
    pagination: PaginationMetadata
    sources: tuple[SourceReference, ...]

    @model_validator(mode="after")
    def validate_live_page(self) -> InvitationListOutput:
        returned = len(self.invitations)
        if self.coverage.result_count != returned or self.pagination.returned_count != returned:
            raise ValueError("Invitation page counts must match the returned invitations")
        if self.pagination.consistency != "live_deduplicated":
            raise ValueError("Invitation pagination must identify live-deduplicated consistency")
        if self.pagination.has_more and self.coverage.stop_reason not in {
            StopReason.RESULT_LIMIT,
            StopReason.SAFETY_BOUND,
        }:
            raise ValueError("Invitation continuation requires an honest non-terminal stop reason")
        if (
            not self.pagination.has_more
            and not self.pagination.truncated
            and self.coverage.stop_reason is not StopReason.VISIBLE_PAGE_COMPLETE
        ):
            raise ValueError("A complete invitation scan requires reconciled terminal coverage")
        references = [item.invitation_ref for item in self.invitations]
        if len(references) != len(set(references)):
            raise ValueError("Invitation pages cannot contain duplicate references")
        if any(item.direction is not self.coverage.direction for item in self.invitations):
            raise ValueError("Invitation page items must match the selected direction")
        return self
