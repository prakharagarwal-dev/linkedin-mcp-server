"""End-to-end shared-runtime transport and ownership verification."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import TypedDict

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from linkedin_mcp import __version__
from linkedin_mcp.host import inspect_account_runtime, stop_account_runtime
from linkedin_mcp.host.manager import host_is_healthy

ROOT = Path(__file__).parents[2]


class _ClientObservation(TypedDict):
    server_name: str
    server_version: str
    runtime_model: str
    tool_count: int


@pytest.mark.asyncio
@pytest.mark.timeout(90)
async def test_two_stdio_clients_elect_and_share_one_surviving_runtime(
    tmp_path: Path,
    unused_tcp_port: int,
) -> None:
    lock_path = tmp_path / "runtime.lock"
    profile_path = tmp_path / "profile"
    cache_path = tmp_path / "browsers"
    environment = {
        **os.environ,
        "LINKEDIN_MCP_AUTO_LOGIN_ON_START": "false",
        "LINKEDIN_MCP_BROWSER_AUTO_INSTALL": "false",
        "LINKEDIN_MCP_BROWSER_PROFILE_PATH": str(profile_path),
        "LINKEDIN_MCP_BROWSER_CACHE_PATH": str(cache_path),
        "LINKEDIN_MCP_RUNTIME_LOCK_PATH": str(lock_path),
        "LINKEDIN_MCP_HTTP_HOST": "127.0.0.1",
        "LINKEDIN_MCP_HTTP_PORT": str(unused_tcp_port),
        "LINKEDIN_MCP_LOG_LEVEL": "CRITICAL",
    }
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "linkedin_mcp", "serve", "--transport", "stdio"],
        cwd=ROOT,
        env=environment,
    )
    ready: asyncio.Queue[_ClientObservation | BaseException] = asyncio.Queue()
    release = asyncio.Event()

    async def run_client() -> None:
        announced = False
        try:
            async with (
                stdio_client(parameters) as (read_stream, write_stream),
                ClientSession(read_stream, write_stream) as session,
            ):
                initialized = await session.initialize()
                tools = await session.list_tools()
                status = await session.call_tool("linkedin.server.status", {})
                assert status.isError is False
                assert status.structuredContent is not None
                await ready.put(
                    _ClientObservation(
                        server_name=initialized.serverInfo.name,
                        server_version=initialized.serverInfo.version,
                        runtime_model=str(status.structuredContent["runtime_model"]),
                        tool_count=len(tools.tools),
                    )
                )
                announced = True
                await release.wait()
                after_wait = await session.call_tool("linkedin.server.status", {})
                assert after_wait.isError is False
        except BaseException as error:
            if not announced:
                await ready.put(error)
            else:
                raise

    clients = [asyncio.create_task(run_client()) for _ in range(2)]
    owner_pid: int | None = None
    endpoint: str | None = None
    try:
        observations = [
            await asyncio.wait_for(ready.get(), timeout=30),
            await asyncio.wait_for(ready.get(), timeout=30),
        ]
        for observation in observations:
            if isinstance(observation, BaseException):
                raise observation
            assert observation["server_name"] == "linkedin-mcp-server"
            assert observation["server_version"] == __version__
            assert observation["runtime_model"] == "shared_local"
            assert observation["tool_count"] > 20

        ownership = inspect_account_runtime(lock_path)
        assert ownership.running is True
        assert ownership.owner is not None
        assert ownership.owner.command == "shared-runtime"
        assert ownership.owner.transport == "shared-loopback"
        assert ownership.owner.version == __version__
        assert ownership.owner.configuration_fingerprint is not None
        assert ownership.owner.endpoint == f"http://127.0.0.1:{unused_tcp_port}/mcp"
        owner_pid = ownership.owner.pid
        endpoint = ownership.owner.endpoint
        assert endpoint is not None

        async with (
            streamable_http_client(endpoint) as (read_stream, write_stream, _),
            ClientSession(read_stream, write_stream) as direct_session,
        ):
            await direct_session.initialize()
            direct_status = await direct_session.call_tool("linkedin.server.status", {})
            assert direct_status.isError is False
            assert direct_status.structuredContent is not None
            assert direct_status.structuredContent["accepting_calls"] is True

        release.set()
        await asyncio.wait_for(asyncio.gather(*clients), timeout=20)

        after_disconnect = inspect_account_runtime(lock_path)
        assert after_disconnect.running is True
        assert after_disconnect.owner is not None
        assert after_disconnect.owner.pid == owner_pid
        for _ in range(12):
            assert await host_is_healthy(endpoint, timeout_seconds=3)
    finally:
        release.set()
        for client in clients:
            if not client.done():
                client.cancel()
        await asyncio.gather(*clients, return_exceptions=True)
        if inspect_account_runtime(lock_path).running:
            await asyncio.to_thread(
                stop_account_runtime,
                lock_path,
                timeout_seconds=10,
            )

    assert inspect_account_runtime(lock_path).running is False
