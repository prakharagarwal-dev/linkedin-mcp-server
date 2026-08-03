from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

import linkedin_mcp.application.shared_runtime as shared_runtime
from linkedin_mcp.application import AccountRuntimeOwner, AccountRuntimeStatus
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import ConfigurationError


def test_shared_runtime_endpoint_is_deterministic_and_loopback_only(tmp_path: Path) -> None:
    assert (
        shared_runtime.shared_runtime_endpoint(
            Settings(
                http_host="localhost",
                http_port=8123,
                runtime_lock_path=tmp_path / "runtime.lock",
            )
        )
        == "http://127.0.0.1:8123/mcp"
    )
    assert (
        shared_runtime.shared_runtime_endpoint(
            Settings(
                http_host="::1",
                http_port=8124,
                runtime_lock_path=tmp_path / "runtime-v6.lock",
            )
        )
        == "http://[::1]:8124/mcp"
    )

    unsafe = Settings(
        transport="stdio",
        http_host="0.0.0.0",
        runtime_lock_path=tmp_path / "unsafe.lock",
    )
    with pytest.raises(ConfigurationError, match="loopback"):
        shared_runtime.shared_runtime_endpoint(unsafe)


@pytest.mark.parametrize(
    "endpoint",
    (
        "https://127.0.0.1:8000/mcp",
        "http://example.com:8000/mcp",
        "http://127.0.0.1:8000/not-mcp",
        "http://user@127.0.0.1:8000/mcp",
        "http://127.0.0.1:8000/mcp?token=secret",
    ),
)
def test_published_runtime_endpoint_validation_fails_closed(endpoint: str) -> None:
    with pytest.raises(ConfigurationError, match="loopback"):
        shared_runtime.validate_shared_runtime_endpoint(endpoint)


@pytest.mark.asyncio
async def test_existing_healthy_runtime_is_reused_without_spawning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(runtime_lock_path=tmp_path / "runtime.lock")
    endpoint = "http://127.0.0.1:8000/mcp"
    status = AccountRuntimeStatus(
        running=True,
        owner=AccountRuntimeOwner(
            pid=4321,
            command="_runtime",
            endpoint=endpoint,
            version=shared_runtime.__version__,
            account_id=settings.account_id,
            configuration_fingerprint=shared_runtime.runtime_configuration_fingerprint(settings),
        ),
    )

    def inspect(_: Path) -> AccountRuntimeStatus:
        return status

    monkeypatch.setattr(shared_runtime, "inspect_account_runtime", inspect)

    async def healthy(_: AccountRuntimeStatus) -> str:
        return endpoint

    monkeypatch.setattr(shared_runtime, "_healthy_endpoint", healthy)

    def unexpected_spawn(_: Settings) -> Any:
        raise AssertionError("A healthy runtime must not spawn another owner.")

    monkeypatch.setattr(shared_runtime, "_spawn_shared_runtime", unexpected_spawn)

    assert await shared_runtime.ensure_shared_runtime(settings) == endpoint


@pytest.mark.asyncio
async def test_runtime_wait_rejects_exclusive_profile_maintenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(runtime_lock_path=tmp_path / "runtime.lock")
    status = AccountRuntimeStatus(
        running=True,
        owner=AccountRuntimeOwner(pid=4321, command="login", account_id=settings.account_id),
    )

    def inspect(_: Path) -> AccountRuntimeStatus:
        return status

    monkeypatch.setattr(shared_runtime, "inspect_account_runtime", inspect)

    async def unavailable(_: AccountRuntimeStatus) -> None:
        return None

    monkeypatch.setattr(shared_runtime, "_healthy_endpoint", unavailable)

    with pytest.raises(ConfigurationError, match=r"maintenance or a legacy runtime \(login\)"):
        await shared_runtime.wait_for_shared_runtime(settings)


@pytest.mark.asyncio
async def test_runtime_wait_rejects_an_incompatible_owner_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(runtime_lock_path=tmp_path / "runtime.lock")
    status = AccountRuntimeStatus(
        running=True,
        owner=AccountRuntimeOwner(
            pid=4321,
            command="_runtime",
            version="0.1.0",
            endpoint="http://127.0.0.1:8000/mcp",
            account_id=settings.account_id,
        ),
    )

    def inspect(_: Path) -> AccountRuntimeStatus:
        return status

    monkeypatch.setattr(shared_runtime, "inspect_account_runtime", inspect)

    with pytest.raises(ConfigurationError, match="this client uses"):
        await shared_runtime.wait_for_shared_runtime(settings)


@pytest.mark.asyncio
async def test_runtime_wait_rejects_different_effective_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(runtime_lock_path=tmp_path / "runtime.lock")
    status = AccountRuntimeStatus(
        running=True,
        owner=AccountRuntimeOwner(
            pid=4321,
            command="_runtime",
            version=shared_runtime.__version__,
            endpoint="http://127.0.0.1:8000/mcp",
            account_id=settings.account_id,
            configuration_fingerprint="0" * 64,
        ),
    )

    def inspect(_: Path) -> AccountRuntimeStatus:
        return status

    monkeypatch.setattr(shared_runtime, "inspect_account_runtime", inspect)

    with pytest.raises(ConfigurationError, match="different profile, authorization"):
        await shared_runtime.wait_for_shared_runtime(settings)


@pytest.mark.asyncio
async def test_runtime_wait_reports_background_start_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(runtime_lock_path=tmp_path / "runtime.lock")

    def inspect(_: Path) -> AccountRuntimeStatus:
        return AccountRuntimeStatus(running=False)

    monkeypatch.setattr(shared_runtime, "inspect_account_runtime", inspect)

    async def unavailable(_: AccountRuntimeStatus) -> None:
        return None

    class FailedStarter:
        @staticmethod
        def poll() -> int:
            return 1

    monkeypatch.setattr(shared_runtime, "_healthy_endpoint", unavailable)

    with pytest.raises(ConfigurationError, match="failed during startup"):
        await shared_runtime.wait_for_shared_runtime(
            settings,
            starter=cast(Any, FailedStarter()),
        )
