"""Models for `linkedin_mcp.tools.invitations.list`."""

from __future__ import annotations

from enum import StrEnum


class InvitationEntityType(StrEnum):
    PERSON = "person"
    COMPANY = "company"
    SCHOOL = "school"
    GROUP = "group"
    EVENT = "event"
    NEWSLETTER = "newsletter"
    OTHER = "other"
