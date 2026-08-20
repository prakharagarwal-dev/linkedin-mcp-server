from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any, cast

import anyio
import pytest
import uvicorn

import linkedin_mcp.host.manager as host
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import ConfigurationError
from linkedin_mcp.host import AccountRuntimeOwner, AccountRuntimeStatus
from tests.contract.test_mcp_protocol import protocol_server


def test_host_endpoint_is_deterministic_and_loopback_only(tmp_path: Path) -> None:
    assert (
        host.host_endpoint(
            Settings(
                http_host="localhost",
                http_port=8123,
                runtime_lock_path=tmp_path / "runtime.lock",
            )
        )
        == "http://127.0.0.1:8123/mcp"
    )
    assert (
        host.host_endpoint(
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
        host.host_endpoint(unsafe)


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
        host.validate_host_endpoint(endpoint)


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
            command="shared-runtime",
            endpoint=endpoint,
            version=host.__version__,
            account_id=settings.account_id,
            configuration_fingerprint=host.runtime_configuration_fingerprint(settings),
        ),
    )

    def inspect(_: Path) -> AccountRuntimeStatus:
        return status

    monkeypatch.setattr(host, "inspect_account_runtime", inspect)

    async def healthy(_: AccountRuntimeStatus) -> str:
        return endpoint

    monkeypatch.setattr(host, "_healthy_endpoint", healthy)

    def unexpected_spawn(_: Settings) -> Any:
        raise AssertionError("A healthy runtime must not spawn another owner.")

    monkeypatch.setattr(host, "_spawn_host", unexpected_spawn)

    assert await host.ensure_host(settings) == endpoint


@pytest.mark.asyncio
async def test_ensure_waits_for_new_lock_owner_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(runtime_lock_path=tmp_path / "runtime.lock")
    endpoint = "http://127.0.0.1:8000/mcp"

    def starting(_: Path) -> AccountRuntimeStatus:
        return AccountRuntimeStatus(running=True)

    monkeypatch.setattr(host, "inspect_account_runtime", starting)

    async def wait(_: Settings, *, starter: Any = None) -> str:
        assert starter is None
        return endpoint

    monkeypatch.setattr(host, "wait_for_host", wait)

    def unexpected_spawn(_: Settings) -> Any:
        raise AssertionError("A held runtime lock must not spawn another owner.")

    monkeypatch.setattr(host, "_spawn_host", unexpected_spawn)
    assert await host.ensure_host(settings) == endpoint


@pytest.mark.asyncio
async def test_runtime_wait_tolerates_owner_metadata_publication_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(runtime_lock_path=tmp_path / "runtime.lock")
    endpoint = "http://127.0.0.1:8000/mcp"
    owner = AccountRuntimeOwner(
        pid=4321,
        command="shared-runtime",
        endpoint=endpoint,
        version=host.__version__,
        account_id=settings.account_id,
        configuration_fingerprint=host.runtime_configuration_fingerprint(settings),
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

    monkeypatch.setattr(host, "inspect_account_runtime", inspect)
    monkeypatch.setattr(host, "_healthy_endpoint", healthy)
    monkeypatch.setattr(host.asyncio, "sleep", no_sleep)
    assert await host.wait_for_host(settings) == endpoint


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

    monkeypatch.setattr(host, "inspect_account_runtime", missing)
    monkeypatch.setattr(host.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(host, "time", FakeTime)

    with pytest.raises(ConfigurationError, match="without valid runtime metadata"):
        await host.wait_for_host(settings)


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

    monkeypatch.setattr(host, "inspect_account_runtime", inspect)

    async def unavailable(_: AccountRuntimeStatus) -> None:
        return None

    monkeypatch.setattr(host, "_healthy_endpoint", unavailable)

    with pytest.raises(ConfigurationError, match=r"profile maintenance \(login\)"):
        await host.wait_for_host(settings)


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
            command="shared-runtime",
            version="0.1.0",
            endpoint="http://127.0.0.1:8000/mcp",
            account_id=settings.account_id,
        ),
    )

    def inspect(_: Path) -> AccountRuntimeStatus:
        return status

    monkeypatch.setattr(host, "inspect_account_runtime", inspect)

    with pytest.raises(ConfigurationError, match="this client uses"):
        await host.wait_for_host(settings)


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
            command="shared-runtime",
            version=host.__version__,
            endpoint="http://127.0.0.1:8000/mcp",
            account_id=settings.account_id,
            configuration_fingerprint="0" * 64,
        ),
    )

    def inspect(_: Path) -> AccountRuntimeStatus:
        return status

    monkeypatch.setattr(host, "inspect_account_runtime", inspect)

    with pytest.raises(ConfigurationError, match="different profile, browser"):
        await host.wait_for_host(settings)


