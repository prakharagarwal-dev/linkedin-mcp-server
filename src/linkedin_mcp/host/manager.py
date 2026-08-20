"""Discovery, startup, and lifecycle for the shared local MCP host."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO, Protocol, TextIO
from urllib.parse import urlsplit

from linkedin_mcp import __version__
from linkedin_mcp.config import Settings, runtime_configuration_fingerprint
from linkedin_mcp.errors import ConfigurationError
from linkedin_mcp.host.lock import (
    AccountProcessLock,
    AccountRuntimeStatus,
    inspect_account_runtime,
)
from linkedin_mcp.infra.cursor import CursorStore
from linkedin_mcp.infra.queue import Scheduler, Worker
from linkedin_mcp.tools import attach_tools
from linkedin_mcp.tools._shared.browser import BrowserManager
from linkedin_mcp.transport.server import (
    bind_http_listener,
    create_mcp_server,
    http_server_is_healthy,
    read_http_server_status,
    serve_http,
)

_RUNTIME_OWNER_COMMAND = "shared-runtime"
_RUNTIME_MODULE = "linkedin_mcp.host"
_RUNTIME_TRANSPORT = "shared-loopback"
# The OS lock becomes visible before its holder can fsync owner metadata.
_LOCK_OWNER_PUBLICATION_GRACE_SECONDS = 5.0
_WINDOWS_BROKER_COMMAND_ENV = "LINKEDIN_MCP_INTERNAL_BROKER_COMMAND"
_WINDOWS_BROKER_CWD_ENV = "LINKEDIN_MCP_INTERNAL_BROKER_CWD"
_WINDOWS_BROKERED_RUNTIME_ENV = "LINKEDIN_MCP_INTERNAL_BROKERED_RUNTIME"
_WINDOWS_RUNTIME_CREATION_FLAGS = 0x00000008 | 0x00000200
_WINDOWS_BROKER_SCRIPT = "; ".join(
    (
        f"$command = $env:{_WINDOWS_BROKER_COMMAND_ENV}",
        f"$workingDirectory = $env:{_WINDOWS_BROKER_CWD_ENV}",
        "$environment = [System.Environment]::GetEnvironmentVariables('Process')",
        f"[void]$environment.Remove('{_WINDOWS_BROKER_COMMAND_ENV}')",
        f"[void]$environment.Remove('{_WINDOWS_BROKER_CWD_ENV}')",
        "$environmentVariables = [string[]]@($environment.GetEnumerator() | "
        "ForEach-Object { [string]::Concat($_.Key, '=', $_.Value) })",
        "$startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ "
        f"CreateFlags = [uint32]{_WINDOWS_RUNTIME_CREATION_FLAGS}; "
        "EnvironmentVariables = $environmentVariables; ShowWindow = [uint16]0 }",
        "$result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ "
        "CommandLine = $command; CurrentDirectory = $workingDirectory; "
        "ProcessStartupInformation = $startup }",
        "if ([uint32]$result.ReturnValue -ne 0) { "
        "throw ('Win32_Process.Create failed with code ' + $result.ReturnValue) }",
    )
)


class _HostStarter(Protocol):
    def poll(self) -> int | None: ...


class _BrokeredHostStarter:
    """Report only broker failures while the elected runtime publishes its own PID."""

    def __init__(self, broker: subprocess.Popen[bytes]) -> None:
        self._broker = broker

    def poll(self) -> int | None:
        return_code = self._broker.poll()
        return return_code if return_code not in {None, 0} else None


def host_endpoint(settings: Settings) -> str:
    host = _normalized_loopback_host(settings.http_host)
    rendered_host = f"[{host}]" if ":" in host else host
    return f"http://{rendered_host}:{settings.http_port}/mcp"


async def ensure_host(settings: Settings) -> str:
    """Return a healthy endpoint, starting one elected background owner if needed."""

    status = inspect_account_runtime(settings.runtime_lock_path)
    if status.running and status.owner is None:
        return await wait_for_host(settings)
    _validate_running_owner(status, settings)
    endpoint = await _healthy_endpoint(status)
    if endpoint is not None:
        return endpoint
    if status.running:
        return await wait_for_host(settings)

    starter = _spawn_host(settings)
    return await wait_for_host(settings, starter=starter)


async def wait_for_host(
    settings: Settings,
    *,
    starter: _HostStarter | None = None,
) -> str:
    deadline = time.monotonic() + settings.runtime_start_timeout_seconds
    last_owner_command: str | None = None
    unpublished_owner_since: float | None = None
    while (now := time.monotonic()) < deadline:
        status = inspect_account_runtime(settings.runtime_lock_path)
        owner = status.owner
        last_owner_command = owner.command if owner is not None else None
        if status.running and owner is None:
            if unpublished_owner_since is None:
                unpublished_owner_since = now
            if now - unpublished_owner_since < _LOCK_OWNER_PUBLICATION_GRACE_SECONDS:
                await asyncio.sleep(0.1)
                continue
        else:
            unpublished_owner_since = None
        _validate_running_owner(status, settings)
        endpoint = await _healthy_endpoint(status)
        if endpoint is not None:
            return endpoint
        if starter is not None and starter.poll() is not None and not status.running:
            raise ConfigurationError(
                "The shared LinkedIn MCP runtime failed during startup. See "
                f"{_host_log_path(settings)} for the safe local diagnostic log."
            )
        await asyncio.sleep(0.1)
    suffix = f" The current owner command is {last_owner_command!r}." if last_owner_command else ""
    raise ConfigurationError(
        "The shared LinkedIn MCP runtime did not become healthy before the startup timeout."
        f"{suffix} Run `linkedin-mcp status` for details."
    )


async def host_is_healthy(endpoint: str, *, timeout_seconds: float = 2.0) -> bool:
    try:
        validated = validate_host_endpoint(endpoint)
    except ConfigurationError:
        return False
    return await http_server_is_healthy(validated, timeout_seconds=timeout_seconds)


async def read_host_status(
    endpoint: str,
    *,
    timeout_seconds: float = 2.0,
) -> dict[str, object] | None:
    """Read the runtime's safe local status without entering the browser queue."""

    try:
        validated = validate_host_endpoint(endpoint)
    except ConfigurationError:
        return None
    return await read_http_server_status(validated, timeout_seconds=timeout_seconds)


