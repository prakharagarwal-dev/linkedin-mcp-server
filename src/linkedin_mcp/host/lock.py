"""Cross-platform ownership for the shared host and exclusive profile operations."""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
import signal
import time
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from types import FrameType
from typing import BinaryIO, cast
from uuid import uuid4

from linkedin_mcp.config import Settings
from linkedin_mcp.errors import ConfigurationError

_LOCK_BYTES = 1
_WINDOWS_LOCK_OFFSET = 0x7FFF_FFFE
_MAX_OWNER_BYTES = 64 * 1024
_STOP_POLL_SECONDS = 0.1
# POSIX flock reports EACCES/EAGAIN, and Windows maps a byte-range lock
# violation to EACCES plus winerror 33. Both errno names exist on every
# supported Python platform; less portable aliases are intentionally omitted.
_CONTENTION_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN})
_WINDOWS_LOCK_VIOLATION = 33
_STOP_PROTOCOL = "file-v1"


@dataclass(frozen=True, slots=True)
class AccountRuntimeOwner:
    """Non-secret identity of the process holding one account lock."""

    pid: int
    instance_id: str | None = None
    account_id: str | None = None
    command: str | None = None
    transport: str | None = None
    started_at: str | None = None
    endpoint: str | None = None
    version: str | None = None
    configuration_fingerprint: str | None = None
    stop_protocol: str | None = None


@dataclass(frozen=True, slots=True)
class AccountRuntimeStatus:
    """Current ownership state for one configured runtime lock."""

    running: bool
    owner: AccountRuntimeOwner | None = None


class AccountProcessLock:
    """Elect one shared browser-runtime owner for a configured LinkedIn account."""

    def __init__(
        self,
        path: Path,
        *,
        account_id: str | None = None,
        command: str | None = None,
        transport: str | None = None,
        version: str | None = None,
        configuration_fingerprint: str | None = None,
    ) -> None:
        self._path = path
        self._account_id = account_id
        self._command = command
        self._transport = transport
        self._version = version
        self._configuration_fingerprint = configuration_fingerprint
        self._instance_id = str(uuid4())
        self._handle: BinaryIO | None = None
        self._owner: AccountRuntimeOwner | None = None

    @property
    def acquired(self) -> bool:
        return self._handle is not None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def owner(self) -> AccountRuntimeOwner:
        owner = self._owner
        if self._handle is None or owner is None:
            raise RuntimeError("The account runtime lock is not owned by this process.")
        return owner

    def acquire(self) -> None:
        if self.acquired:
            return
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _harden_directory(self._path.parent)
        handle = _open_lock_file(self._path, create=True)
        try:
            if not _try_lock(handle.fileno()):
                handle.close()
                status = inspect_account_runtime(self._path)
                owner_suffix = ""
                if status.owner is not None:
                    owner_suffix = f" (PID {status.owner.pid})"
                raise ConfigurationError(
                    "Another local LinkedIn runtime or profile-maintenance command already owns "
                    "this account"
                    f"{owner_suffix}. Run `linkedin-mcp status`, then `linkedin-mcp stop` "
                    "to release it."
                )
        except Exception:
            if not handle.closed:
                handle.close()
            raise

        owner = AccountRuntimeOwner(
            pid=os.getpid(),
            instance_id=self._instance_id,
            account_id=self._account_id,
            command=self._command,
            transport=self._transport,
            started_at=datetime.now(UTC).isoformat(),
            version=self._version,
            configuration_fingerprint=self._configuration_fingerprint,
            stop_protocol=_STOP_PROTOCOL,
        )
        self._handle = handle
        self._owner = owner
        try:
            _clear_stale_stop_requests(self._path)
            self._write_owner(owner)
        except BaseException:
            self.release()
            raise

    def publish_endpoint(self, endpoint: str) -> AccountRuntimeOwner:
        """Publish the healthy loopback endpoint while retaining lock ownership."""

        if not endpoint.startswith(("http://127.0.0.1:", "http://[::1]:", "http://localhost:")):
            raise ValueError("The shared runtime endpoint must use an explicit loopback host.")
        owner = self.owner
        owner = replace(owner, endpoint=endpoint)
        self._owner = owner
        self._write_owner(owner)
        return owner

    async def wait_for_stop_request(self) -> None:
        """Wait until ``linkedin-mcp stop`` addresses this exact owner instance."""

        owner = self.owner
        instance_id = owner.instance_id
        if instance_id is None:
            raise RuntimeError("The account runtime owner has no stop-request identity.")
        request_path = _stop_request_path(self._path, instance_id)
        while self.acquired:
            if request_path.is_file():
                return
            await asyncio.sleep(_STOP_POLL_SECONDS)
        raise RuntimeError("The account runtime lock was released before a stop request arrived.")

    def release(self) -> None:
        handle = self._handle
        owner = self._owner
        self._handle = None
        self._owner = None
        if handle is None:
            return
        if owner is not None and owner.instance_id is not None:
            with suppress(OSError):
                _stop_request_path(self._path, owner.instance_id).unlink()
        # Closing is the portable release primitive. It also avoids an unlock-before-close
        # window in which another process could acquire while this handle remained live.
        handle.close()

    def _write_owner(self, owner: AccountRuntimeOwner) -> None:
        handle = self._handle
        if handle is None:
            raise RuntimeError("The account runtime lock is not owned by this process.")
        payload = (json.dumps(asdict(owner), sort_keys=True) + "\n").encode()
        handle.seek(0)
        handle.truncate()
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def claim_account_runtime(
    settings: Settings,
    *,
    command: str,
) -> Generator[AccountProcessLock, None, None]:
    """Claim exclusive access to the configured account profile."""

    lock = AccountProcessLock(
        settings.runtime_lock_path,
        account_id=settings.account_id,
        command=command,
    )
    lock.acquire()
    try:
        yield lock
    finally:
        lock.release()