@pytest.mark.asyncio
async def test_runtime_wait_reports_background_start_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(runtime_lock_path=tmp_path / "runtime.lock")

    def inspect(_: Path) -> AccountRuntimeStatus:
        return AccountRuntimeStatus(running=False)

    monkeypatch.setattr(host, "inspect_account_runtime", inspect)

    async def unavailable(_: AccountRuntimeStatus) -> None:
        return None

    class FailedStarter:
        @staticmethod
        def poll() -> int:
            return 1

    monkeypatch.setattr(host, "_healthy_endpoint", unavailable)

    with pytest.raises(ConfigurationError, match="failed during startup"):
        await host.wait_for_host(
            settings,
            starter=cast(Any, FailedStarter()),
        )


@pytest.mark.asyncio
async def test_runtime_health_and_status_probe_the_real_mcp_transport(
    tmp_path: Path,
    unused_tcp_port: int,
) -> None:
    mcp, scheduler, browser, cursor_store = protocol_server(tmp_path)
    await scheduler.start()
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

    try:
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(server.serve)
            for _ in range(200):
                if server.started:
                    break
                await anyio.sleep(0.01)
            else:
                raise AssertionError("Shared runtime fixture did not start")
            try:
                assert await host.host_is_healthy(endpoint)
                status = await host.read_host_status(endpoint)
            finally:
                server.should_exit = True
    finally:
        await scheduler.close()
        await cursor_store.close()
        await browser.close()

    assert status is not None
    assert status["name"] == "linkedin-mcp-server"
    assert await host.host_is_healthy("https://example.com/mcp") is False
    assert await host.read_host_status("https://example.com/mcp") is None


