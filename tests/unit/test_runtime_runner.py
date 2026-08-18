from pathlib import Path

import pytest
from pydantic import ValidationError

import linkedin_mcp.transport.runner as runtime_runner
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import ConfigurationError
from linkedin_mcp.transport import AccountRuntimeStatus


@pytest.mark.asyncio
async def test_runtime_runner_rewrites_transport_and_recovers_an_election_race(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: list[str] = []

    async def run(settings: Settings) -> None:
        observed.append(settings.transport)

    monkeypatch.setattr(runtime_runner, "run_shared_runtime", run)
    settings = Settings(
        transport="stdio",
        runtime_lock_path=tmp_path / "runtime.lock",
    )
    await runtime_runner.run(settings)

    async def lose_election(_: Settings) -> None:
        raise ConfigurationError("another owner won")

    def running(_: Path) -> AccountRuntimeStatus:
        return AccountRuntimeStatus(running=True)

    async def wait(_: Settings) -> str:
        observed.append("waited")
        return "http://127.0.0.1:8000/mcp"

    monkeypatch.setattr(runtime_runner, "run_shared_runtime", lose_election)
    monkeypatch.setattr(runtime_runner, "inspect_account_runtime", running)
    monkeypatch.setattr(runtime_runner, "wait_for_shared_runtime", wait)
    await runtime_runner.run(settings)

    assert observed == ["streamable-http", "waited"]


@pytest.mark.asyncio
async def test_runtime_runner_revalidates_loopback_transport() -> None:
    settings = Settings(transport="stdio", http_host="0.0.0.0")

    with pytest.raises(ValidationError, match="restricted to loopback"):
        await runtime_runner.run(settings)
