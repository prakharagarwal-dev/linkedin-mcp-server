from __future__ import annotations

import asyncio
import errno
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

import linkedin_mcp.runtime.ownership as process_lock_module
from linkedin_mcp.app.container import create_production_container
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import ConfigurationError
from linkedin_mcp.runtime import (
    AccountProcessLock,
    AccountRuntimeOwner,
    AccountRuntimeStatus,
    inspect_account_runtime,
    stop_account_runtime,
)


@pytest.mark.asyncio
async def test_production_container_composes_and_closes_without_connecting() -> None:
    container = create_production_container(Settings())

    assert container.browser.started is False

    await container.close()


def test_account_process_lock_rejects_a_second_local_server(tmp_path: Path) -> None:
    path = tmp_path / "runtime.lock"
    first = AccountProcessLock(path)
    second = AccountProcessLock(path)

    first.acquire()
    with pytest.raises(ConfigurationError, match="already owns"):
        second.acquire()
    first.release()

    second.acquire()
    assert second.acquired is True
    second.release()


def test_account_process_lock_publishes_non_secret_runtime_metadata(tmp_path: Path) -> None:
    path = tmp_path / "runtime.lock"
    lock = AccountProcessLock(
        path,
        account_id="personal",
        command="serve",
        transport="stdio",
        version="0.16.0",
        configuration_fingerprint="f" * 64,
    )

    lock.acquire()
    try:
        lock.publish_endpoint("http://127.0.0.1:8000/mcp")
        status = inspect_account_runtime(path)
        payload = json.loads(path.read_text(encoding="utf-8"))

        assert status.running is True
        assert status.owner is not None
        assert status.owner.pid == os.getpid()
        assert status.owner.account_id == "personal"
        assert status.owner.command == "serve"
        assert status.owner.transport == "stdio"
        assert status.owner.endpoint == "http://127.0.0.1:8000/mcp"
        assert status.owner.version == "0.16.0"
        assert status.owner.configuration_fingerprint == "f" * 64
        assert status.owner.stop_protocol == "file-v1"
        assert status.owner.instance_id
        assert status.owner.started_at
        assert payload["pid"] == os.getpid()
        if os.name != "nt":
            assert path.stat().st_mode & 0o077 == 0
    finally:
        lock.release()

    assert inspect_account_runtime(path).running is False


@pytest.mark.asyncio
async def test_account_process_lock_waits_for_its_exact_stop_request(tmp_path: Path) -> None:
    path = tmp_path / "runtime.lock"
    lock = AccountProcessLock(path)

    with pytest.raises(RuntimeError, match="not owned"):
        _ = lock.owner

    stale = process_lock_module._stop_request_path(  # pyright: ignore[reportPrivateUsage]
        path,
        "stale-owner",
    )
    stale.touch()
    request: Path | None = None
    lock.acquire()
    try:
        owner = lock.owner
        assert lock.path == path
        assert owner.instance_id is not None
        assert stale.exists() is False

        waiter = asyncio.create_task(lock.wait_for_stop_request())
        await asyncio.sleep(0)
        assert waiter.done() is False
        process_lock_module._publish_stop_request(  # pyright: ignore[reportPrivateUsage]
            path,
            owner.instance_id,
        )
        request = process_lock_module._stop_request_path(  # pyright: ignore[reportPrivateUsage]
            path,
            owner.instance_id,
        )
        await asyncio.wait_for(waiter, timeout=1)
    finally:
        lock.release()

    assert request is not None
    assert request.exists() is False


