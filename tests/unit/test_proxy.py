"""Compact contract coverage for the shared-runtime stdio bridge."""

from __future__ import annotations

import base64
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast

import anyio
import pytest
from mcp import ClientSession, types
from mcp.server.lowlevel import Server
from mcp.shared.message import SessionMessage
from pydantic import AnyUrl

import linkedin_mcp.mcp.transports.stdio as proxy_module
from linkedin_mcp.mcp.transports.stdio import (
    _read_resource_content,  # pyright: ignore[reportPrivateUsage]
    _register_proxy_handlers,  # pyright: ignore[reportPrivateUsage]
)


class FakeUpstream:
    progress_forwarded = False

    async def list_tools(
        self,
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListToolsResult:
        del params
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="linkedin.test.read",
                    description="Read a deterministic fixture.",
                    inputSchema={"type": "object", "properties": {}},
                    annotations=types.ToolAnnotations(readOnlyHint=True),
                )
            ]
        )

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        progress_callback: Callable[[float, float | None, str | None], Awaitable[None]]
        | None = None,
    ) -> types.CallToolResult:
        assert name == "linkedin.test.read"
        assert arguments == {}
        if progress_callback is not None:
            await progress_callback(1, 1, "done")
            self.progress_forwarded = True
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="fixture")],
            structuredContent={"status": "completed"},
        )

    async def list_resources(
        self,
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListResourcesResult:
        del params
        return types.ListResourcesResult(
            resources=[
                types.Resource(
                    uri=AnyUrl("example://resources/test"),
                    name="test evidence",
                )
            ]
        )

    async def list_resource_templates(self) -> types.ListResourceTemplatesResult:
        return types.ListResourceTemplatesResult(
            resourceTemplates=[
                types.ResourceTemplate(
                    uriTemplate="example://resources/{resource_id}",
                    name="Example resource",
                )
            ]
        )

    async def read_resource(self, uri: AnyUrl) -> types.ReadResourceResult:
        return types.ReadResourceResult(
            contents=[
                types.TextResourceContents(
                    uri=uri,
                    mimeType="text/plain",
                    text="visible evidence",
                )
            ]
        )

    async def list_prompts(
        self,
        params: types.PaginatedRequestParams | None = None,
    ) -> types.ListPromptsResult:
        del params
        return types.ListPromptsResult(prompts=[types.Prompt(name="test-prompt")])

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str] | None = None,
    ) -> types.GetPromptResult:
        assert name == "test-prompt"
        assert arguments == {"topic": "python"}
        return types.GetPromptResult(description="fixture prompt", messages=[])


@asynccontextmanager
async def proxy_session(upstream: FakeUpstream) -> AsyncGenerator[ClientSession]:
    proxy: Server[dict[str, Any], Any] = Server("linkedin-mcp-server")
    _register_proxy_handlers(proxy, cast(ClientSession, upstream))
    server_send, client_receive = anyio.create_memory_object_stream[SessionMessage](20)
    client_send, server_receive = anyio.create_memory_object_stream[SessionMessage](20)

    async def run_server() -> None:
        await proxy.run(
            server_receive,
            server_send,
            proxy.create_initialization_options(),
            raise_exceptions=True,
        )

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(run_server)
        async with ClientSession(client_receive, client_send) as session:
            await session.initialize()
            yield session
        task_group.cancel_scope.cancel()


@pytest.mark.asyncio
async def test_proxy_forwards_the_complete_public_mcp_surface() -> None:
    upstream = FakeUpstream()
    observed_progress: list[tuple[float, float | None, str | None]] = []

    async def capture_progress(
        progress: float,
        total: float | None,
        message: str | None,
    ) -> None:
        observed_progress.append((progress, total, message))

    async with proxy_session(upstream) as session:
        tools = await session.list_tools()
        result = await session.call_tool(
            "linkedin.test.read",
            {},
            progress_callback=capture_progress,
        )
        resources = await session.list_resources()
        templates = await session.list_resource_templates()
        resource = await session.read_resource(AnyUrl("example://resources/test"))
        prompts = await session.list_prompts()
        prompt = await session.get_prompt("test-prompt", {"topic": "python"})

    assert tools.tools[0].annotations is not None
    assert tools.tools[0].annotations.readOnlyHint is True
    assert result.structuredContent == {"status": "completed"}
    assert upstream.progress_forwarded is True
    assert observed_progress == [(1.0, 1.0, "done")]
    assert resources.resources[0].name == "test evidence"
    assert templates.resourceTemplates[0].name == "Example resource"
    resource_content = resource.contents[0]
    assert isinstance(resource_content, types.TextResourceContents)
    assert resource_content.text == "visible evidence"
    assert prompts.prompts[0].name == "test-prompt"
    assert prompt.description == "fixture prompt"


def test_proxy_decodes_text_and_binary_resource_contents() -> None:
    text = _read_resource_content(
        types.TextResourceContents(
            uri=AnyUrl("example://resources/text"),
            mimeType="text/plain",
            text="visible",
        )
    )
    blob = _read_resource_content(
        types.BlobResourceContents(
            uri=AnyUrl("example://resources/blob"),
            mimeType="application/octet-stream",
            blob=base64.b64encode(b"binary").decode("ascii"),
        )
    )

    assert text.content == "visible"
    assert blob.content == b"binary"


@pytest.mark.asyncio
async def test_stdio_proxy_connects_initializes_and_runs_the_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    @asynccontextmanager
    async def fake_http(_: str) -> AsyncGenerator[tuple[object, object, None]]:
        events.append("http-connected")
        yield object(), object(), None

    class FakeSession:
        async def __aenter__(self) -> FakeSession:
            events.append("upstream-entered")
            return self

        async def __aexit__(self, *_: object) -> None:
            events.append("upstream-exited")

        async def initialize(self) -> Any:
            events.append("initialized")
            return SimpleNamespace(
                serverInfo=SimpleNamespace(
                    name="linkedin-mcp-server",
                    version="1.0.0",
                    websiteUrl=None,
                    icons=None,
                ),
                instructions="fixture instructions",
            )

    class FakeProxy:
        def create_initialization_options(self) -> object:
            return object()

        async def run(self, _: object, __: object, ___: object) -> None:
            events.append("proxy-ran")

    @asynccontextmanager
    async def fake_stdio() -> AsyncGenerator[tuple[object, object]]:
        events.append("stdio-opened")
        yield object(), object()

    def fake_session(*_: object, **__: object) -> Any:
        return FakeSession()

    def fake_server(*_: object, **__: object) -> Any:
        events.append("proxy-created")
        return FakeProxy()

    def fake_register(_: Any, __: Any) -> None:
        events.append("handlers-registered")

    monkeypatch.setattr(proxy_module, "streamable_http_client", fake_http)
    monkeypatch.setattr(proxy_module, "ClientSession", fake_session)
    monkeypatch.setattr(proxy_module, "Server", fake_server)
    monkeypatch.setattr(proxy_module, "stdio_server", fake_stdio)
    monkeypatch.setattr(proxy_module, "_register_proxy_handlers", fake_register)

    await proxy_module.run_stdio_proxy("http://127.0.0.1:8000/mcp")

    assert events == [
        "http-connected",
        "upstream-entered",
        "initialized",
        "proxy-created",
        "handlers-registered",
        "stdio-opened",
        "proxy-ran",
        "upstream-exited",
    ]
