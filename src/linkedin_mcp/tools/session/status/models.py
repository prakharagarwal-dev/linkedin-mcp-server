"""Models owned by `linkedin.session.status`."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from linkedin_mcp.browser import AuthenticationState, BrowserSetupState


class StrictModel(BaseModel):
    """Base model that rejects undeclared input and normalizes strings."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
        validate_assignment=True,
    )


Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=200, pattern="^[A-Za-z0-9][A-Za-z0-9._:-]*$")
]


class SessionStatusOutput(StrictModel):
    account_id: Identifier
    profile_present: bool
    browser_setup_state: BrowserSetupState
    browser_started: bool
    authentication_state: AuthenticationState
    paused: bool
    pause_reason: str | None = None
    status_message: str | None = None
