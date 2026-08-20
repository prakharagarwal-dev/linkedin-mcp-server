"""Discovery, startup, and lifecycle for the shared local MCP host."""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import BinaryIO, Protocol, TextIO
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP

from linkedin_mcp import __version__
from linkedin_mcp.browser import BrowserManager
from linkedin_mcp.config import Settings, runtime_configuration_fingerprint
from linkedin_mcp.errors import ConfigurationError, LinkedInMCPError
from linkedin_mcp.host.lock import (
    AccountProcessLock,
    AccountRuntimeStatus,
    inspect_account_runtime,
    run_owned_operation,
)
from linkedin_mcp.infra.cursor import CursorStore
from linkedin_mcp.infra.playwright import Paced
from linkedin_mcp.infra.queue import Scheduler, Worker
from linkedin_mcp.tools import attach_tools
from linkedin_mcp.transport.server import (
    bind_http_listener,
    create_mcp_server,
    http_server_is_healthy,
    read_http_server_status,
    serve_http,
)
from linkedin_mcp.transport.stdio import run_stdio_proxy

_RUNTIME_OWNER_COMMAND = "shared-runtime"
_RUNTIME_MODULE = "linkedin_mcp"
_RUNTIME_TRANSPORT = "shared-loopback"
_INTERNAL_HOST_ENV = "LINKEDIN_MCP_INTERNAL_HOST"
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


