"""FastMCP composition and loopback Streamable HTTP serving."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Awaitable, Callable
from typing import cast

import uvicorn
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.server.fastmcp import FastMCP
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from linkedin_mcp import __version__
from linkedin_mcp.config import Settings


class _LoopbackMCPApp:
    """Expose request/response MCP without the optional standalone SSE stream."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "GET":
            await Response(status_code=405, headers={"Allow": "POST, DELETE"})(
                scope,
                receive,
                send,
            )
            return
        await self._app(scope, receive, send)


def create_mcp_server(settings: Settings) -> FastMCP[None]:
    """Create the transport-facing FastMCP server without application dependencies."""

    mcp: FastMCP[None] = FastMCP(
        "linkedin-mcp-server",
        instructions=(
            "Each account-changing tool performs one complete LinkedIn action. Every invocation "
            "is new, so do not retry an uncertain action blindly. Use only registered typed "
            "LinkedIn capabilities. Every read invocation executes freshly."
        ),
        json_response=True,
        stateless_http=False,
        host=settings.http_host,
        port=settings.http_port,
        log_level=settings.log_level,
    )
    # FastMCP does not currently forward a product version to its low-level server.
    mcp._mcp_server.version = __version__  # pyright: ignore[reportPrivateUsage]

    return mcp


def bind_http_listener(host: str, port: int) -> socket.socket:
    """Bind the exact loopback listener before publishing the host endpoint."""

    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    listener = socket.socket(family, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(socket.SOMAXCONN)
        listener.setblocking(False)
        return listener
    except BaseException:
        listener.close()
        raise


async def serve_http(
    mcp: FastMCP[None],
    settings: Settings,
    listener: socket.socket,
    wait_for_stop: Callable[[], Awaitable[None]],
) -> None:
    """Serve Streamable HTTP until Uvicorn exits or the host requests shutdown."""

    app = _LoopbackMCPApp(mcp.streamable_http_app())
    config = uvicorn.Config(
        app,
        host=settings.http_host,
        port=settings.http_port,
        log_level=settings.log_level.lower(),
        access_log=False,
        timeout_graceful_shutdown=None,
    )
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve(sockets=[listener]))
    stop_task = asyncio.ensure_future(wait_for_stop())
    try:
        done, _ = await asyncio.wait(
            (server_task, stop_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_task in done:
            await stop_task
            server.should_exit = True
        await server_task
    finally:
        for task in (server_task, stop_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(server_task, stop_task, return_exceptions=True)


async def http_server_is_healthy(endpoint: str, *, timeout_seconds: float = 2.0) -> bool:
    """Probe one already-validated Streamable HTTP endpoint."""

    try:
        async with asyncio.timeout(timeout_seconds):
            async with streamable_http_client(endpoint) as (read_stream, write_stream, _):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    client_info=types.Implementation(
                        name="linkedin-mcp-runtime-probe",
                        version=__version__,
                    ),
                ) as session:
                    await session.initialize()
                    await session.send_ping()
        return True
    except Exception:
        return False


async def read_http_server_status(
    endpoint: str,
    *,
    timeout_seconds: float = 2.0,
) -> dict[str, object] | None:
    """Read safe status from one already-validated Streamable HTTP endpoint."""

    try:
        async with asyncio.timeout(timeout_seconds):
            async with streamable_http_client(endpoint) as (read_stream, write_stream, _):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    client_info=types.Implementation(
                        name="linkedin-mcp-status",
                        version=__version__,
                    ),
                ) as session:
                    await session.initialize()
                    result = await session.call_tool("linkedin.server.status", {})
        if result.isError or result.structuredContent is None:
            return None
        return cast(dict[str, object], result.structuredContent)
    except Exception:
        return None
