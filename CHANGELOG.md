# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Enable every currently implemented capability by default while preserving
  prepare/execute confirmation for actions that change LinkedIn; document
  optional read-only and Jobs-and-People restriction presets.
- Rework the README into a concise onboarding path with one universal package
  configuration, one-click links and compact setup instructions for popular
  MCP clients, first-login prompts, and focused configuration and
  troubleshooting references.

## [0.15.0] - 2026-08-02

### Changed

- Remove the redundant `LINKEDIN_MCP_LIVE_ENABLED` master switch. Starting the
  server now always permits browser authentication while registered
  capabilities remain independently restricted by configured surfaces, scopes,
  effects, authentication guards, and write confirmations.

## [0.14.2] - 2026-08-02

### Added

- Document the complete local data lifecycle, third-party sharing, retention,
  deletion controls, and privacy contact path in the README and a standalone
  privacy policy.
- Advertise the project and LinkedIn privacy policies in the MCPB manifest and
  the project privacy policy in PyPI metadata.

## [0.14.1] - 2026-08-01

### Fixed

- Advertise the LinkedIn MCP server package version during MCP initialization
  instead of inheriting the Python SDK version.
- Publish GHCR images for both `linux/amd64` and `linux/arm64`.
- Produce byte-reproducible MCPB release bundles from tracked source files.

## [0.14.0] - 2026-07-31

### Added

- Initial public release of the standalone Python MCP server.
- Jobs, people, companies, posts, invitations, connections, and messaging tools
  that use LinkedIn's visible website.
- Cursor pagination, one-worker queueing, internal pacing, immutable evidence,
  and process-local operation state.
- Hash-locked prepare/execute contracts with scopes, idempotency, native client
  confirmation annotations, and visible postcondition checks.
- Persistent Playwright Chromium authentication profile, stdio and loopback
  Streamable HTTP transports, and an optional container image.
- Fully offline `mock_verified` simulator, semantic fixtures, protocol tests,
  workflow tests, package tests, and network isolation.
- Official MCP Registry metadata, an MCPB desktop bundle manifest, a project
  icon, and automated PyPI, GitHub Release, and GHCR publication.

### Changed

- The PyPI distribution is named `linkedin-mcp-local` because the unrelated
  `linkedin-mcp-server` name is already registered. The `linkedin-mcp`
  executable, Python import package, repository, and MCP server identity are
  unchanged.

[Unreleased]: https://github.com/prakharagarwal-dev/linkedin-mcp-server/compare/v0.15.0...HEAD
[0.15.0]: https://github.com/prakharagarwal-dev/linkedin-mcp-server/releases/tag/v0.15.0
[0.14.2]: https://github.com/prakharagarwal-dev/linkedin-mcp-server/releases/tag/v0.14.2
[0.14.1]: https://github.com/prakharagarwal-dev/linkedin-mcp-server/releases/tag/v0.14.1
[0.14.0]: https://github.com/prakharagarwal-dev/linkedin-mcp-server/releases/tag/v0.14.0
