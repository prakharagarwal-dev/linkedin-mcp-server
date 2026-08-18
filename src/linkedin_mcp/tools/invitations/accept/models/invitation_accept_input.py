"""Models for `linkedin_mcp.tools.invitations.accept`."""

from __future__ import annotations

from linkedin_mcp.tools._shared.models import Identifier, ProfileSlug, StrictModel


class InvitationAcceptInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    profile_slug: ProfileSlug
