"""Models for `linkedin_mcp.tools.server.status`."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from linkedin_mcp.tools._shared.models import StrictModel


class ServerStatusOutput(StrictModel):
    name: Literal["linkedin-mcp-server"] = "linkedin-mcp-server"
    version: str
    transport: Literal["stdio", "streamable-http"]
    operation_state: Literal["process_local"] = "process_local"
    runtime_model: Literal["shared_local"] = "shared_local"
    queue_depth: Annotated[int, Field(ge=0)] = 0
    active_browser_operation: bool = False
    active_task: str | None = None
    accepting_calls: bool = True
