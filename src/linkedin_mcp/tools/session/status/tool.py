"""FastMCP definition for `linkedin.session.status`."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from linkedin_mcp.app.container import AppContainer
from linkedin_mcp.tools.session.status.models.session_status_output import SessionStatusOutput


def register(
    mcp: FastMCP[None],
    container: AppContainer,
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
            account_id=container.settings.account_id,
            profile_present=container.browser.profile_present(),
            browser_setup_state=container.browser.browser_setup_state,
            browser_started=container.browser.started,
            authentication_state=container.browser.authentication_state,
            automatic_login_enabled=container.settings.auto_login_on_start,
            login_browser_open=container.browser.login_browser_open,
            paused=container.browser.paused,
            pause_reason=container.browser.pause_reason,
            status_message=container.browser.authentication_status_message,
        )

    del _session_status
