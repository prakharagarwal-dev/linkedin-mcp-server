from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any, cast

import anyio
import pytest
import uvicorn

import linkedin_mcp.runtime.shared as shared_runtime
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import ConfigurationError
from linkedin_mcp.mcp.server import create_mcp_server
from linkedin_mcp.runtime import AccountRuntimeOwner, AccountRuntimeStatus
from tests.contract.test_mcp_protocol import protocol_container


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
async def test_ensure_waits_for_new_lock_owner_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(runtime_lock_path=tmp_path / "runtime.lock")
    endpoint = "http://127.0.0.1:8000/mcp"

    def starting(_: Path) -> AccountRuntimeStatus:
        return AccountRuntimeStatus(running=True)

    monkeypatch.setattr(shared_runtime, "inspect_account_runtime", starting)

    async def wait(_: Settings, *, starter: Any = None) -> str:
        assert starter is None
        return endpoint

    monkeypatch.setattr(shared_runtime, "wait_for_shared_runtime", wait)

    def unexpected_spawn(_: Settings) -> Any:
        raise AssertionError("A held runtime lock must not spawn another owner.")

    monkeypatch.setattr(shared_runtime, "_spawn_shared_runtime", unexpected_spawn)
    assert await shared_runtime.ensure_shared_runtime(settings) == endpoint


@pytest.mark.asyncio
async def test_runtime_wait_tolerates_owner_metadata_publication_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(runtime_lock_path=tmp_path / "runtime.lock")
    endpoint = "http://127.0.0.1:8000/mcp"
    owner = AccountRuntimeOwner(
        pid=4321,
        command="_runtime",
        endpoint=endpoint,
        version=shared_runtime.__version__,
        account_id=settings.account_id,
        configuration_fingerprint=shared_runtime.runtime_configuration_fingerprint(settings),
    )
    statuses = iter(
        (
            AccountRuntimeStatus(running=True),
            AccountRuntimeStatus(running=True, owner=owner),
        )
    )

    def inspect(_: Path) -> AccountRuntimeStatus:
        return next(statuses)

    async def healthy(status: AccountRuntimeStatus) -> str | None:
        return endpoint if status.owner is owner else None

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(shared_runtime, "inspect_account_runtime", inspect)
    monkeypatch.setattr(shared_runtime, "_healthy_endpoint", healthy)
    monkeypatch.setattr(shared_runtime.asyncio, "sleep", no_sleep)
    assert await shared_runtime.wait_for_shared_runtime(settings) == endpoint


