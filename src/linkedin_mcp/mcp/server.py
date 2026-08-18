"""FastMCP server composition for capability-owned tool definitions."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

from linkedin_mcp import __version__
from linkedin_mcp.container import AppContainer
from linkedin_mcp.mcp.context import bind_client_execution
from linkedin_mcp.tools import attach_tools


def create_mcp_server(
    container: AppContainer,
    *,
    manage_container_lifecycle: bool = True,
) -> FastMCP[None]:
    @asynccontextmanager
    async def lifespan(_: FastMCP[None]) -> AsyncGenerator[None]:
        if manage_container_lifecycle:
            await container.start()
        try:
            yield None
        finally:
            if manage_container_lifecycle:
                await container.close()

    mcp: FastMCP[None] = FastMCP(
        "linkedin-mcp-server",
        instructions=(
            "Each account-changing tool performs one complete LinkedIn action. Every invocation "
            "is new, so do not retry an uncertain action blindly. Use only registered typed "
            "LinkedIn capabilities. Every read invocation executes freshly. Cursors belong to "
            "the MCP session that created them."
        ),
        json_response=True,
        stateless_http=False,
        host=container.settings.http_host,
        port=container.settings.http_port,
        log_level=container.settings.log_level,
        lifespan=lifespan,
    )
    # FastMCP does not currently forward a product version to its low-level server.
    mcp._mcp_server.version = __version__  # pyright: ignore[reportPrivateUsage]

    attach_tools(mcp, container)
    _install_client_context_binding(mcp, container)
    return mcp


def _install_client_context_binding(mcp: FastMCP[None], container: AppContainer) -> None:
    """Bind every protocol request to an opaque identity owned by its MCP session."""

    low_level = mcp._mcp_server  # pyright: ignore[reportPrivateUsage]
    for request_type, handler in tuple(low_level.request_handlers.items()):

        async def with_client_context(request: Any, *, _handler: Any = handler) -> Any:
            session = low_level.request_context.session
            client_id = container.clients.resolve(session)
            with bind_client_execution(client_id):
                return await _handler(request)

        low_level.request_handlers[request_type] = with_client_context
