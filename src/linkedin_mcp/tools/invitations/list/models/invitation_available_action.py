"""Models for `linkedin_mcp.tools.invitations.list`."""

from __future__ import annotations

from enum import StrEnum


class InvitationAvailableAction(StrEnum):
    ACCEPT = "accept"
    IGNORE = "ignore"
    WITHDRAW = "withdraw"
    MESSAGE = "message"
    REPLY = "reply"
