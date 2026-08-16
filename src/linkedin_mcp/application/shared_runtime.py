"""Discovery, election, and lifecycle for the shared local MCP runtime."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

import uvicorn
from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client

from linkedin_mcp import __version__
from linkedin_mcp.application.process_lock import (
    AccountProcessLock,
    AccountRuntimeStatus,
    inspect_account_runtime,
)
from linkedin_mcp.config import Settings, runtime_configuration_fingerprint
from linkedin_mcp.container import create_production_container
from linkedin_mcp.errors import ConfigurationError
from linkedin_mcp.server import create_mcp_server

_RUNTIME_COMMAND = "_runtime"
_RUNTIME_TRANSPORT = "shared-loopback"


def shared_runtime_endpoint(settings: Settings) -> str:
    host = _normalized_loopback_host(settings.http_host)
    rendered_host = f"[{host}]" if ":" in host else host
    return f"http://{rendered_host}:{settings.http_port}/mcp"


async def ensure_shared_runtime(settings: Settings) -> str:
    """Return a healthy endpoint, starting one elected background owner if needed."""

    status = inspect_account_runtime(settings.runtime_lock_path)
    _validate_running_owner(status, settings)
    endpoint = await _healthy_endpoint(status)
    if endpoint is not None:
        return endpoint
    if status.running:
        return await wait_for_shared_runtime(settings)

    starter = _spawn_shared_runtime(settings)
    return await wait_for_shared_runtime(settings, starter=starter)


async def wait_for_shared_runtime(
    settings: Settings,
    *,
    starter: subprocess.Popen[bytes] | None = None,
) -> str:
    deadline = time.monotonic() + settings.runtime_start_timeout_seconds
    last_owner_command: str | None = None
    while time.monotonic() < deadline:
        status = inspect_account_runtime(settings.runtime_lock_path)
        owner = status.owner
        last_owner_command = owner.command if owner is not None else None
        _validate_running_owner(status, settings)
        endpoint = await _healthy_endpoint(status)
        if endpoint is not None:
            return endpoint
        if starter is not None and starter.poll() is not None and not status.running:
            raise ConfigurationError(
                "The shared LinkedIn MCP runtime failed during startup. See "
                f"{_runtime_log_path(settings)} for the safe local diagnostic log."
            )
        await asyncio.sleep(0.1)
    suffix = f" The current owner command is {last_owner_command!r}." if last_owner_command else ""
    raise ConfigurationError(
        "The shared LinkedIn MCP runtime did not become healthy before the startup timeout."
        f"{suffix} Run `linkedin-mcp status` for details."
    )


async def runtime_is_healthy(endpoint: str, *, timeout_seconds: float = 2.0) -> bool:
    try:
        validated = validate_shared_runtime_endpoint(endpoint)
        async with asyncio.timeout(timeout_seconds):
            async with streamable_http_client(validated) as (read_stream, write_stream, _):
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


async def read_shared_runtime_status(
    endpoint: str,
    *,
    timeout_seconds: float = 2.0,
) -> dict[str, object] | None:
    """Read the runtime's safe local status without entering the browser queue."""

    try:
        validated = validate_shared_runtime_endpoint(endpoint)
        async with asyncio.timeout(timeout_seconds):
            async with streamable_http_client(validated) as (read_stream, write_stream, _):
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


async def run_shared_runtime(settings: Settings) -> None:
    """Own the profile lock and serve stateful MCP sessions on loopback."""

    endpoint = shared_runtime_endpoint(settings)
    host = _normalized_loopback_host(settings.http_host)
    container = create_production_container(settings)
    container.process_lock = AccountProcessLock(
        settings.runtime_lock_path,
        account_id=settings.account_id,
        command=_RUNTIME_COMMAND,
        transport=_RUNTIME_TRANSPORT,
        version=__version__,
        configuration_fingerprint=runtime_configuration_fingerprint(settings),
    )
    listener: socket.socket | None = None
    await container.start()
    try:
        listener = _bind_listener(host, settings.http_port)
        mcp = create_mcp_server(container, manage_container_lifecycle=False)
        app = mcp.streamable_http_app()
        config = uvicorn.Config(
            app,
            host=host,
            port=settings.http_port,
            log_level=settings.log_level.lower(),
            access_log=False,
            timeout_graceful_shutdown=None,
        )
        server = uvicorn.Server(config)
        container.process_lock.publish_endpoint(endpoint)
        await _serve_until_stopped(server, container.process_lock, listener)
    finally:
        if listener is not None:
            listener.close()
        await container.close()


