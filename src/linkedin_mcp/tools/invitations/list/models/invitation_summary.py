"""Models for `linkedin_mcp.tools.invitations.list`."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from linkedin_mcp.tools._shared.models import Identifier, StrictModel
from linkedin_mcp.tools.invitations.list.models.invitation_available_action import (
    InvitationAvailableAction,
)
from linkedin_mcp.tools.invitations.list.models.invitation_direction import InvitationDirection
from linkedin_mcp.tools.invitations.list.models.invitation_entity import InvitationEntity
from linkedin_mcp.tools.invitations.list.models.invitation_evidence import InvitationEvidence
from linkedin_mcp.tools.invitations.list.models.invitation_type import InvitationType


class InvitationSummary(StrictModel):
    invitation_ref: Identifier
    direction: InvitationDirection
    invitation_type: InvitationType
    primary_entity: InvitationEntity
    inviter: InvitationEntity | None = None
    headline: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None
    context: Annotated[str, Field(min_length=1, max_length=2_000)] | None = None
    note: Annotated[str, Field(min_length=1, max_length=2_000)] | None = None
    sent_or_received_at_text: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    relationship_context: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    available_actions: tuple[InvitationAvailableAction, ...]
    visible_text: Annotated[str, Field(min_length=1)]
    evidence: tuple[InvitationEvidence, ...]
