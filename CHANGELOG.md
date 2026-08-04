# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Read the nearest current member introduction card, ignore self-only
  verification and guidance prompts, and retain visible top-card company and
  education summaries from LinkedIn's semantic organization buttons.
- Treat LinkedIn's visible post-success alert and exact View post link as the
  primary publication postcondition, preserve that confirmation across a
  post-click browser timeout, and classify a visible publishing rejection as a
  verified failure.

## [0.16.0] - 2026-08-04

### Added

- Add one shared local runtime that accepts simultaneous stdio and loopback
  Streamable HTTP clients while retaining one Chromium context, account
  profile, pacing history, and browser worker.
- Add fair per-client scheduling, opaque MCP-session identity, shared-runtime
  health and queue status, and transparent stdio bridges that automatically
  elect or attach to the healthy owner.
- Bind attachment to the same account, package version, and SHA-256 effective
  runtime-configuration fingerprint so conflicting client policies fail safely.
- Add multi-client protocol coverage for concurrent startup, transport
  forwarding, client disconnects, request and draft isolation, cursor
  ownership, cancellation, and account-global write idempotency.
- Add `status` and `stop` commands with non-secret exact-owner metadata,
  graceful queue draining, and safe lock release.
- Add explicit `profile create`, `profile status`, and recoverable
  `profile reset` commands while preserving automatic first-run profile
  creation during normal server startup.
- Add LinkedIn-only `login` and visible, clean-reopen-verified `logout`
  commands protected by the same account lock as the server.
- Add the native GitHub Sponsor button and a concise README sponsor request.
- Add canonical Glama maintainer metadata so its repository-backed listing can
  refresh from this release.

### Changed

- Delegate interactive versus unattended write approval to each MCP client's
  durable per-tool policy while keeping destructive execute annotations as the
  confirmation-requesting default.
- Document exact-tool Codex pre-approval for recurring post publishing without
  weakening server scopes, immutable previews, idempotency, revalidation, or
  postcondition checks.
- Scope request replay, in-flight coalescing, prepared actions, and pagination
  cursors to the originating MCP session. Reserve continuation cursors before
  queue waiting so pacing and fair scheduling cannot expire or double-consume
  them.
- Keep each browser-backed tool call atomic, use a fresh temporary Page for the
  call, and schedule clients only between calls. Active writes continue to a
  terminal result after client cancellation; abandoned queued work and active
  reads can be cancelled safely.
- Replace invitation-only immutable snapshot pagination with the shared live,
  deduplicated cursor contract. `linkedin.invitations.list` `4.0.0` now rescans
  bounded visible prefixes and retains exact count reconciliation for terminal
  completion.
- Make lock conflicts actionable without manual PID discovery or lock-file
  deletion, and document browser-profile archive retention.
- Keep the Streamable HTTP container, lock, queue, pacing, cursors, drafts, and
  other process-local state alive for the full listener lifetime instead of
  recreating them around individual HTTP requests.
- Use one clear, capability-first product description across the README,
  package, registry, desktop bundle, and container metadata.
- Use a faithful compact variant where a registry enforces a shorter metadata
  limit.
- Move the Star and Sponsor calls to action into one focused README support
  section instead of repeating them in the hero and footer.
- Present a neutral trademark and non-affiliation disclaimer before the README
  product description, and clarify user responsibility for platform terms,
  account risk, applicable law, and third-party rights.
- Replace the duplicated capability summaries with one grouped function-level
  table covering every supported LinkedIn domain.
- Enable every currently implemented capability by default while preserving
  prepare/execute confirmation for actions that change LinkedIn; document
  optional read-only and Jobs-and-People restriction presets.
- Rework the README into a concise onboarding path with one-click installers,
  self-contained client-specific instructions, concise first-login guidance,
  example prompts, and focused supporting documentation.

### Fixed

- Wait through LinkedIn's visible post-composer loader, avoid clicking disabled
  Save and Done controls when settings are unchanged, and report failures before
  the final Post control as not submitted instead of uncertain.
- Preserve exact immutable evidence for dynamically changing Posts search cards
  instead of failing after a valid visible result was parsed.
- Clarify in the public post-creation schema that `content.mode`, not `kind`, is
  the required discriminator.

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

[Unreleased]: https://github.com/prakharagarwal-dev/linkedin-mcp-server/compare/v0.16.0...HEAD
[0.16.0]: https://github.com/prakharagarwal-dev/linkedin-mcp-server/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/prakharagarwal-dev/linkedin-mcp-server/releases/tag/v0.15.0
[0.14.2]: https://github.com/prakharagarwal-dev/linkedin-mcp-server/releases/tag/v0.14.2
[0.14.1]: https://github.com/prakharagarwal-dev/linkedin-mcp-server/releases/tag/v0.14.1
[0.14.0]: https://github.com/prakharagarwal-dev/linkedin-mcp-server/releases/tag/v0.14.0
