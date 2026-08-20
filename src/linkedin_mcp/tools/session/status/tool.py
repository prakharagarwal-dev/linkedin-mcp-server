"""FastMCP definition for `linkedin.session.status`."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from linkedin_mcp.browser import BrowserManager
from linkedin_mcp.config import Settings
from linkedin_mcp.tools.session.status.models import SessionStatusOutput


def register(
    mcp: FastMCP[None],
    settings: Settings,
    browser: BrowserManager,
) -> None:
    @mcp.tool(
        name="linkedin.session.status",
        title="LinkedIn Session Status",
        description="Return non-secret browser-session state for the configured account.",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    async def _session_status() -> SessionStatusOutput:
        return SessionStatusOutput(
            account_id=settings.account_id,
            profile_present=browser.profile_present(),
            browser_setup_state=browser.browser_setup_state,
            browser_started=browser.started,
            authentication_state=browser.authentication_state,
            paused=browser.paused,
            pause_reason=browser.pause_reason,
            status_message=browser.authentication_status_message,
        )

    del _session_status
