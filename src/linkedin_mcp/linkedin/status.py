"""Typed status contracts for the LinkedIn session and MCP server."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from linkedin_mcp.browser.models import BrowserSetupState
from linkedin_mcp.linkedin.common import (
    CapabilityName,
    Identifier,
    StrictModel,
)


class SessionAuthenticationState(StrEnum):
    UNVERIFIED = "unverified"
    LOGIN_REQUIRED = "login_required"
    LOGIN_IN_PROGRESS = "login_in_progress"
    VALIDATING = "validating"
    AUTHENTICATED = "authenticated"
    ATTENTION_REQUIRED = "attention_required"


class ServerStatusOutput(StrictModel):
    name: Literal["linkedin-mcp-server"] = "linkedin-mcp-server"
    version: str
    transport: Literal["stdio", "streamable-http"]
    operation_state: Literal["process_local"] = "process_local"
    runtime_model: Literal["shared_local"] = "shared_local"
    connected_clients: Annotated[int, Field(ge=0)] = 0
    queue_depth: Annotated[int, Field(ge=0)] = 0
    queued_clients: Annotated[int, Field(ge=0)] = 0
    active_browser_operation: bool = False
    active_capability: CapabilityName | None = None
    accepting_calls: bool = True


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
