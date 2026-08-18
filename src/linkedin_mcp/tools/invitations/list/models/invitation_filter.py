"""Models for `linkedin_mcp.tools.invitations.list`."""

from __future__ import annotations

from enum import StrEnum


class InvitationFilter(StrEnum):
    ALL = "all"
    FOCUSED = "focused"
    OTHER = "other"
    VERIFIED = "verified"
    SAME_COMPANY = "same_company"
    SAME_SCHOOL = "same_school"
    MUTUAL_CONNECTIONS = "mutual_connections"
    PEOPLE = "people"


CURRENT_RECEIVED_INVITATION_VIEWS: tuple[InvitationFilter, ...] = (
    InvitationFilter.FOCUSED,
    InvitationFilter.OTHER,
    InvitationFilter.VERIFIED,
    InvitationFilter.MUTUAL_CONNECTIONS,
    InvitationFilter.SAME_COMPANY,
    InvitationFilter.SAME_SCHOOL,
)
