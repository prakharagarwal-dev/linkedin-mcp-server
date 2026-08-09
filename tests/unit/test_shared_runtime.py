from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
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


def test_malformed_runtime_endpoint_is_reported_as_configuration_error() -> None:
    with pytest.raises(ConfigurationError, match="invalid endpoint"):
        shared_runtime.validate_shared_runtime_endpoint("http://[::1")


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


@pytest.mark.asyncio
async def test_runtime_wait_returns_health_and_reports_owner_on_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        runtime_lock_path=tmp_path / "runtime.lock",
        runtime_start_timeout_seconds=1,
    )
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
    assert await shared_runtime.wait_for_shared_runtime(settings) == endpoint

    async def unhealthy(_: AccountRuntimeStatus) -> None:
        return None

    monotonic_values = iter((0.0, 0.0, 2.0))

    def monotonic() -> float:
        return next(monotonic_values, 2.0)

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(shared_runtime, "_healthy_endpoint", unhealthy)
    monkeypatch.setattr(shared_runtime, "time", SimpleNamespace(monotonic=monotonic))
    monkeypatch.setattr(shared_runtime.asyncio, "sleep", no_sleep)

    with pytest.raises(ConfigurationError, match="current owner command is '_runtime'"):
        await shared_runtime.wait_for_shared_runtime(settings)


