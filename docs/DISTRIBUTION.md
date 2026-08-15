# Distribution and registry coverage

Last verified: 2026-08-15

Use this exact description on every public surface that accepts it:

> A LinkedIn MCP server to find jobs, search people, research companies, manage
> your network, publish and engage with posts, and read or send messages.

The Official MCP Registry is the sole exception: its schema limits
`description` to 100 characters, so `server.json` contains the tested compact
value required for a valid record.

## Published packages

| Surface | State | Canonical location |
| --- | --- | --- |
| PyPI | Live | [`linkedin-mcp-local`](https://pypi.org/project/linkedin-mcp-local/) |
| GitHub Container Registry | Live | [`linkedin-mcp-server`](https://github.com/prakharagarwal-dev/linkedin-mcp-server/pkgs/container/linkedin-mcp-server) |
| GitHub Releases | Live | [Versioned MCPB bundles and checksums](https://github.com/prakharagarwal-dev/linkedin-mcp-server/releases) |

## Registries and catalogs

| Surface | State | Listing or submission |
| --- | --- | --- |
| Official MCP Registry | Live | [`io.github.prakharagarwal-dev/linkedin-mcp-server`](https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.prakharagarwal-dev%2Flinkedin-mcp-server) |
| Glama | Live | [Server listing](https://glama.ai/mcp/servers/prakharagarwal-dev/linkedin-mcp-server) |
| Smithery | Live | [Server listing](https://smithery.ai/servers/prakharagarwal3031/linkedin-mcp-server) |
| Docker MCP Catalog | Under review | [Registry pull request](https://github.com/docker/mcp-registry/pull/4591) |
| Cline MCP Marketplace | Under review | [Marketplace request](https://github.com/cline/mcp-marketplace/issues/2164) |
| Awesome MCP Servers | Under review | [Catalog pull request](https://github.com/punkpeye/awesome-mcp-servers/pull/11316) |
| MCP Find | Under review | [Catalog pull request](https://github.com/MCPFind/mcp-find/pull/137) |
| MCP.Directory | Under review | Repository submission is queued; the catalog pulls its description from the canonical README |
| ToolRoute | Under review | Free catalog submission accepted on 2026-08-15 |
| mcpservers.org | Submitted | Free submission accepted for review on 2026-08-15 |
| PulseMCP | Awaiting automatic ingestion | New submissions are paused; PulseMCP directs publishers to the Official MCP Registry and says it will ingest those records |

The Official MCP Registry record currently exposes the immutable OCI package.
The registry publishing workflow now adds the matching MCPB release URL and
SHA-256 checksum when it publishes the next version; previously published
registry versions cannot be amended.

Official Registry consumers, including GitHub MCP discovery and Visual Studio
Code, receive the server through that upstream record rather than a separate
submission.

## Blocked or inapplicable submission paths

| Surface | Reason |
| --- | --- |
| MCP.so | Its current submission flow requires a paid listing; no purchase is authorized for registry coverage |
| Cursor Marketplace | Publication requires accepting publisher terms and packaging a Cursor plugin; legal acceptance remains an owner action |
| Claude Desktop extension directory | Its interest form requires accepting directory terms, and its current selection criteria prioritize MIT-licensed Node.js bundles rather than this Apache-licensed Python bundle |
| Claude Rules | Its free listing requires creating or connecting an account through GitHub or Google OAuth |
| FindMCP | Its public form and a direct valid submission both fail at `/api/submit` with HTTP 500 |
| MCP Servers Directory | Its submission endpoint currently returns an empty response or HTTP 502 |
| MCPub | It accepts hosted MCP endpoints; this server is a local stdio package, not a hosted remote service |
| MCP House | Its showcase is for servers built with the TypeScript `mcp-framework` project |

This ledger covers maintained package registries, MCP registries, and curated
catalogs with a public submission path. Scraped mirrors, abandoned lists, and
sites with no publisher-controlled submission or correction path are not
treated as distribution targets.

After each release, verify every live listing, update pending-review links,
and record the new verification date here. Do not create a second product
description for catalog-specific positioning.