def validate_shared_runtime_endpoint(endpoint: str) -> str:
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError as error:
        raise ConfigurationError("The shared runtime published an invalid endpoint.") from error
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
        or port is None
        or parsed.path != "/mcp"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigurationError("The shared runtime endpoint is not an exact loopback MCP URL.")
    return endpoint


async def _healthy_endpoint(status: AccountRuntimeStatus) -> str | None:
    owner = status.owner
    if not status.running or owner is None or owner.endpoint is None:
        return None
    endpoint = validate_shared_runtime_endpoint(owner.endpoint)
    return endpoint if await runtime_is_healthy(endpoint) else None


def _spawn_shared_runtime(settings: Settings) -> subprocess.Popen[bytes]:
    log_path = _runtime_log_path(settings)
    log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with suppress(OSError):
        log_path.parent.chmod(0o700)
    log = log_path.open("ab", buffering=0)
    try:
        if os.name != "nt":
            os.fchmod(log.fileno(), 0o600)
        if os.name == "nt":
            creation_flags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200))
            creation_flags |= int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
            process = subprocess.Popen(
                [sys.executable, "-m", "linkedin_mcp", _RUNTIME_COMMAND],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                close_fds=True,
                creationflags=creation_flags,
            )
        else:
            process = subprocess.Popen(
                [sys.executable, "-m", "linkedin_mcp", _RUNTIME_COMMAND],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                close_fds=True,
                start_new_session=True,
            )
    finally:
        log.close()
    return process


def _runtime_log_path(settings: Settings) -> Path:
    return settings.runtime_lock_path.with_name("runtime.log")


async def _serve_until_stopped(
    server: uvicorn.Server,
    process_lock: AccountProcessLock,
    listener: socket.socket,
) -> None:
    """Serve until Uvicorn exits or the exact elected owner receives a stop request."""

    server_task = asyncio.create_task(server.serve(sockets=[listener]))
    stop_task = asyncio.create_task(process_lock.wait_for_stop_request())
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


def _normalized_loopback_host(host: str) -> str:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ConfigurationError("The shared MCP runtime must bind to an exact loopback host.")
    return "127.0.0.1" if host == "localhost" else host


def _validate_running_owner(status: AccountRuntimeStatus, settings: Settings) -> None:
    if not status.running:
        return
    owner = status.owner
    if owner is None:
        raise ConfigurationError(
            "A local process owns the LinkedIn profile without valid runtime metadata. "
            "Run `linkedin-mcp status`, then `linkedin-mcp stop`."
        )
    if owner.command != _RUNTIME_COMMAND:
        raise ConfigurationError(
            f"LinkedIn profile maintenance ({owner.command or 'unknown'}) "
            "currently owns the browser profile. Retry after it completes, or run "
            "`linkedin-mcp stop`."
        )
    if owner.version != __version__:
        raise ConfigurationError(
            f"LinkedIn MCP runtime version {owner.version or 'unknown'} is already running, "
            f"but this client uses {__version__}. Run `linkedin-mcp stop`, then retry."
        )
    if owner.account_id != settings.account_id:
        raise ConfigurationError(
            f"The shared runtime owns account {owner.account_id or 'unknown'}, but this client "
            f"configured {settings.account_id}. Use a distinct runtime lock and port, or run "
            "`linkedin-mcp stop`."
        )
    expected_fingerprint = runtime_configuration_fingerprint(settings)
    if owner.configuration_fingerprint != expected_fingerprint:
        raise ConfigurationError(
            "The running LinkedIn MCP runtime uses different profile, browser, "
            "pacing, or transport settings. Make client configurations match, or run "
            "`linkedin-mcp stop` and restart with the intended settings."
        )


def _bind_listener(host: str, port: int) -> socket.socket:
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
