"""Official MCP client harness for the stateful simulator container."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from mcp import ClientSession
from mcp.shared.message import SessionMessage
from pydantic import TypeAdapter

from linkedin_mcp.server import create_mcp_server
from tests.simulator.harness import create_simulator_container
from tests.simulator.state import SimulatorState


@asynccontextmanager
async def simulator_session(
    root: Path,
    state: SimulatorState,
) -> AsyncGenerator[ClientSession]:
    container = create_simulator_container(root, state)
    mcp = create_mcp_server(container)
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

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(run_server)
        async with ClientSession(server_to_client_receive, client_to_server_send) as session:
            await session.initialize()
            yield session
        task_group.cancel_scope.cancel()


async def execute_prepared(
    session: ClientSession,
    *,
    execute_tool: str,
    prepared_content: dict[str, object],
    request_id: str,
    idempotency_key: str,
) -> dict[str, object]:
    draft = TypeAdapter(dict[str, object]).validate_python(prepared_content["draft"])
    approval_preview = TypeAdapter(dict[str, object]).validate_python(
        prepared_content["approval_preview"]
    )
    action_id = TypeAdapter(str).validate_python(draft["action_id"])
    payload_hash = TypeAdapter(str).validate_python(draft["payload_hash"])
    result = await session.call_tool(
        execute_tool,
        {
            "context_id": "mock-workflow",
            "request_id": request_id,
            "action_id": action_id,
            "payload_hash": payload_hash,
            "approval_preview": approval_preview,
            "idempotency_key": idempotency_key,
        },
    )
    assert result.isError is False
    assert result.structuredContent is not None
    return TypeAdapter(dict[str, object]).validate_python(result.structuredContent)
