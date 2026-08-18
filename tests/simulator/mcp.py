"""Official MCP client harness for the stateful simulator container."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from mcp import ClientSession
from mcp.shared.message import SessionMessage

from tests.simulator.harness import create_simulator_server
from tests.simulator.state import SimulatorState


@asynccontextmanager
async def simulator_session(
    root: Path,
    state: SimulatorState,
) -> AsyncGenerator[ClientSession]:
    mcp, scheduler, browser, cursor_store = create_simulator_server(root, state)
    await scheduler.start()
    server_to_client_send, server_to_client_receive = anyio.create_memory_object_stream[
        SessionMessage
    ](50)
    client_to_server_send, client_to_server_receive = anyio.create_memory_object_stream[
        SessionMessage
    ](50)

    async def run_server() -> None:
        await mcp._mcp_server.run(  # pyright: ignore[reportPrivateUsage]
            client_to_server_receive,
            server_to_client_send,
            mcp._mcp_server.create_initialization_options(),  # pyright: ignore[reportPrivateUsage]
            raise_exceptions=True,
        )

    try:
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(run_server)
            async with ClientSession(server_to_client_receive, client_to_server_send) as session:
                await session.initialize()
                yield session
            task_group.cancel_scope.cancel()
    finally:
        await scheduler.close()
        await cursor_store.close()
        await browser.close()