@pytest.mark.asyncio
async def test_unowned_runtime_is_spawned_then_awaited(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(runtime_lock_path=tmp_path / "runtime.lock")
    starter = object()
    endpoint = "http://127.0.0.1:8000/mcp"

    def inspect(_: Path) -> AccountRuntimeStatus:
        return AccountRuntimeStatus(running=False)

    def spawn(_: Settings) -> object:
        return starter

    monkeypatch.setattr(shared_runtime, "inspect_account_runtime", inspect)
    monkeypatch.setattr(shared_runtime, "_spawn_shared_runtime", spawn)

    async def wait(_: Settings, *, starter: object | None = None) -> str:
        assert starter is not None
        return endpoint

    monkeypatch.setattr(shared_runtime, "wait_for_shared_runtime", wait)

    assert await shared_runtime.ensure_shared_runtime(settings) == endpoint


@pytest.mark.asyncio
async def test_running_runtime_without_health_waits_for_existing_owner(
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

    async def unhealthy(_: AccountRuntimeStatus) -> None:
        return None

    async def wait(_: Settings, *, starter: object | None = None) -> str:
        assert starter is None
        return endpoint

    monkeypatch.setattr(shared_runtime, "_healthy_endpoint", unhealthy)
    monkeypatch.setattr(shared_runtime, "wait_for_shared_runtime", wait)

    assert await shared_runtime.ensure_shared_runtime(settings) == endpoint


@pytest.mark.asyncio
async def test_runtime_health_and_status_use_only_validated_loopback_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []
    result = SimpleNamespace(
        isError=False,
        structuredContent={"accepting_calls": True},
    )

    @asynccontextmanager
    async def fake_http_client(endpoint: str) -> AsyncGenerator[tuple[str, str, None]]:
        events.append(("http", endpoint))
        yield ("read", "write", None)

    class FakeSession:
        def __init__(self, read: str, write: str, *, client_info: object) -> None:
            events.append(("session", read, write, client_info))

        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def initialize(self) -> None:
            events.append("initialize")

        async def send_ping(self) -> None:
            events.append("ping")

        async def call_tool(self, name: str, arguments: dict[str, object]) -> object:
            events.append(("call_tool", name, arguments))
            return result

    monkeypatch.setattr(shared_runtime, "streamable_http_client", fake_http_client)
    monkeypatch.setattr(shared_runtime, "ClientSession", FakeSession)

    endpoint = "http://127.0.0.1:8000/mcp"
    assert await shared_runtime.runtime_is_healthy(endpoint) is True
    assert await shared_runtime.read_shared_runtime_status(endpoint) == {"accepting_calls": True}
    assert "ping" in events
    assert ("call_tool", "linkedin.server.status", {}) in events
    assert await shared_runtime.runtime_is_healthy("https://example.com/mcp") is False
    assert await shared_runtime.read_shared_runtime_status("https://example.com/mcp") is None

    result.isError = True
    assert await shared_runtime.read_shared_runtime_status(endpoint) is None
    result.isError = False
    result.structuredContent = None
    assert await shared_runtime.read_shared_runtime_status(endpoint) is None


@pytest.mark.asyncio
async def test_healthy_endpoint_requires_running_owner_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (
        await shared_runtime._healthy_endpoint(  # pyright: ignore[reportPrivateUsage]
            AccountRuntimeStatus(running=False)
        )
        is None
    )
    assert (
        await shared_runtime._healthy_endpoint(  # pyright: ignore[reportPrivateUsage]
            AccountRuntimeStatus(
                running=True,
                owner=AccountRuntimeOwner(pid=4321, command="_runtime"),
            )
        )
        is None
    )

    async def healthy(_: str, *, timeout_seconds: float = 2.0) -> bool:
        assert timeout_seconds == 2.0
        return True

    monkeypatch.setattr(shared_runtime, "runtime_is_healthy", healthy)
    endpoint = "http://127.0.0.1:8000/mcp"
    assert (
        await shared_runtime._healthy_endpoint(  # pyright: ignore[reportPrivateUsage]
            AccountRuntimeStatus(
                running=True,
                owner=AccountRuntimeOwner(
                    pid=4321,
                    command="_runtime",
                    endpoint=endpoint,
                ),
            )
        )
        == endpoint
    )


@pytest.mark.asyncio
async def test_shared_runtime_owns_listener_and_closes_container(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        transport="streamable-http",
        http_port=8123,
        runtime_lock_path=tmp_path / "runtime.lock",
    )
    events: list[object] = []

    class FakeLock:
        def __init__(self, path: Path, **values: object) -> None:
            events.append(("lock", path, values))

        def publish_endpoint(self, endpoint: str) -> None:
            events.append(("publish", endpoint))

    class FakeContainer:
        process_lock: object | None = None

        async def start(self) -> None:
            events.append("start")

        async def close(self) -> None:
            events.append("close")

    class FakeListener:
        def close(self) -> None:
            events.append("listener-close")

    class FakeMCP:
        def streamable_http_app(self) -> str:
            return "application"

    class FakeServer:
        def __init__(self, config: object) -> None:
            events.append(("server", config))

        async def serve(self, *, sockets: list[object]) -> None:
            events.append(("serve", sockets))

    container = FakeContainer()
    listener = FakeListener()

    def create_container(_: Settings) -> object:
        return container

    def bind_listener(_: str, __: int) -> object:
        return listener

    def create_server(_: object, *, manage_container_lifecycle: bool) -> object:
        assert manage_container_lifecycle is False
        return FakeMCP()

    def create_config(app: object, **values: object) -> object:
        return (app, values)

    monkeypatch.setattr(shared_runtime, "create_production_container", create_container)
    monkeypatch.setattr(shared_runtime, "AccountProcessLock", FakeLock)
    monkeypatch.setattr(shared_runtime, "_bind_listener", bind_listener)
    monkeypatch.setattr(shared_runtime, "create_mcp_server", create_server)
    monkeypatch.setattr(shared_runtime.uvicorn, "Config", create_config)
    monkeypatch.setattr(shared_runtime.uvicorn, "Server", FakeServer)

    await shared_runtime.run_shared_runtime(settings)

    assert events[0] == (
        "lock",
        settings.runtime_lock_path,
        {
            "account_id": settings.account_id,
            "command": "_runtime",
            "transport": "shared-loopback",
            "version": shared_runtime.__version__,
            "configuration_fingerprint": shared_runtime.runtime_configuration_fingerprint(settings),
        },
    )
    assert "start" in events
    assert ("publish", "http://127.0.0.1:8123/mcp") in events
    assert ("serve", [listener]) in events
    assert events[-2:] == ["listener-close", "close"]


def test_runtime_spawn_owner_validation_and_listener_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(runtime_lock_path=tmp_path / "runtime.lock")
    popen_calls: list[tuple[object, object]] = []
    process = object()

    def fake_popen(command: object, **values: object) -> object:
        popen_calls.append((command, values))
        return process

    monkeypatch.setattr(shared_runtime.subprocess, "Popen", fake_popen)

    assert shared_runtime._spawn_shared_runtime(settings) is process  # pyright: ignore[reportPrivateUsage]
    assert popen_calls[0][0] == [
        shared_runtime.sys.executable,
        "-m",
        "linkedin_mcp",
        "_runtime",
    ]
    assert shared_runtime._runtime_log_path(settings) == tmp_path / "runtime.log"  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(ConfigurationError, match="without valid runtime metadata"):
        shared_runtime._validate_running_owner(  # pyright: ignore[reportPrivateUsage]
            AccountRuntimeStatus(running=True),
            settings,
        )

    wrong_account = AccountRuntimeOwner(
        pid=4321,
        command="_runtime",
        version=shared_runtime.__version__,
        account_id="work",
        configuration_fingerprint=shared_runtime.runtime_configuration_fingerprint(settings),
    )
    with pytest.raises(ConfigurationError, match="owns account work"):
        shared_runtime._validate_running_owner(  # pyright: ignore[reportPrivateUsage]
            AccountRuntimeStatus(running=True, owner=wrong_account),
            settings,
        )

    listener = shared_runtime._bind_listener("127.0.0.1", 0)  # pyright: ignore[reportPrivateUsage]
    try:
        assert listener.getsockname()[0] == "127.0.0.1"
    finally:
        listener.close()


def test_listener_closes_when_binding_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    class FailedListener:
        def setsockopt(self, *_: object) -> None:
            events.append("setsockopt")

        def bind(self, _: object) -> None:
            raise OSError("address unavailable")

        def close(self) -> None:
            events.append("close")

    def create_socket(_: int, __: int) -> FailedListener:
        return FailedListener()

    monkeypatch.setattr(shared_runtime.socket, "socket", create_socket)

    with pytest.raises(OSError, match="address unavailable"):
        shared_runtime._bind_listener(  # pyright: ignore[reportPrivateUsage]
            "127.0.0.1",
            8123,
        )
    assert events == ["setsockopt", "close"]
