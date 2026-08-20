from pathlib import Path

import pytest
from pydantic import ValidationError

import linkedin_mcp.host.manager as host_main
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import ConfigurationError
from linkedin_mcp.host import AccountRuntimeStatus


@pytest.mark.asyncio
async def test_host_main_rewrites_transport_and_recovers_an_election_race(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: list[str] = []

    class SuccessfulHostManager:
        def __init__(self, settings: Settings) -> None:
            observed.append(settings.transport)

        async def run_http(self) -> None:
            return

    monkeypatch.setattr(host_main, "HostManager", SuccessfulHostManager)
    settings = Settings(
        transport="stdio",
        runtime_lock_path=tmp_path / "runtime.lock",
    )
    await host_main.run_internal_host(settings)

    class LosingHostManager:
        def __init__(self, _: Settings) -> None:
            return

        async def run_http(self) -> None:
            raise ConfigurationError("another owner won")

    def running(_: Path) -> AccountRuntimeStatus:
        return AccountRuntimeStatus(running=True)

    async def wait(_: Settings) -> str:
        observed.append("waited")
        return "http://127.0.0.1:8000/mcp"

    monkeypatch.setattr(host_main, "HostManager", LosingHostManager)
    monkeypatch.setattr(host_main, "inspect_account_runtime", running)
    monkeypatch.setattr(host_main, "wait_for_host", wait)
    await host_main.run_internal_host(settings)

    assert observed == ["streamable-http", "waited"]


@pytest.mark.asyncio
async def test_host_main_revalidates_loopback_transport() -> None:
    settings = Settings(transport="stdio", http_host="0.0.0.0")

    with pytest.raises(ValidationError, match="restricted to loopback"):
        await host_main.run_internal_host(settings)
