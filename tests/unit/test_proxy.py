from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast

import pytest
from mcp import types
from pydantic import AnyUrl

import linkedin_mcp.application.proxy as proxy_module


class _FakeProxy:
    def __init__(self) -> None:
        self.handlers: dict[str, Callable[..., Any]] = {}
        self.progress_notifications: list[dict[str, object]] = []
        self.request_context = SimpleNamespace(
            meta=None,
            session=SimpleNamespace(
                send_progress_notification=self._send_progress_notification,
            ),
        )

    async def _send_progress_notification(self, **values: object) -> None:
        self.progress_notifications.append(values)

    def _decorator(self, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def register(handler: Callable[..., Any]) -> Callable[..., Any]:
            self.handlers[name] = handler
            return handler

        return register

    def list_tools(self) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._decorator("list_tools")

    def call_tool(
        self,
        *,
        validate_input: bool,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        assert validate_input is False
        return self._decorator("call_tool")

    def list_resources(self) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._decorator("list_resources")

    def list_resource_templates(self) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._decorator("list_resource_templates")

    def read_resource(self) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._decorator("read_resource")

    def list_prompts(self) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._decorator("list_prompts")

    def get_prompt(self) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self._decorator("get_prompt")


class _FakeUpstream:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def list_tools(self, *, params: object = None) -> str:
        self.calls.append(("list_tools", params))
        return "tools"

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        progress_callback: Callable[[float, float | None, str | None], Any] | None,
    ) -> str:
        self.calls.append(("call_tool", (name, arguments)))
        if progress_callback is not None:
            await progress_callback(1.0, 2.0, "working")
        return "tool-result"

    async def list_resources(self, *, params: object = None) -> str:
        self.calls.append(("list_resources", params))
        return "resources"

    async def list_resource_templates(self) -> SimpleNamespace:
        self.calls.append(("list_resource_templates", None))
        return SimpleNamespace(resourceTemplates=["template"])

    async def read_resource(self, uri: AnyUrl) -> SimpleNamespace:
        self.calls.append(("read_resource", str(uri)))
        return SimpleNamespace(
            contents=[
                types.TextResourceContents(
                    uri=uri,
                    mimeType="text/plain",
                    text="visible text",
                    _meta={"source": "fixture"},
                ),
                types.BlobResourceContents(
                    uri=uri,
                    mimeType="application/octet-stream",
                    blob="YmluYXJ5",
                ),
            ]
        )

    async def list_prompts(self, *, params: object = None) -> str:
        self.calls.append(("list_prompts", params))
        return "prompts"

    async def get_prompt(self, name: str, arguments: dict[str, str] | None) -> str:
        self.calls.append(("get_prompt", (name, arguments)))
        return "prompt"


@pytest.mark.asyncio
async def test_proxy_handlers_forward_contract_and_progress() -> None:
    proxy = _FakeProxy()
    upstream = _FakeUpstream()
    proxy_module._register_proxy_handlers(  # pyright: ignore[reportPrivateUsage]
        cast(Any, proxy),
        cast(Any, upstream),
    )

    params = types.PaginatedRequestParams(cursor="next")
    request = SimpleNamespace(params=params)
    assert await proxy.handlers["list_tools"]() == "tools"
    assert await proxy.handlers["list_tools"](request) == "tools"
    assert await proxy.handlers["list_resources"](request) == "resources"
    assert await proxy.handlers["list_resource_templates"]() == ["template"]
    assert await proxy.handlers["list_prompts"](request) == "prompts"
    assert await proxy.handlers["get_prompt"]("welcome", {"name": "Prakhar"}) == "prompt"

    uri = AnyUrl("linkedin://sources/example")
    contents = await proxy.handlers["read_resource"](uri)
    assert contents[0].content == "visible text"
    assert contents[0].mime_type == "text/plain"
    assert contents[0].meta == {"source": "fixture"}
    assert contents[1].content == b"binary"

    assert await proxy.handlers["call_tool"]("linkedin.server.status", {}) == "tool-result"
    assert proxy.progress_notifications == []

    proxy.request_context.meta = SimpleNamespace(progressToken="progress-1")
    assert await proxy.handlers["call_tool"]("linkedin.jobs.search", {"query": "python"}) == (
        "tool-result"
    )
    assert proxy.progress_notifications == [
        {
            "progress_token": "progress-1",
            "progress": 1.0,
            "total": 2.0,
            "message": "working",
        }
    ]
    assert upstream.calls[0] == ("list_tools", None)
    assert upstream.calls[1] == ("list_tools", params)


@pytest.mark.asyncio
async def test_stdio_proxy_initializes_and_runs_downstream_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []

    @asynccontextmanager
    async def fake_http_client(endpoint: str) -> AsyncGenerator[tuple[str, str, None]]:
        events.append(("http", endpoint))
        yield ("upstream-read", "upstream-write", None)

    @asynccontextmanager
    async def fake_stdio_server() -> AsyncGenerator[tuple[str, str]]:
        events.append("stdio")
        yield ("downstream-read", "downstream-write")

    class FakeSession:
        def __init__(self, read: str, write: str, *, client_info: object) -> None:
            events.append(("session", read, write, client_info))

        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def initialize(self) -> SimpleNamespace:
            return SimpleNamespace(
                serverInfo=SimpleNamespace(
                    name="linkedin-runtime",
                    version="1.2.3",
                    websiteUrl="https://example.test",
                    icons=[],
                ),
                instructions="runtime instructions",
            )

    class FakeServer:
        def __init__(self, **values: object) -> None:
            events.append(("server", values))

        def create_initialization_options(self) -> str:
            return "initialization-options"

        async def run(self, read: str, write: str, options: str) -> None:
            events.append(("run", read, write, options))

    def register(_: object, __: object) -> None:
        events.append("handlers")

    monkeypatch.setattr(proxy_module, "streamable_http_client", fake_http_client)
    monkeypatch.setattr(proxy_module, "ClientSession", FakeSession)
    monkeypatch.setattr(proxy_module, "stdio_server", fake_stdio_server)
    monkeypatch.setattr(proxy_module, "Server", FakeServer)
    monkeypatch.setattr(proxy_module, "_register_proxy_handlers", register)

    await proxy_module.run_stdio_proxy("http://127.0.0.1:8123/mcp")

    assert ("http", "http://127.0.0.1:8123/mcp") in events
    assert "handlers" in events
    assert ("run", "downstream-read", "downstream-write", "initialization-options") in events
