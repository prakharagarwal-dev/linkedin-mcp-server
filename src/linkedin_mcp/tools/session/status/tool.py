"""FastMCP definition for `linkedin.session.status`."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from linkedin_mcp.config import Settings
from linkedin_mcp.tools.session.status.models.session_status_output import SessionStatusOutput
from linkedin_mcp.ui import LinkedInPlaywright


def register(
    mcp: FastMCP[None],
    settings: Settings,
    playwright: LinkedInPlaywright,
    annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        name="linkedin.session.status",
        title="LinkedIn Session Status",
        description="Return non-secret browser-session state for the configured account.",
        annotations=annotations,
    )
    async def _session_status() -> SessionStatusOutput:
        return SessionStatusOutput(
            account_id=settings.account_id,
            profile_present=playwright.profile_present(),
            browser_setup_state=playwright.browser_setup_state,
            browser_started=playwright.started,
            authentication_state=playwright.authentication_state,
            paused=playwright.paused,
            pause_reason=playwright.pause_reason,
            status_message=playwright.authentication_status_message,
        )

    del _session_status
