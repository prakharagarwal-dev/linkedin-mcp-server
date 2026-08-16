from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from linkedin_mcp.application import (
    AccountProcessLock,
    inspect_account_runtime,
    stop_account_runtime,
)
from linkedin_mcp.config import Settings
from linkedin_mcp.container import create_production_container
from linkedin_mcp.domain.models import CapabilityName
from linkedin_mcp.errors import ConfigurationError


@pytest.mark.asyncio
async def test_production_container_composes_and_closes_without_connecting() -> None:
    container = create_production_container(Settings())

    assert container.registry.get(CapabilityName.JOBS_SEARCH).version == "3.0.0"
    assert container.registry.get(CapabilityName.PEOPLE_SEARCH).version == "3.0.0"
    assert container.registry.get(CapabilityName.PEOPLE_GET).version == "1.1.1"
    assert container.registry.get(CapabilityName.COMPANIES_SEARCH).version == "3.0.0"
    assert container.registry.get(CapabilityName.COMPANIES_GET).version == "2.0.0"
    assert container.registry.get(CapabilityName.POSTS_SEARCH).version == "3.0.0"
    assert container.registry.get(CapabilityName.POSTS_GET).version == "2.0.0"
    assert container.registry.get(CapabilityName.POST_COMMENTS_LIST).version == "2.0.0"
    assert container.registry.get(CapabilityName.INVITATIONS_LIST).version == "5.1.0"
    assert container.registry.get(CapabilityName.CONNECTIONS_LIST).version == "3.0.0"
    assert container.registry.get(CapabilityName.CONNECTIONS_SEARCH).version == "3.0.0"
    assert container.registry.get(CapabilityName.POSTS_CREATE).version == "4.0.0"
    assert container.registry.get(CapabilityName.POST_COMMENT).version == "4.0.0"
    assert container.registry.get(CapabilityName.POST_REACT).version == "4.0.0"
    assert container.registry.get(CapabilityName.INVITATION_SEND).version == "3.0.0"
    assert container.registry.get(CapabilityName.INVITATION_ACCEPT).version == "2.0.0"
    assert container.registry.get(CapabilityName.INVITATION_IGNORE).version == "2.0.0"
    assert container.registry.get(CapabilityName.MESSAGING_CONVERSATION_GET).version == "2.0.0"
    assert container.registry.get(CapabilityName.MESSAGING_SEARCH).version == "3.0.0"
    assert container.registry.get(CapabilityName.MESSAGING_SEND).version == "3.0.0"
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
        assert status.owner.instance_id
        assert status.owner.started_at
        assert payload["pid"] == os.getpid()
        if os.name != "nt":
            assert path.stat().st_mode & 0o077 == 0
    finally:
        lock.release()

    assert inspect_account_runtime(path).running is False


def test_runtime_stop_is_idempotent_and_refuses_unidentified_owner(tmp_path: Path) -> None:
    path = tmp_path / "runtime.lock"
    assert stop_account_runtime(path).running is False

    with path.open("w+", encoding="utf-8") as handle:
        handle.write("not-valid-owner-metadata\n")
        handle.flush()
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        with pytest.raises(ConfigurationError, match="valid owner PID"):
            stop_account_runtime(path, timeout_seconds=0.1)


@pytest.mark.timeout(10)
def test_runtime_stop_terminates_only_the_exact_lock_owner(tmp_path: Path) -> None:
    path = tmp_path / "runtime.lock"
    program = """
import signal
import sys
import time
from pathlib import Path
from linkedin_mcp.application import AccountProcessLock

lock = AccountProcessLock(Path(sys.argv[1]), account_id="personal", transport="stdio")
lock.acquire()
signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
print("ready", flush=True)
while True:
    time.sleep(1)
"""
    child = subprocess.Popen(
        [sys.executable, "-c", program, str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "ready"
        before = inspect_account_runtime(path)

        result = stop_account_runtime(path, timeout_seconds=5)
        child.wait(timeout=5)

        assert before.running is True
        assert before.owner is not None
        assert before.owner.pid == child.pid
        assert result.running is False
        assert result.owner == before.owner
        assert child.returncode == 0
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=5)
