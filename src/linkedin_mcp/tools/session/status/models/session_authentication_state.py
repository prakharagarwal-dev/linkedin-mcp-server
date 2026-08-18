"""Models for `linkedin_mcp.tools.session.status`."""

from __future__ import annotations

from enum import StrEnum


class SessionAuthenticationState(StrEnum):
    UNVERIFIED = "unverified"
    LOGIN_REQUIRED = "login_required"
    LOGIN_IN_PROGRESS = "login_in_progress"
    VALIDATING = "validating"
    AUTHENTICATED = "authenticated"
    ATTENTION_REQUIRED = "attention_required"