async def run_owned_operation[ResultT](
    settings: Settings,
    *,
    command: str,
    operation: Callable[[], Awaitable[ResultT]],
) -> ResultT:
    """Run one profile operation while excluding the shared MCP host."""

    with claim_account_runtime(settings, command=command) as process_lock:
        operation_task = asyncio.ensure_future(operation())
        stop_task = asyncio.create_task(_wait_for_owned_operation_stop(process_lock))
        try:
            done, _ = await asyncio.wait(
                (operation_task, stop_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if operation_task in done:
                return await operation_task

            reason = await stop_task
            if operation_task.done():
                return await operation_task
            operation_task.cancel()
            await asyncio.gather(operation_task, return_exceptions=True)
            raise RuntimeError(f"The {command} operation was interrupted by {reason}.")
        finally:
            if not operation_task.done():
                operation_task.cancel()
            if not stop_task.done():
                stop_task.cancel()
            await asyncio.gather(operation_task, stop_task, return_exceptions=True)


async def _wait_for_stop_signal() -> signal.Signals:
    """Wait for a console stop signal using APIs available on every supported OS."""

    loop = asyncio.get_running_loop()
    received: asyncio.Future[signal.Signals] = loop.create_future()

    def receive(signum: int, _: FrameType | None) -> None:
        if not received.done():
            received.set_result(signal.Signals(signum))

    watched = (signal.SIGINT, signal.SIGTERM)
    previous = {watched_signal: signal.getsignal(watched_signal) for watched_signal in watched}
    try:
        for watched_signal in watched:
            signal.signal(watched_signal, receive)
        return await received
    finally:
        for watched_signal, handler in previous.items():
            signal.signal(watched_signal, handler)


async def _wait_for_owned_operation_stop(process_lock: AccountProcessLock) -> str:
    request_task = asyncio.create_task(process_lock.wait_for_stop_request())
    signal_task = asyncio.create_task(_wait_for_stop_signal())
    try:
        done, _ = await asyncio.wait(
            (request_task, signal_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if signal_task in done:
            return (await signal_task).name
        await request_task
        return "a graceful stop request"
    finally:
        for task in (request_task, signal_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(request_task, signal_task, return_exceptions=True)


def inspect_account_runtime(path: Path) -> AccountRuntimeStatus:
    """Inspect a runtime lock without acquiring ownership or starting Chromium."""

    try:
        handle = _open_lock_file(path, create=False)
    except FileNotFoundError:
        return AccountRuntimeStatus(running=False)
    except OSError as error:
        raise ConfigurationError("The LinkedIn runtime lock could not be inspected.") from error

    with handle:
        try:
            acquired = _try_lock(handle.fileno())
        except OSError as error:
            raise ConfigurationError("The LinkedIn runtime lock could not be inspected.") from error
        if acquired:
            return AccountRuntimeStatus(running=False)
        return AccountRuntimeStatus(
            running=True,
            owner=_read_owner(handle),
        )


def stop_account_runtime(
    path: Path,
    *,
    timeout_seconds: float = 30.0,
) -> AccountRuntimeStatus:
    """Ask the exact lock-owning process to stop and wait for lock release."""

    if not 0.1 <= timeout_seconds <= 300:
        raise ValueError("Runtime stop timeout must be between 0.1 and 300 seconds.")
    initial = inspect_account_runtime(path)
    if not initial.running:
        return initial
    owner = initial.owner
    if owner is None or owner.instance_id is None:
        raise ConfigurationError(
            "The active LinkedIn runtime did not expose a valid owner identity; it was not stopped."
        )
    if owner.pid == os.getpid():
        raise ConfigurationError("The LinkedIn runtime cannot stop itself through this command.")

    confirmed = inspect_account_runtime(path)
    if not confirmed.running or confirmed.owner != owner:
        raise ConfigurationError(
            "LinkedIn runtime ownership changed while stop was being requested; retry status first."
        )
    if owner.stop_protocol == _STOP_PROTOCOL:
        try:
            _publish_stop_request(path, owner.instance_id)
        except OSError as error:
            raise ConfigurationError(
                "The LinkedIn runtime could not be asked to stop safely."
            ) from error
    elif os.name == "nt":
        raise ConfigurationError(
            "The active LinkedIn runtime predates native Windows shutdown support. Close that "
            "process once, then start the current version."
        )
    else:
        _signal_legacy_posix_owner(owner.pid)

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = inspect_account_runtime(path)
        if not status.running:
            return AccountRuntimeStatus(running=False, owner=owner)
        if status.owner != owner:
            raise ConfigurationError(
                "A different LinkedIn runtime acquired the profile while stop was waiting."
            )
        time.sleep(_STOP_POLL_SECONDS)
    raise ConfigurationError(
        "The LinkedIn runtime is still stopping. No force-kill was attempted; retry status shortly."
    )


def _open_lock_file(path: Path, *, create: bool) -> BinaryIO:
    flags = os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    if create:
        flags |= os.O_CREAT
    descriptor = os.open(path, flags, 0o600)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        os.set_inheritable(descriptor, False)
        return cast(BinaryIO, os.fdopen(descriptor, "r+b", buffering=0))
    except BaseException:
        os.close(descriptor)
        raise


def _try_lock(descriptor: int) -> bool:
    if os.name == "nt":
        return _try_windows_lock(descriptor)
    return _try_posix_lock(descriptor)


def _try_posix_lock(descriptor: int) -> bool:
    try:
        module = import_module("fcntl")
    except ImportError as error:
        raise OSError("This POSIX platform does not provide advisory file locking.") from error
    flock = cast(Callable[[int, int], None], module.__dict__["flock"])
    exclusive = cast(int, module.__dict__["LOCK_EX"])
    nonblocking = cast(int, module.__dict__["LOCK_NB"])
    try:
        flock(descriptor, exclusive | nonblocking)
    except OSError as error:
        if error.errno in _CONTENTION_ERRNOS:
            return False
        raise
    return True


def _try_windows_lock(descriptor: int) -> bool:
    try:
        module = import_module("msvcrt")
    except ImportError as error:
        raise OSError("This Windows runtime does not provide byte-range file locking.") from error
    locking = cast(Callable[[int, int, int], None], module.__dict__["locking"])
    nonblocking = cast(int, module.__dict__["LK_NBLCK"])
    os.lseek(descriptor, _WINDOWS_LOCK_OFFSET, os.SEEK_SET)
    try:
        locking(descriptor, nonblocking, _LOCK_BYTES)
    except OSError as error:
        windows_error = cast(int | None, getattr(error, "winerror", None))
        if error.errno in _CONTENTION_ERRNOS or windows_error == _WINDOWS_LOCK_VIOLATION:
            return False
        raise
    return True


def _read_owner(handle: BinaryIO) -> AccountRuntimeOwner | None:
    handle.seek(0)
    payload = handle.read(_MAX_OWNER_BYTES + 1)
    if len(payload) > _MAX_OWNER_BYTES:
        return None
    try:
        return _parse_owner(payload.decode("utf-8"))
    except UnicodeDecodeError:
        return None


def _publish_stop_request(lock_path: Path, instance_id: str) -> None:
    request_path = _stop_request_path(lock_path, instance_id)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(request_path, flags, 0o600)
    except FileExistsError:
        return
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        os.write(descriptor, b"stop\n")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _signal_legacy_posix_owner(pid: int) -> None:
    """Gracefully stop a pre-file-protocol POSIX owner during package upgrades."""

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError as error:
        raise ConfigurationError(
            "The LinkedIn runtime belongs to a process this user cannot stop."
        ) from error
    except OSError as error:
        raise ConfigurationError("The LinkedIn runtime could not be stopped safely.") from error


def _stop_request_path(lock_path: Path, instance_id: str) -> Path:
    digest = hashlib.sha256(instance_id.encode()).hexdigest()
    return lock_path.with_name(f"{lock_path.name}.stop-{digest}")


def _clear_stale_stop_requests(lock_path: Path) -> None:
    prefix = f"{lock_path.name}.stop-"
    try:
        siblings = tuple(lock_path.parent.iterdir())
    except OSError:
        return
    for sibling in siblings:
        if sibling.name.startswith(prefix):
            with suppress(OSError):
                sibling.unlink()


def _harden_directory(path: Path) -> None:
    if os.name != "nt":
        with suppress(OSError):
            path.chmod(0o700)


def _parse_owner(value: str) -> AccountRuntimeOwner | None:
    text = value.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    payload = cast(dict[str, object], payload)
    pid = payload.get("pid")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        return None
    return AccountRuntimeOwner(
        pid=pid,
        instance_id=_optional_string(payload.get("instance_id")),
        account_id=_optional_string(payload.get("account_id")),
        command=_optional_string(payload.get("command")),
        transport=_optional_string(payload.get("transport")),
        started_at=_optional_string(payload.get("started_at")),
        endpoint=_optional_string(payload.get("endpoint")),
        version=_optional_string(payload.get("version")),
        configuration_fingerprint=_optional_string(payload.get("configuration_fingerprint")),
        stop_protocol=_optional_string(payload.get("stop_protocol")),
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