class HostManager:
    """Own the process transport and every component used by the shared MCP host."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._process_lock: AccountProcessLock | None = None
        self._browser: BrowserManager | None = None
        self._scheduler: Scheduler | None = None
        self._scheduler_started = False
        self._cursor_store: CursorStore | None = None
        self._mcp: FastMCP[None] | None = None
        self._listener: socket.socket | None = None

    async def serve(self) -> str | None:
        """Start or attach to the configured transport.

        A returned endpoint means another process already owns the shared host.
        ``None`` means this call served until the host was stopped, or the stdio
        bridge ran until its client disconnected.
        """

        if self.settings.transport == "stdio":
            endpoint = await self.ensure_host()
            await run_stdio_proxy(endpoint)
            return None

        status = inspect_account_runtime(self.settings.runtime_lock_path)
        if status.running:
            return await self.wait_for_host()
        try:
            await self.run_http()
        except LinkedInMCPError:
            status = inspect_account_runtime(self.settings.runtime_lock_path)
            if not status.running:
                raise
            return await self.wait_for_host()
        return None

    async def ensure_host(self) -> str:
        """Return the shared endpoint, creating its owner process when necessary."""

        return await ensure_host(self.settings)

    async def wait_for_host(self) -> str:
        """Wait for the elected shared owner to publish a healthy endpoint."""

        return await wait_for_host(self.settings)

    async def login(self) -> None:
        """Perform visible login while exclusively owning the browser profile."""

        async def operation() -> None:
            browser = BrowserManager(
                self.settings,
                Paced(self.settings.browser_action_delay_seconds),
            )
            try:
                await browser.login()
            finally:
                await browser.close()

        await run_owned_operation(self.settings, command="login", operation=operation)

    async def logout(self) -> bool:
        """Perform visible logout while exclusively owning the browser profile."""

        async def operation() -> bool:
            browser = BrowserManager(
                self.settings,
                Paced(self.settings.browser_action_delay_seconds),
            )
            try:
                return await browser.logout()
            finally:
                await browser.close()

        return await run_owned_operation(self.settings, command="logout", operation=operation)

    async def run_http(self) -> None:
        """Start all infrastructure, then expose the ready host on loopback HTTP."""

        endpoint = host_endpoint(self.settings)
        host = _normalized_loopback_host(self.settings.http_host)
        self._process_lock = AccountProcessLock(
            self.settings.runtime_lock_path,
            account_id=self.settings.account_id,
            command=_RUNTIME_OWNER_COMMAND,
            transport=_RUNTIME_TRANSPORT,
            version=__version__,
            configuration_fingerprint=runtime_configuration_fingerprint(self.settings),
        )
        self._process_lock.acquire()
        try:
            self._browser = BrowserManager(
                self.settings,
                Paced(self.settings.browser_action_delay_seconds),
            )
            await self._browser.start()
            self._scheduler = Scheduler(Worker(), capacity=self.settings.queue_capacity)
            self._cursor_store = CursorStore(
                ttl_seconds=self.settings.pagination_cursor_ttl_seconds,
                max_active_cursors=self.settings.pagination_max_active_cursors,
                max_seen_items_per_cursor=self.settings.pagination_max_seen_items_per_cursor,
            )
            self._mcp = create_mcp_server(self.settings)
            attach_tools(
                self._mcp,
                settings=self.settings,
                browser=self._browser,
                scheduler=self._scheduler,
                cursor_store=self._cursor_store,
            )
            await self._scheduler.start()
            self._scheduler_started = True
            self._listener = bind_http_listener(host, self.settings.http_port)
            self._process_lock.publish_endpoint(endpoint)
            await serve_http(
                self._mcp,
                self.settings,
                self._listener,
                self._process_lock.wait_for_stop_request,
            )
        finally:
            await self.close()

    async def close(self) -> None:
        """Close the host in reverse startup order; safe after partial startup."""

        listener = self._listener
        scheduler = self._scheduler
        cursor_store = self._cursor_store
        browser = self._browser
        process_lock = self._process_lock
        scheduler_started = self._scheduler_started

        self._listener = None
        self._scheduler = None
        self._cursor_store = None
        self._browser = None
        self._process_lock = None
        self._mcp = None
        self._scheduler_started = False

        if listener is not None:
            listener.close()
        try:
            if scheduler is not None and scheduler_started:
                await scheduler.quiesce()
        finally:
            try:
                if scheduler is not None:
                    await scheduler.close()
            finally:
                try:
                    if cursor_store is not None:
                        await cursor_store.close()
                finally:
                    try:
                        if browser is not None:
                            await browser.close()
                    finally:
                        if process_lock is not None:
                            process_lock.release()


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
        environment = os.environ.copy()
        environment[_INTERNAL_HOST_ENV] = "1"
        if os.name != "nt":
            os.fchmod(log.fileno(), 0o600)
        if os.name == "nt":
            process: _HostStarter = _spawn_windows_host(log, environment=environment)
        else:
            process = subprocess.Popen(
                [sys.executable, "-m", _RUNTIME_MODULE],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                close_fds=True,
                start_new_session=True,
                env=environment,
            )
    finally:
        log.close()
    return process


def _spawn_windows_host(
    log: BinaryIO,
    *,
    environment: dict[str, str] | None = None,
) -> _BrokeredHostStarter:
    """Ask local Windows CIM to create the runtime outside the caller's Job Object."""

    environment = environment or os.environ.copy()
    environment[_INTERNAL_HOST_ENV] = "1"
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


def internal_host_requested() -> bool:
    """Return whether the root module was launched as the private host owner."""

    return os.environ.get(_INTERNAL_HOST_ENV) == "1"


async def run_internal_host(settings: Settings) -> None:
    """Run the elected HTTP owner, or wait for the process that won the race."""

    values = settings.model_dump()
    values["transport"] = "streamable-http"
    host_settings = Settings.model_validate(values)
    try:
        await HostManager(host_settings).run_http()
    except LinkedInMCPError:
        status = inspect_account_runtime(host_settings.runtime_lock_path)
        if not status.running:
            raise
        await wait_for_host(host_settings)


def host_process_main() -> None:
    """Root-module entrypoint used only by a spawned shared-host process."""

    from pydantic import ValidationError

    from linkedin_mcp.logging import configure_logging

    try:
        settings = Settings()
        if brokered_host_output_required():
            redirect_brokered_host_output(settings)
        configure_logging(settings.log_level)
        asyncio.run(run_internal_host(settings))
    except (LinkedInMCPError, ValidationError, ValueError, RuntimeError) as error:
        print(f"linkedin-mcp host: {error}", file=sys.stderr)
        raise SystemExit(1) from error
    except Exception as error:
        print("linkedin-mcp host: an unexpected startup failure occurred", file=sys.stderr)
        raise SystemExit(1) from error
