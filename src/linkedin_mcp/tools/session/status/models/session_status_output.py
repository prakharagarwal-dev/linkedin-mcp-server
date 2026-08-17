"""Models for `linkedin_mcp.tools.session.status`."""

from __future__ import annotations

from linkedin_mcp.browser.bootstrap import BrowserSetupState
from linkedin_mcp.tools._shared.models import Identifier, StrictModel
from linkedin_mcp.tools.session.status.models.session_authentication_state import (
    SessionAuthenticationState,
)


class SessionStatusOutput(StrictModel):
    account_id: Identifier
    profile_present: bool
    browser_setup_state: BrowserSetupState
    browser_started: bool
    authentication_state: SessionAuthenticationState
    automatic_login_enabled: bool
    login_browser_open: bool
    paused: bool
    pause_reason: str | None = None
    status_message: str | None = None
