# Build Status

Updated: 2026-08-01

## Release verification

- [`v0.14.0`](https://github.com/prakharagarwal-dev/linkedin-mcp-server/releases/tag/v0.14.0)
  is published on GitHub with an attested wheel, source archive, MCPB bundle,
  and verified SHA-256 checksums.
- Corrected `v0.14.1` artifacts are prepared in
  [pull request 10](https://github.com/prakharagarwal-dev/linkedin-mcp-server/pull/10).
  Ruff, strict Pyright, all 435 offline tests, package builds, Twine checks,
  MCPB validation, and official-registry metadata validation pass locally.
- The public `v0.14.0` GHCR image is anonymously readable, has a signed GitHub
  provenance attestation and SBOM, passes `linkedin-mcp doctor`, completes an
  MCP handshake, and exposes 31 tools. Publication validation found that this
  first image is amd64-only; `v0.14.1` adds native arm64 publication.
- MCP initialization tests now verify the package version over in-memory,
  stdio, and loopback Streamable HTTP transports. MCPB builds use only tracked
  files and are byte-reproducible across independent builds.

## Publication status

- GitHub repository and `v0.14.0` release: public.
- GHCR: `v0.14.0` published and attested; multi-architecture `v0.14.1`
  publication is prepared.
- MCP.Directory: accepted into its review queue.
- MCP.so: submitted in
  [`chatmcp/mcpso#3393`](https://github.com/chatmcp/mcpso/issues/3393).
- Docker MCP Catalog: submitted in
  [`docker/mcp-registry#4591`](https://github.com/docker/mcp-registry/pull/4591).
- Cline Marketplace: README-only installation was verified with Cline CLI
  3.0.48, including all 31 tool schemas, and submitted in
  [`cline/mcp-marketplace#2164`](https://github.com/cline/mcp-marketplace/issues/2164).
- Awesome MCP Servers: submitted in
  [`punkpeye/awesome-mcp-servers#11316`](https://github.com/punkpeye/awesome-mcp-servers/pull/11316);
  that directory requires a verified Glama listing before merge.
- MCPRepository: accepted into its processing queue at the
  [canonical listing URL](https://mcprepository.com/prakharagarwal-dev/linkedin-mcp-server).
- PyPI: awaiting creation of the `linkedin-mcp-local` pending Trusted
  Publisher for `prakharagarwal-dev/linkedin-mcp-server`, workflow
  `publish.yml`, environment `pypi`.
- Official MCP Registry: validated metadata is ready, and the release workflow
  now uses secretless GitHub OIDC publication after PyPI succeeds.
- GitHub MCP Registry and PulseMCP: await automatic ingestion from the Official
  MCP Registry.
- Smithery: publication is blocked because Smithery CLI 1.2.0 does not support
  the official MCPB `uv` runtime. The upstream defect is tracked in
  [`arcadeai-labs/smithery-cli#801`](https://github.com/arcadeai-labs/smithery-cli/issues/801).
- Glama: maintainer verification requires an interactive GitHub OAuth session.
- Cursor Marketplace: requires the publisher application and acceptance of the
  current publisher terms by the account owner.
- MCP Market and MCPServers.org: their free submission queues require
  browser-only forms; no paid fast-track option is being used.

No LinkedIn credentials, cookies, browser profiles, or reusable test sessions
are shared with publication services.
