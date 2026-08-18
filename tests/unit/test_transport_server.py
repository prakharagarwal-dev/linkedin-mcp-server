from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

import linkedin_mcp.transport.server as transport_server
from linkedin_mcp.config import Settings


def test_bind_http_listener_owns_the_requested_loopback_socket() -> None:
    listener = transport_server.bind_http_listener("127.0.0.1", 0)
    try:
        host, port = listener.getsockname()[:2]
        assert host == "127.0.0.1"
        assert port > 0
        assert listener.getblocking() is False
    finally:
        listener.close()


@pytest.mark.asyncio
async def test_serve_http_owns_uvicorn_and_cancels_its_stop_waiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeMcp:
        @staticmethod
        def streamable_http_app() -> object:
            events.append("app-created")
            return object()

    class FakeListener:
        pass

    class FakeServer:
        should_exit = False

        def __init__(self, _: object) -> None:
            events.append("server-created")

        async def serve(self, *, sockets: list[FakeListener]) -> None:
            assert len(sockets) == 1
            events.append("served")

    def fake_config(*_: object, **__: object) -> object:
        events.append("configured")
        return object()

    async def wait_for_stop() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            events.append("stop-waiter-closed")

    monkeypatch.setattr(transport_server.uvicorn, "Config", fake_config)
    monkeypatch.setattr(transport_server.uvicorn, "Server", FakeServer)

    await transport_server.serve_http(
        cast(Any, FakeMcp()),
        Settings(http_port=8123),
        cast(Any, FakeListener()),
        wait_for_stop,
    )

    assert events == [
        "app-created",
        "configured",
        "server-created",
        "served",
        "stop-waiter-closed",
    ]
