# Build Status

Updated: 2026-08-01

## Release verification

- `v0.14.0` is published on GitHub with an attested wheel, source archive,
  MCPB bundle, and SHA-256 checksums.
- The merged release commit passed Ruff, strict Pyright, 435 offline tests on
  Python 3.12 and 3.13, package builds, and CodeQL.
- The Docker image builds locally, passes `linkedin-mcp doctor`, completes an
  MCP handshake, and exposes 31 tools.

## Publication status

- GitHub release: published.
- MCP.Directory: submitted for review.
- MCP.so: submitted in `chatmcp/mcpso#3393`.
- Docker MCP Catalog: submitted in `docker/mcp-registry#4591`.
- PyPI: awaiting creation of the `linkedin-mcp-local` pending Trusted
  Publisher for `prakharagarwal-dev/linkedin-mcp-server`, workflow
  `publish.yml`, environment `pypi`.
- GHCR: the first release run exposed a missing Buildx setup step for
  provenance and SBOM output. The workflow fix and an explicit existing-tag
  retry path are prepared and validated.
- Official MCP Registry: validated metadata is ready, and the release workflow
  now uses secretless GitHub OIDC publication after PyPI succeeds.
- Downstream MCP registries: await the canonical PyPI and Official Registry
  publications required for package verification and ingestion.

No LinkedIn credentials, cookies, browser profiles, or reusable test sessions
are shared with publication services.
