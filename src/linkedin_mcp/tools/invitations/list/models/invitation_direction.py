"""Models for `linkedin_mcp.tools.invitations.list`."""

from __future__ import annotations

from enum import StrEnum


class InvitationDirection(StrEnum):
    RECEIVED = "received"
    SENT = "sent"
