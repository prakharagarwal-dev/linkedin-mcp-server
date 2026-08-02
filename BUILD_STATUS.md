# Build Status

Updated: 2026-08-02

## Release verification

- [v0.15.0](https://github.com/prakharagarwal-dev/linkedin-mcp-server/releases/tag/v0.15.0)
  is the current public release. Its wheel, source archive, and MCPB bundle are
  checksummed and carry GitHub build provenance attestations tied to merge
  commit 78c57fb23d82b730afa70b8fb3de9abf158b1ae4. The MCPB SHA-256 is
  869b31442c8207441c123f24161598904f00e138c95ca882250744940955eb72.
- [Pull request 19](https://github.com/prakharagarwal-dev/linkedin-mcp-server/pull/19)
  merged after Ruff, strict Pyright, package checks, CodeQL, and all 436
  offline tests passed on Python 3.12 and 3.13. A clean wheel installation
  passes `linkedin-mcp --help`, the release MCPB passes the official validator,
  and the Official MCP Registry metadata passes publisher validation.
- The public v0.15.0 GHCR image is anonymously readable at digest
  sha256:7fda5591f9ef9c97a48c483c3478bbcc285ab5aaaf8c2a01c0f3806928f6a607.
  The release workflow built and attested its native linux/amd64 and
  linux/arm64 images.
- The release and registry workflows completed successfully:
  [artifacts, PyPI, and GHCR](https://github.com/prakharagarwal-dev/linkedin-mcp-server/actions/runs/30746557443)
  and [Official MCP Registry publication](https://github.com/prakharagarwal-dev/linkedin-mcp-server/actions/runs/30746557059).

## Live distributions

- GitHub repository and
  [v0.15.0 release](https://github.com/prakharagarwal-dev/linkedin-mcp-server/releases/tag/v0.15.0):
  public, checksummed, and attested.
- PyPI:
  [linkedin-mcp-local 0.15.0](https://pypi.org/project/linkedin-mcp-local/0.15.0/)
  is published through GitHub OIDC Trusted Publishing.
- GHCR: ghcr.io/prakharagarwal-dev/linkedin-mcp-server:0.15.0 is public,
  multi-architecture, and attested.
- Official MCP Registry:
  [io.github.prakharagarwal-dev/linkedin-mcp-server 0.15.0](https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.prakharagarwal-dev%2Flinkedin-mcp-server)
  is active, marked latest, and points to the immutable 0.15.0 OCI package
  without the removed `LINKEDIN_MCP_LIVE_ENABLED` option.
- [Glama](https://glama.ai/mcp/servers/prakharagarwal-dev/linkedin-mcp-server)
  has a public canonical listing linked to the intended GitHub repository.
- [MCPRepository](https://mcprepository.com/prakharagarwal-dev/linkedin-mcp-server)
  has a public canonical listing. Its cached README currently trails the
  repository release and must refresh through the directory's ingestion job.
- MCP Central has ingested the Official MCP Registry record and exposes the
  server as active at 0.14.1. Its 0.14.2 upstream refresh is still pending.

## Submitted and awaiting review

- Docker MCP Catalog:
  [docker/mcp-registry#4591](https://github.com/docker/mcp-registry/pull/4591)
  is open for review and is pinned to the v0.14.2 release commit.
- Cline Marketplace:
  [cline/mcp-marketplace#2164](https://github.com/cline/mcp-marketplace/issues/2164)
  is open for review. Its submission now references v0.14.2, PyPI, GHCR, and
  the verified Official MCP Registry record.
- MCP.so:
  [chatmcp/mcpso#3393](https://github.com/chatmcp/mcpso/issues/3393)
  is open for review with current v0.14.2 artifact and registry metadata.
- Awesome MCP Servers:
  [punkpeye/awesome-mcp-servers#11316](https://github.com/punkpeye/awesome-mcp-servers/pull/11316)
  is open for review. The entry includes the required Glama score badge and
  its submission check passes.
- MCP.Directory accepted the canonical repository into its review queue.
- MCPServers.org accepted the corrected free submission using
  prakharagarwal3031@gmail.com; it is awaiting moderation.
- Cursor Marketplace received the individual publisher application and is
  awaiting review.

## Upstream ingestion and external blockers

- GitHub MCP Registry is curated and does not currently expose this server.
  The canonical Official MCP Registry record is published, but GitHub offers
  no public self-service submission route for this catalog.
- PulseMCP is a read-only sub-registry and does not accept direct
  submissions. Its public catalog has not yet ingested this Official MCP
  Registry record.
- Glama's public listing works, but its GitHub-authenticated profile onboarding
  leaves the required Continue control disabled after a valid publisher choice.
  Maintainer-profile completion is blocked by that UI behavior.
- Smithery CLI 1.2.0 accepts MCPB paths in its documented command but rejects
  the official server.type = "uv" runtime before upload with
  "Could not determine bundle runtime from manifest". Smithery's web
  publisher currently exposes only public Streamable HTTP URL publication.
  Publishing there would require an unsupported bundle workaround or an
  architecture change, so no misleading release was created.
- Anthropic's Desktop Extensions form is complete and ready, but its Google
  Forms upload is blocked because the submitting Google account is over its
  Drive quota. The verified v0.14.2 MCPB has not been submitted yet.
- MCP Market exposes only a $29 one-time paid listing option. No purchase was
  made.

No LinkedIn credentials, cookies, browser profiles, reusable test sessions, or
local operation state are shared with publication services.
