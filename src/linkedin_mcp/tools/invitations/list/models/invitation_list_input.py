"""Models for `linkedin_mcp.tools.invitations.list`."""

from __future__ import annotations

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import Identifier, PaginatedInput
from linkedin_mcp.tools.invitations.list.models.invitation_direction import InvitationDirection
from linkedin_mcp.tools.invitations.list.models.invitation_filter import InvitationFilter


class InvitationListInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    direction: InvitationDirection = InvitationDirection.RECEIVED
    invitation_filter: InvitationFilter | None = Field(
        default=None,
        description=(
            "Current visible LinkedIn invitation filter. Omit for the deduplicated union of "
            "every Received view or for Sent People."
        ),
    )

    @model_validator(mode="after")
    def validate_direction_filter(self) -> InvitationListInput:
        selected = self.resolved_filter
        if self.direction is InvitationDirection.SENT and selected is not InvitationFilter.PEOPLE:
            raise ValueError("Sent invitations support only the visible People filter")
        if self.direction is InvitationDirection.RECEIVED and selected is InvitationFilter.PEOPLE:
            raise ValueError("The People filter applies only to sent invitations")
        return self

    @property
    def resolved_filter(self) -> InvitationFilter:
        if self.invitation_filter is not None:
            return self.invitation_filter
        if self.direction is InvitationDirection.SENT:
            return InvitationFilter.PEOPLE
        return InvitationFilter.ALL