@pytest.mark.asyncio
async def test_healthy_endpoint_requires_a_live_published_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = "http://127.0.0.1:8000/mcp"
    owner = AccountRuntimeOwner(pid=4321, command="shared-runtime", endpoint=endpoint)

    async def healthy(_: str, *, timeout_seconds: float = 2.0) -> bool:
        del timeout_seconds
        return True

    monkeypatch.setattr(host, "host_is_healthy", healthy)
    assert (
        await host._healthy_endpoint(  # pyright: ignore[reportPrivateUsage]
            AccountRuntimeStatus(running=True, owner=owner)
        )
        == endpoint
    )
    assert (
        await host._healthy_endpoint(  # pyright: ignore[reportPrivateUsage]
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

    monkeypatch.setattr(host, "inspect_account_runtime", stopped)
    monkeypatch.setattr(host, "_spawn_host", spawn)

    observed_starters: list[Any] = []

    async def wait_started(_: Settings, *, starter: Any = None) -> str:
        observed_starters.append(starter)
        return endpoint

    monkeypatch.setattr(host, "wait_for_host", wait_started)
    assert await host.ensure_host(settings) == endpoint

    owner = AccountRuntimeOwner(
        pid=4321,
        command="shared-runtime",
        endpoint=endpoint,
        version=host.__version__,
        account_id=settings.account_id,
        configuration_fingerprint=host.runtime_configuration_fingerprint(settings),
    )

    def running(_: Path) -> AccountRuntimeStatus:
        return AccountRuntimeStatus(running=True, owner=owner)

    monkeypatch.setattr(host, "inspect_account_runtime", running)

    async def unhealthy(_: AccountRuntimeStatus) -> None:
        return None

    monkeypatch.setattr(host, "_healthy_endpoint", unhealthy)
    assert await host.ensure_host(settings) == endpoint
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
        command="shared-runtime",
        endpoint="http://127.0.0.1:8000/mcp",
        version=host.__version__,
        account_id=settings.account_id,
        configuration_fingerprint=host.runtime_configuration_fingerprint(settings),
    )

    def running(_: Path) -> AccountRuntimeStatus:
        return AccountRuntimeStatus(running=True, owner=owner)

    monkeypatch.setattr(host, "inspect_account_runtime", running)

    async def unhealthy(_: AccountRuntimeStatus) -> None:
        return None

    async def no_sleep(_: float) -> None:
        return None

    class FakeTime:
        values = iter((0.0, 0.1, 2.0))

        @classmethod
        def monotonic(cls) -> float:
            return next(cls.values)

    monkeypatch.setattr(host, "_healthy_endpoint", unhealthy)
    monkeypatch.setattr(host.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(host, "time", FakeTime)

    with pytest.raises(ConfigurationError, match="current owner command is 'shared-runtime'"):
        await host.wait_for_host(settings)


@pytest.mark.asyncio
async def test_run_host_owns_and_closes_its_listener(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeLock:
        def __init__(self, *_: object, **__: object) -> None:
            events.append("lock-created")

        def acquire(self) -> None:
            events.append("lock-acquired")

        def publish_endpoint(self, endpoint: str) -> None:
            events.append(f"published:{endpoint}")

        async def wait_for_stop_request(self) -> None:
            await asyncio.Event().wait()

        def release(self) -> None:
            events.append("lock-released")

    class FakeBrowser:
        def __init__(self, _: Settings, __: object) -> None:
            events.append("browser-created")
            self.setup_state = object()

        async def start(self) -> object:
            events.append("browser-started")
            return context

        def profile_present(self) -> bool:
            return True

        async def close(self) -> None:
            events.append("browser-closed")

    class FakeScheduler:
        def __init__(self, *_: object, **__: object) -> None:
            events.append("scheduler-created")

        async def start(self) -> None:
            events.append("scheduler-started")

        async def quiesce(self) -> None:
            events.append("scheduler-quiesced")

        async def close(self) -> None:
            events.append("scheduler-closed")

    class FakeCursorStore:
        def __init__(self, **_: object) -> None:
            events.append("cursor-created")

        async def close(self) -> None:
            events.append("cursor-closed")

    class FakeListener:
        def close(self) -> None:
            events.append("listener-closed")

    def fake_listener(_: str, __: int) -> Any:
        return FakeListener()

    context = object()
    mcp = object()

    def fake_mcp(_: Settings) -> object:
        events.append("mcp-created")
        return mcp

    def fake_attach(*_: object, **__: object) -> None:
        events.append("tools-attached")

    async def fake_serve_http(
        served_mcp: object,
        served_settings: Settings,
        listener: FakeListener,
        wait_for_stop: Any,
    ) -> None:
        assert served_mcp is mcp
        assert served_settings.http_port == 8123
        assert isinstance(listener, FakeListener)
        assert callable(wait_for_stop)
        events.append("served")

    monkeypatch.setattr(host, "AccountProcessLock", FakeLock)
    monkeypatch.setattr(host, "BrowserManager", FakeBrowser)
    monkeypatch.setattr(host, "Scheduler", FakeScheduler)
    monkeypatch.setattr(host, "CursorStore", FakeCursorStore)
    monkeypatch.setattr(host, "create_mcp_server", fake_mcp)
    monkeypatch.setattr(host, "attach_tools", fake_attach)
    monkeypatch.setattr(host, "bind_http_listener", fake_listener)
    monkeypatch.setattr(host, "serve_http", fake_serve_http)

    settings = Settings(
        runtime_lock_path=tmp_path / "runtime.lock",
        http_port=8123,
    )
    await host.HostManager(settings).run_http()

    assert events == [
        "lock-created",
        "lock-acquired",
        "browser-created",
        "browser-started",
        "scheduler-created",
        "cursor-created",
        "mcp-created",
        "tools-attached",
        "scheduler-started",
        "published:http://127.0.0.1:8123/mcp",
        "served",
        "listener-closed",
        "scheduler-quiesced",
        "scheduler-closed",
        "cursor-closed",
        "browser-closed",
        "lock-released",
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

    monkeypatch.setattr(host.subprocess, "Popen", fake_popen)
    spawned = host._spawn_host(  # pyright: ignore[reportPrivateUsage]
        settings
    )
    assert spawned is not None
    assert len(popen_calls) == 1
    args, kwargs = popen_calls[0]
    if os.name == "nt":
        assert Path(args[0]).name == "powershell.exe"
        assert args[-2] == "-Command"
        assert args[-1] == host._WINDOWS_BROKER_SCRIPT  # pyright: ignore[reportPrivateUsage]
        assert kwargs["creationflags"]
        assert "start_new_session" not in kwargs
    else:
        assert args == [host.sys.executable, "-m", "linkedin_mcp"]
        assert kwargs["start_new_session"] is True
        assert "creationflags" not in kwargs
        environment = cast(dict[str, str], kwargs["env"])
        assert environment["LINKEDIN_MCP_INTERNAL_HOST"] == "1"
    assert (tmp_path / "runtime.log").is_file()

    with pytest.raises(ConfigurationError, match="invalid endpoint"):
        host.validate_host_endpoint("http://127.0.0.1:bad/mcp")
    with pytest.raises(ConfigurationError, match="without valid runtime metadata"):
        host._validate_running_owner(  # pyright: ignore[reportPrivateUsage]
            AccountRuntimeStatus(running=True),
            settings,
        )
    wrong_account = AccountRuntimeOwner(
        pid=4321,
        command="shared-runtime",
        endpoint="http://127.0.0.1:8000/mcp",
        version=host.__version__,
        account_id="other",
        configuration_fingerprint=host.runtime_configuration_fingerprint(settings),
    )
    with pytest.raises(ConfigurationError, match="owns account other"):
        host._validate_running_owner(  # pyright: ignore[reportPrivateUsage]
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

    monkeypatch.setattr(host.subprocess, "Popen", fake_popen)
    monkeypatch.setenv("SystemRoot", str(tmp_path / "Windows"))
    log_path = tmp_path / "runtime.log"
    with log_path.open("wb") as log:
        starter = host._spawn_windows_host(  # pyright: ignore[reportPrivateUsage]
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
        [host.sys.executable, "-m", "linkedin_mcp"]
    )
    assert environment["LINKEDIN_MCP_INTERNAL_HOST"] == "1"
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

    monkeypatch.setattr(host.subprocess, "Popen", fail_popen)
    with (
        (tmp_path / "runtime.log").open("wb") as log,
        pytest.raises(ConfigurationError, match="local Windows CIM") as raised,
    ):
        host._spawn_windows_host(  # pyright: ignore[reportPrivateUsage]
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
    monkeypatch.setattr(host, "sys", fake_sys)
    monkeypatch.delenv("LINKEDIN_MCP_INTERNAL_BROKERED_RUNTIME", raising=False)
    assert host.brokered_host_output_required() is False
    monkeypatch.setenv("LINKEDIN_MCP_INTERNAL_BROKERED_RUNTIME", "1")
    assert host.brokered_host_output_required() is True

    log = host.redirect_brokered_host_output(Settings(runtime_lock_path=tmp_path / "runtime.lock"))
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