def test_windows_lock_backend_classifies_contention_and_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "windows.lock"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    module = ModuleType("msvcrt")
    calls: list[tuple[int, int, int, int]] = []

    def acquired(fd: int, mode: int, size: int) -> None:
        calls.append((fd, mode, size, os.lseek(fd, 0, os.SEEK_CUR)))

    def import_fake(_: str) -> ModuleType:
        return module

    module.__dict__.update({"LK_NBLCK": 7, "locking": acquired})
    monkeypatch.setattr(process_lock_module, "import_module", import_fake)
    try:
        assert process_lock_module._try_windows_lock(  # pyright: ignore[reportPrivateUsage]
            descriptor
        )
        assert calls == [(descriptor, 7, 1, 0x7FFF_FFFE)]

        def contended(_: int, __: int, ___: int) -> None:
            raise OSError(errno.EACCES, "locked")

        module.__dict__["locking"] = contended
        assert not process_lock_module._try_windows_lock(  # pyright: ignore[reportPrivateUsage]
            descriptor
        )

        def failed(_: int, __: int, ___: int) -> None:
            raise OSError(errno.EINVAL, "invalid")

        module.__dict__["locking"] = failed
        with pytest.raises(OSError, match="invalid"):
            process_lock_module._try_windows_lock(  # pyright: ignore[reportPrivateUsage]
                descriptor
            )

        def unavailable(_: str) -> ModuleType:
            raise ImportError("missing")

        monkeypatch.setattr(process_lock_module, "import_module", unavailable)
        with pytest.raises(OSError, match="does not provide"):
            process_lock_module._try_windows_lock(  # pyright: ignore[reportPrivateUsage]
                descriptor
            )
    finally:
        os.close(descriptor)


@pytest.mark.skipif(os.name == "nt", reason="Legacy shutdown signals are POSIX-only")
def test_runtime_stop_supports_a_legacy_posix_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = AccountRuntimeOwner(pid=4321, instance_id="legacy-instance")
    statuses = iter(
        (
            AccountRuntimeStatus(running=True, owner=owner),
            AccountRuntimeStatus(running=True, owner=owner),
            AccountRuntimeStatus(running=False),
        )
    )

    def inspect(_: Path) -> AccountRuntimeStatus:
        return next(statuses)

    signaled: list[tuple[int, int]] = []

    def kill(pid: int, sent_signal: int) -> None:
        signaled.append((pid, sent_signal))

    monkeypatch.setattr(process_lock_module, "inspect_account_runtime", inspect)
    monkeypatch.setattr(process_lock_module.os, "kill", kill)

    result = stop_account_runtime(tmp_path / "runtime.lock", timeout_seconds=1)

    assert result == AccountRuntimeStatus(running=False, owner=owner)
    assert signaled == [(owner.pid, signal.SIGTERM)]


def test_runtime_stop_is_idempotent_and_refuses_unidentified_owner(tmp_path: Path) -> None:
    path = tmp_path / "runtime.lock"
    assert stop_account_runtime(path).running is False

    lock = AccountProcessLock(path)
    lock.acquire()
    try:
        path.write_text("not-valid-owner-metadata\n", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="valid owner identity"):
            stop_account_runtime(path, timeout_seconds=0.1)
    finally:
        lock.release()


@pytest.mark.timeout(10)
def test_runtime_stop_requests_only_the_exact_lock_owner(tmp_path: Path) -> None:
    path = tmp_path / "runtime.lock"
    program = """
import asyncio
import os
import sys
from pathlib import Path
from linkedin_mcp.runtime import AccountProcessLock

lock = AccountProcessLock(Path(sys.argv[1]), account_id="personal", transport="stdio")
lock.acquire()
print(f"ready:{os.getpid()}", flush=True)
asyncio.run(lock.wait_for_stop_request())
lock.release()
"""
    child = subprocess.Popen(
        [sys.executable, "-c", program, str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        ready, owner_pid = child.stdout.readline().strip().split(":", 1)
        assert ready == "ready"
        before = inspect_account_runtime(path)

        result = stop_account_runtime(path, timeout_seconds=5)
        child.wait(timeout=5)

        assert before.running is True
        assert before.owner is not None
        assert before.owner.pid == int(owner_pid)
        assert result.running is False
        assert result.owner == before.owner
        assert child.returncode == 0
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
