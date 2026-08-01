# Build Status

Updated: 2026-08-01

## Release verification

- [`v0.14.1`](https://github.com/prakharagarwal-dev/linkedin-mcp-server/releases/tag/v0.14.1)
  is the corrected public release. Its attested wheel, source archive, and
  MCPB bundle pass the published `SHA256SUMS`; the MCPB SHA-256 is
  `309c694f8560bd41c27d564f58b2a2dca314cadbb96212f2fac8ddd02d292d64`.
- [Pull request 10](https://github.com/prakharagarwal-dev/linkedin-mcp-server/pull/10)
  merged after Ruff, strict Pyright, package checks, CodeQL, and all 435
  offline tests passed on Python 3.12 and 3.13.
- The public `v0.14.1` GHCR image is anonymously readable at digest
  `sha256:da9846ada5031a48cd8eefa82818b85eed76bcb92ed03b2fd0cc26bcba4e609c`.
  It contains native linux/amd64 and linux/arm64 images plus provenance
  attestations. Both architectures pass `linkedin-mcp doctor`; MCP handshakes
  advertise server version `0.14.1` and expose 31 tools.
- MCP initialization tests now verify the package version over in-memory,
  stdio, and loopback Streamable HTTP transports. MCPB builds use only tracked
  files and are byte-reproducible across independent builds.
- Virtualized connection, inbox, and message-history collection now retries one
  idle wheel delivery within the existing bounded polling budget. The three
  formerly flaky browser cases passed 90 consecutive stress iterations, and
  the complete 437-test offline suite passes locally with Ruff and strict
  Pyright.

## Publication status

- GitHub repository and `v0.14.1` release: public, checksummed, and attested.
- GHCR: multi-architecture `v0.14.1` is public and attested.
- MCP.Directory: accepted into its review queue.
- MCP.so: submitted in
  [`chatmcp/mcpso#3393`](https://github.com/chatmcp/mcpso/issues/3393).
- Docker MCP Catalog: submitted in
  [`docker/mcp-registry#4591`](https://github.com/docker/mcp-registry/pull/4591),
  pinned to the `v0.14.1` release commit. Catalog validation and its generated
  image build pass with 31 discovered tools.
- Cline Marketplace: README-only installation was verified with Cline CLI
  3.0.48, including all 31 tool schemas, and submitted in
  [`cline/mcp-marketplace#2164`](https://github.com/cline/mcp-marketplace/issues/2164).
- Claude Desktop Extensions: the verified `v0.14.1` MCPB is published on the
  GitHub release. Anthropic's public-directory interest form requires an
  authenticated account-owner submission and subsequent human review.
- Awesome MCP Servers: submitted in
  [`punkpeye/awesome-mcp-servers#11316`](https://github.com/punkpeye/awesome-mcp-servers/pull/11316);
  that directory requires a verified Glama listing before merge.
- MCPRepository: accepted into its processing queue at the
  [canonical listing URL](https://mcprepository.com/prakharagarwal-dev/linkedin-mcp-server).
- PyPI: release publication reached GitHub OIDC, but PyPI returned
  `invalid-publisher`. It awaits creation of the `linkedin-mcp-local` pending
  Trusted Publisher for owner `prakharagarwal-dev`, repository
  `linkedin-mcp-server`, workflow `publish.yml`, environment `pypi`.
- Official MCP Registry: OCI-backed metadata passes the official publisher's
  live validation. A dedicated workflow now uses secretless GitHub OIDC and
  verifies the exact public GHCR image independently of PyPI.
- GitHub MCP Registry and PulseMCP: await automatic ingestion from the Official
  MCP Registry.
- MCP Central: its documented publisher endpoint currently resolves to an
  Azure Container Apps hostname with no reachable address record, so the
  publisher cannot connect; its public catalog API remains online.
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
