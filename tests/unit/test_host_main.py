from pathlib import Path

import pytest
from pydantic import ValidationError

import linkedin_mcp.host.__main__ as host_main
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import ConfigurationError
from linkedin_mcp.host import AccountRuntimeStatus


@pytest.mark.asyncio
async def test_host_main_rewrites_transport_and_recovers_an_election_race(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: list[str] = []

    async def run(settings: Settings) -> None:
        observed.append(settings.transport)

    monkeypatch.setattr(host_main, "run_host", run)
    settings = Settings(
        transport="stdio",
        runtime_lock_path=tmp_path / "runtime.lock",
    )
    await host_main.run(settings)

    async def lose_election(_: Settings) -> None:
        raise ConfigurationError("another owner won")

    def running(_: Path) -> AccountRuntimeStatus:
        return AccountRuntimeStatus(running=True)

    async def wait(_: Settings) -> str:
        observed.append("waited")
        return "http://127.0.0.1:8000/mcp"

    monkeypatch.setattr(host_main, "run_host", lose_election)
    monkeypatch.setattr(host_main, "inspect_account_runtime", running)
    monkeypatch.setattr(host_main, "wait_for_host", wait)
    await host_main.run(settings)

    assert observed == ["streamable-http", "waited"]


@pytest.mark.asyncio
async def test_host_main_revalidates_loopback_transport() -> None:
    settings = Settings(transport="stdio", http_host="0.0.0.0")

    with pytest.raises(ValidationError, match="restricted to loopback"):
        await host_main.run(settings)