async def run_host(settings: Settings) -> None:
    """Own the profile lock and serve stateful MCP sessions on loopback."""

    endpoint = host_endpoint(settings)
    host = _normalized_loopback_host(settings.http_host)
    process_lock = AccountProcessLock(
        settings.runtime_lock_path,
        account_id=settings.account_id,
        command=_RUNTIME_OWNER_COMMAND,
        transport=_RUNTIME_TRANSPORT,
        version=__version__,
        configuration_fingerprint=runtime_configuration_fingerprint(settings),
    )
    browser = BrowserManager(settings)
    scheduler = Scheduler(Worker(), capacity=settings.queue_capacity)
    cursor_store = CursorStore(
        ttl_seconds=settings.pagination_cursor_ttl_seconds,
        max_active_cursors=settings.pagination_max_active_cursors,
        max_seen_items_per_cursor=settings.pagination_max_seen_items_per_cursor,
    )
    mcp = create_mcp_server(settings)
    attach_tools(
        mcp,
        settings=settings,
        browser=browser,
        scheduler=scheduler,
        cursor_store=cursor_store,
    )
    process_lock.acquire()
    try:
        await scheduler.start()
        browser.start_session_bootstrap()
        listener = bind_http_listener(host, settings.http_port)
        try:
            process_lock.publish_endpoint(endpoint)
            await serve_http(
                mcp,
                settings,
                listener,
                process_lock.wait_for_stop_request,
            )
        finally:
            listener.close()
    finally:
        try:
            await scheduler.quiesce()
        finally:
            try:
                await scheduler.close()
            finally:
                try:
                    await cursor_store.close()
                finally:
                    try:
                        await browser.close()
                    finally:
                        process_lock.release()


def validate_host_endpoint(endpoint: str) -> str:
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
    endpoint = validate_host_endpoint(owner.endpoint)
    return endpoint if await host_is_healthy(endpoint) else None


def _spawn_host(settings: Settings) -> _HostStarter:
    log_path = _host_log_path(settings)
    log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with suppress(OSError):
        log_path.parent.chmod(0o700)
    log = log_path.open("ab", buffering=0)
    try:
        if os.name != "nt":
            os.fchmod(log.fileno(), 0o600)
        if os.name == "nt":
            process: _HostStarter = _spawn_windows_host(log)
        else:
            process = subprocess.Popen(
                [sys.executable, "-m", _RUNTIME_MODULE],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                close_fds=True,
                start_new_session=True,
            )
    finally:
        log.close()
    return process


def _spawn_windows_host(log: BinaryIO) -> _BrokeredHostStarter:
    """Ask local Windows CIM to create the runtime outside the caller's Job Object."""

    environment = os.environ.copy()
    environment[_WINDOWS_BROKER_COMMAND_ENV] = subprocess.list2cmdline(
        [sys.executable, "-m", _RUNTIME_MODULE]
    )
    environment[_WINDOWS_BROKER_CWD_ENV] = str(Path.cwd())
    environment[_WINDOWS_BROKERED_RUNTIME_ENV] = "1"
    powershell = (
        Path(environment.get("SystemRoot", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    try:
        broker = subprocess.Popen(
            [
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _WINDOWS_BROKER_SCRIPT,
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            close_fds=True,
            creationflags=creation_flags,
            env=environment,
        )
    except OSError as error:
        raise ConfigurationError(
            "The shared LinkedIn MCP runtime could not start through local Windows CIM."
        ) from error
    return _BrokeredHostStarter(broker)


def brokered_host_output_required() -> bool:
    return os.environ.get(_WINDOWS_BROKERED_RUNTIME_ENV) == "1"


def redirect_brokered_host_output(settings: Settings) -> TextIO:
    """Give the detached Windows runtime safe Python output streams for diagnostics."""

    log_path = _host_log_path(settings)
    log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    log = log_path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = log
    sys.stderr = log
    return log


def _host_log_path(settings: Settings) -> Path:
    return settings.runtime_lock_path.with_name("runtime.log")


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
    if owner.command != _RUNTIME_OWNER_COMMAND:
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