@pytest.mark.asyncio
async def test_runtime_wait_rejects_persistently_missing_owner_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        runtime_lock_path=tmp_path / "runtime.lock",
        runtime_start_timeout_seconds=10,
    )

    def missing(_: Path) -> AccountRuntimeStatus:
        return AccountRuntimeStatus(running=True)

    async def no_sleep(_: float) -> None:
        return None

    class FakeTime:
        values = iter((0.0, 0.1, 6.0))

        @classmethod
        def monotonic(cls) -> float:
            return next(cls.values)

    monkeypatch.setattr(shared_runtime, "inspect_account_runtime", missing)
    monkeypatch.setattr(shared_runtime.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(shared_runtime, "time", FakeTime)

    with pytest.raises(ConfigurationError, match="without valid runtime metadata"):
        await shared_runtime.wait_for_shared_runtime(settings)


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

    with pytest.raises(ConfigurationError, match=r"profile maintenance \(login\)"):
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

    with pytest.raises(ConfigurationError, match="different profile, browser"):
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
async def test_runtime_health_and_status_probe_the_real_mcp_transport(
    tmp_path: Path,
    unused_tcp_port: int,
) -> None:
    mcp = create_mcp_server(protocol_container(tmp_path))
    server = uvicorn.Server(
        uvicorn.Config(
            mcp.streamable_http_app(),
            host="127.0.0.1",
            port=unused_tcp_port,
            log_level="critical",
        )
    )
    endpoint = f"http://127.0.0.1:{unused_tcp_port}/mcp"
    status: dict[str, object] | None = None

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(server.serve)
        for _ in range(200):
            if server.started:
                break
            await anyio.sleep(0.01)
        else:
            raise AssertionError("Shared runtime fixture did not start")
        try:
            assert await shared_runtime.runtime_is_healthy(endpoint)
            status = await shared_runtime.read_shared_runtime_status(endpoint)
        finally:
            server.should_exit = True

    assert status is not None
    assert status["name"] == "linkedin-mcp-server"
    assert await shared_runtime.runtime_is_healthy("https://example.com/mcp") is False
    assert await shared_runtime.read_shared_runtime_status("https://example.com/mcp") is None


@pytest.mark.asyncio
async def test_healthy_endpoint_requires_a_live_published_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = "http://127.0.0.1:8000/mcp"
    owner = AccountRuntimeOwner(pid=4321, command="_runtime", endpoint=endpoint)

    async def healthy(_: str, *, timeout_seconds: float = 2.0) -> bool:
        del timeout_seconds
        return True

    monkeypatch.setattr(shared_runtime, "runtime_is_healthy", healthy)
    assert (
        await shared_runtime._healthy_endpoint(  # pyright: ignore[reportPrivateUsage]
            AccountRuntimeStatus(running=True, owner=owner)
        )
        == endpoint
    )
    assert (
        await shared_runtime._healthy_endpoint(  # pyright: ignore[reportPrivateUsage]
            AccountRuntimeStatus(running=False)
        )
        is None
    )


@pytest.mark.asyncio
async def test_ensure_and_wait_cover_starting_running_and_timeout_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        runtime_lock_path=tmp_path / "runtime.lock",
        runtime_start_timeout_seconds=1,
    )
    endpoint = "http://127.0.0.1:8000/mcp"
    starter = cast(Any, object())

    def stopped(_: Path) -> AccountRuntimeStatus:
        return AccountRuntimeStatus(running=False)

    def spawn(_: Settings) -> Any:
        return starter

    monkeypatch.setattr(shared_runtime, "inspect_account_runtime", stopped)
    monkeypatch.setattr(shared_runtime, "_spawn_shared_runtime", spawn)

    observed_starters: list[Any] = []

    async def wait_started(_: Settings, *, starter: Any = None) -> str:
        observed_starters.append(starter)
        return endpoint

    monkeypatch.setattr(shared_runtime, "wait_for_shared_runtime", wait_started)
    assert await shared_runtime.ensure_shared_runtime(settings) == endpoint

    owner = AccountRuntimeOwner(
        pid=4321,
        command="_runtime",
        endpoint=endpoint,
        version=shared_runtime.__version__,
        account_id=settings.account_id,
        configuration_fingerprint=shared_runtime.runtime_configuration_fingerprint(settings),
    )

    def running(_: Path) -> AccountRuntimeStatus:
        return AccountRuntimeStatus(running=True, owner=owner)

    monkeypatch.setattr(shared_runtime, "inspect_account_runtime", running)

    async def unhealthy(_: AccountRuntimeStatus) -> None:
        return None

    monkeypatch.setattr(shared_runtime, "_healthy_endpoint", unhealthy)
    assert await shared_runtime.ensure_shared_runtime(settings) == endpoint
    assert observed_starters == [starter, None]


