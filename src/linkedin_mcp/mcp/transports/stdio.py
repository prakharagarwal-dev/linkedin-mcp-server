"""Transparent stdio bridge to the one shared loopback MCP runtime."""

from __future__ import annotations

import base64
from typing import Any

from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server
from mcp.server.lowlevel.helper_types import ReadResourceContents
from mcp.server.stdio import stdio_server
from pydantic import AnyUrl

from linkedin_mcp import __version__


async def run_stdio_proxy(endpoint: str) -> None:
    """Expose stdio while forwarding the complete MCP contract to the shared runtime."""

    async with (
        streamable_http_client(endpoint) as (read_stream, write_stream, _),
        ClientSession(
            read_stream,
            write_stream,
            client_info=types.Implementation(
                name="linkedin-mcp-stdio-bridge",
                version=__version__,
            ),
        ) as upstream,
    ):
        initialized = await upstream.initialize()
        proxy: Server[dict[str, Any], Any] = Server(
            name=initialized.serverInfo.name,
            version=initialized.serverInfo.version,
            instructions=initialized.instructions,
            website_url=initialized.serverInfo.websiteUrl,
            icons=initialized.serverInfo.icons,
        )
        _register_proxy_handlers(proxy, upstream)
        async with stdio_server() as (downstream_read, downstream_write):
            await proxy.run(
                downstream_read,
                downstream_write,
                proxy.create_initialization_options(),
            )


def _register_proxy_handlers(proxy: Server[dict[str, Any], Any], upstream: ClientSession) -> None:
    @proxy.list_tools()
    async def list_tools(
        request: types.ListToolsRequest | None = None,
    ) -> types.ListToolsResult:
        return await upstream.list_tools(params=request.params if request is not None else None)

    @proxy.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict[str, Any]) -> types.CallToolResult:
        request_context = proxy.request_context
        progress_token = (
            request_context.meta.progressToken if request_context.meta is not None else None
        )

        async def report_progress(
            progress: float,
            total: float | None,
            message: str | None,
        ) -> None:
            if progress_token is not None:
                await request_context.session.send_progress_notification(
                    progress_token=progress_token,
                    progress=progress,
                    total=total,
                    message=message,
                )

        return await upstream.call_tool(
            name,
            arguments,
            progress_callback=report_progress if progress_token is not None else None,
        )

    @proxy.list_resources()
    async def list_resources(
        request: types.ListResourcesRequest | None = None,
    ) -> types.ListResourcesResult:
        return await upstream.list_resources(params=request.params if request is not None else None)

    @proxy.list_resource_templates()
    async def list_resource_templates() -> list[types.ResourceTemplate]:
        result = await upstream.list_resource_templates()
        return result.resourceTemplates

    @proxy.read_resource()
    async def read_resource(uri: AnyUrl) -> list[ReadResourceContents]:
        result = await upstream.read_resource(uri)
        return [_read_resource_content(content) for content in result.contents]

    @proxy.list_prompts()
    async def list_prompts(
        request: types.ListPromptsRequest | None = None,
    ) -> types.ListPromptsResult:
        return await upstream.list_prompts(params=request.params if request is not None else None)

    @proxy.get_prompt()
    async def get_prompt(
        name: str,
        arguments: dict[str, str] | None,
    ) -> types.GetPromptResult:
        return await upstream.get_prompt(name, arguments)

    registered_handlers = (
        list_tools,
        call_tool,
        list_resources,
        list_resource_templates,
        read_resource,
        list_prompts,
        get_prompt,
    )
    del registered_handlers


def _read_resource_content(
    content: types.TextResourceContents | types.BlobResourceContents,
) -> ReadResourceContents:
    meta = content.meta
    if isinstance(content, types.TextResourceContents):
        return ReadResourceContents(
            content=content.text,
            mime_type=content.mimeType,
            meta=meta,
        )
    return ReadResourceContents(
        content=base64.b64decode(content.blob, validate=True),
        mime_type=content.mimeType,
        meta=meta,
    )
