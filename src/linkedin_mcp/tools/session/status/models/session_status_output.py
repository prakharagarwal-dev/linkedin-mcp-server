"""Models for `linkedin_mcp.tools.session.status`."""

from __future__ import annotations

from linkedin_mcp.browser.bootstrap import BrowserSetupState
from linkedin_mcp.tools._shared.models import Identifier, StrictModel
from linkedin_mcp.ui import AuthenticationState


class SessionStatusOutput(StrictModel):
    account_id: Identifier
    profile_present: bool
    browser_setup_state: BrowserSetupState
    browser_started: bool
    authentication_state: AuthenticationState
    paused: bool
    pause_reason: str | None = None
    status_message: str | None = None