@pytest.mark.asyncio
async def test_wait_timeout_reports_the_last_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        runtime_lock_path=tmp_path / "runtime.lock",
        runtime_start_timeout_seconds=1,
    )
    owner = AccountRuntimeOwner(
        pid=4321,
        command="_runtime",
        endpoint="http://127.0.0.1:8000/mcp",
        version=shared_runtime.__version__,
        account_id=settings.account_id,
        configuration_fingerprint=shared_runtime.runtime_configuration_fingerprint(settings),
    )

    def running(_: Path) -> AccountRuntimeStatus:
        return AccountRuntimeStatus(running=True, owner=owner)

    monkeypatch.setattr(shared_runtime, "inspect_account_runtime", running)

    async def unhealthy(_: AccountRuntimeStatus) -> None:
        return None

    async def no_sleep(_: float) -> None:
        return None

    class FakeTime:
        values = iter((0.0, 0.1, 2.0))

        @classmethod
        def monotonic(cls) -> float:
            return next(cls.values)

    monkeypatch.setattr(shared_runtime, "_healthy_endpoint", unhealthy)
    monkeypatch.setattr(shared_runtime.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(shared_runtime, "time", FakeTime)

    with pytest.raises(ConfigurationError, match="current owner command is '_runtime'"):
        await shared_runtime.wait_for_shared_runtime(settings)


@pytest.mark.asyncio
async def test_run_shared_runtime_owns_and_closes_its_listener(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeLock:
        def __init__(self, *_: object, **__: object) -> None:
            events.append("lock-created")

        def publish_endpoint(self, endpoint: str) -> None:
            events.append(f"published:{endpoint}")

        async def wait_for_stop_request(self) -> None:
            await asyncio.Event().wait()

    class FakeContainer:
        process_lock: Any = None

        async def start(self) -> None:
            events.append("started")

        async def close(self) -> None:
            events.append("closed")

    class FakeListener:
        def close(self) -> None:
            events.append("listener-closed")

    class FakeMcp:
        @staticmethod
        def streamable_http_app() -> object:
            return object()

    class FakeServer:
        def __init__(self, _: object) -> None:
            events.append("server-created")

        async def serve(self, *, sockets: list[FakeListener]) -> None:
            assert len(sockets) == 1
            events.append("served")

    container = FakeContainer()

    def fake_container(_: Settings) -> Any:
        return container

    def fake_listener(_: str, __: int) -> Any:
        return FakeListener()

    def fake_mcp(_: Any, *, manage_container_lifecycle: bool) -> Any:
        assert manage_container_lifecycle is False
        return FakeMcp()

    def fake_config(*_: object, **__: object) -> object:
        return object()

    monkeypatch.setattr(shared_runtime, "AccountProcessLock", FakeLock)
    monkeypatch.setattr(shared_runtime, "create_production_container", fake_container)
    monkeypatch.setattr(shared_runtime, "_bind_listener", fake_listener)
    monkeypatch.setattr(shared_runtime, "create_mcp_server", fake_mcp)
    monkeypatch.setattr(shared_runtime.uvicorn, "Config", fake_config)
    monkeypatch.setattr(shared_runtime.uvicorn, "Server", FakeServer)

    settings = Settings(
        runtime_lock_path=tmp_path / "runtime.lock",
        http_port=8123,
    )
    await shared_runtime.run_shared_runtime(settings)

    assert events == [
        "lock-created",
        "started",
        "server-created",
        "published:http://127.0.0.1:8123/mcp",
        "served",
        "listener-closed",
        "closed",
    ]


def test_runtime_spawn_listener_and_owner_validation_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(runtime_lock_path=tmp_path / "runtime.lock")
    popen_calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_popen(args: list[str], **kwargs: object) -> Any:
        popen_calls.append((args, kwargs))
        return object()

    monkeypatch.setattr(shared_runtime.subprocess, "Popen", fake_popen)
    spawned = shared_runtime._spawn_shared_runtime(  # pyright: ignore[reportPrivateUsage]
        settings
    )
    assert spawned is not None
    assert len(popen_calls) == 1
    args, kwargs = popen_calls[0]
    if os.name == "nt":
        assert Path(args[0]).name == "powershell.exe"
        assert args[-2] == "-Command"
        assert args[-1] == shared_runtime._WINDOWS_BROKER_SCRIPT  # pyright: ignore[reportPrivateUsage]
        assert kwargs["creationflags"]
        assert "start_new_session" not in kwargs
    else:
        assert args == [shared_runtime.sys.executable, "-m", "linkedin_mcp", "_runtime"]
        assert kwargs["start_new_session"] is True
        assert "creationflags" not in kwargs
    assert (tmp_path / "runtime.log").is_file()

    listener = shared_runtime._bind_listener(  # pyright: ignore[reportPrivateUsage]
        "127.0.0.1", 0
    )
    listener.close()

    with pytest.raises(ConfigurationError, match="invalid endpoint"):
        shared_runtime.validate_shared_runtime_endpoint("http://127.0.0.1:bad/mcp")
    with pytest.raises(ConfigurationError, match="without valid runtime metadata"):
        shared_runtime._validate_running_owner(  # pyright: ignore[reportPrivateUsage]
            AccountRuntimeStatus(running=True),
            settings,
        )
    wrong_account = AccountRuntimeOwner(
        pid=4321,
        command="_runtime",
        endpoint="http://127.0.0.1:8000/mcp",
        version=shared_runtime.__version__,
        account_id="other",
        configuration_fingerprint=shared_runtime.runtime_configuration_fingerprint(settings),
    )
    with pytest.raises(ConfigurationError, match="owns account other"):
        shared_runtime._validate_running_owner(  # pyright: ignore[reportPrivateUsage]
            AccountRuntimeStatus(running=True, owner=wrong_account),
            settings,
        )


def test_windows_runtime_uses_a_local_cim_broker_outside_client_jobs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    popen_calls: list[tuple[list[str], dict[str, object]]] = []

    class FakeBroker:
        return_code: int | None = None

        def poll(self) -> int | None:
            return self.return_code

    broker = FakeBroker()

    def fake_popen(args: list[str], **kwargs: object) -> Any:
        popen_calls.append((args, kwargs))
        return broker

    monkeypatch.setattr(shared_runtime.subprocess, "Popen", fake_popen)
    monkeypatch.setenv("SystemRoot", str(tmp_path / "Windows"))
    log_path = tmp_path / "runtime.log"
    with log_path.open("wb") as log:
        starter = shared_runtime._spawn_windows_shared_runtime(  # pyright: ignore[reportPrivateUsage]
            log
        )

    assert len(popen_calls) == 1
    args, kwargs = popen_calls[0]
    assert Path(args[0]).name == "powershell.exe"
    assert args[1:5] == ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command"]
    script = args[5]
    assert "Win32_ProcessStartup" in script
    assert "Win32_Process" in script
    assert "EnvironmentVariables" in script
    assert "CreateFlags = [uint32]520" in script

    environment = cast(dict[str, str], kwargs["env"])
    assert environment["LINKEDIN_MCP_INTERNAL_BROKER_COMMAND"] == subprocess.list2cmdline(
        [shared_runtime.sys.executable, "-m", "linkedin_mcp", "_runtime"]
    )
    assert environment["LINKEDIN_MCP_INTERNAL_BROKER_CWD"] == str(Path.cwd())
    assert environment["LINKEDIN_MCP_INTERNAL_BROKERED_RUNTIME"] == "1"
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert cast(Any, kwargs["stdout"]).closed is True
    assert cast(Any, kwargs["stderr"]).closed is True
    assert kwargs["close_fds"] is True
    assert kwargs["creationflags"]

    assert starter.poll() is None
    broker.return_code = 0
    assert starter.poll() is None
    broker.return_code = 7
    assert starter.poll() == 7


def test_windows_cim_broker_start_failure_is_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_popen(*_: object, **__: object) -> Any:
        raise OSError("sensitive local launch detail")

    monkeypatch.setattr(shared_runtime.subprocess, "Popen", fail_popen)
    with (
        (tmp_path / "runtime.log").open("wb") as log,
        pytest.raises(ConfigurationError, match="local Windows CIM") as raised,
    ):
        shared_runtime._spawn_windows_shared_runtime(  # pyright: ignore[reportPrivateUsage]
            log
        )
    assert "sensitive local launch detail" not in str(raised.value)


def test_brokered_runtime_redirects_python_output_to_the_safe_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSys:
        stdout: Any = None
        stderr: Any = None

    fake_sys = FakeSys()
    monkeypatch.setattr(shared_runtime, "sys", fake_sys)
    monkeypatch.delenv("LINKEDIN_MCP_INTERNAL_BROKERED_RUNTIME", raising=False)
    assert shared_runtime.brokered_runtime_output_required() is False
    monkeypatch.setenv("LINKEDIN_MCP_INTERNAL_BROKERED_RUNTIME", "1")
    assert shared_runtime.brokered_runtime_output_required() is True

    log = shared_runtime.redirect_brokered_runtime_output(
        Settings(runtime_lock_path=tmp_path / "runtime.lock")
    )
    try:
        assert fake_sys.stdout is log
        assert fake_sys.stderr is log
        log.write("brokered runtime diagnostic\n")
        log.flush()
    finally:
        log.close()
    assert (tmp_path / "runtime.log").read_text(encoding="utf-8") == (
        "brokered runtime diagnostic\n"
    )
