"""Models for `linkedin_mcp.tools.invitations.list`."""

from __future__ import annotations

from enum import StrEnum


class InvitationType(StrEnum):
    CONNECTION_REQUEST = "connection_request"
    COMPANY_FOLLOW = "company_follow"
    SCHOOL_INVITATION = "school_invitation"
    GROUP_INVITATION = "group_invitation"
    EVENT_INVITATION = "event_invitation"
    NEWSLETTER_INVITATION = "newsletter_invitation"
    OTHER = "other"
