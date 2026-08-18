# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Remove the central asset store and `ASSET_ROOT_PATH` configuration. Typed
  upload tools now pass client-selected paths directly to Playwright, including
  absolute paths and paths outside the project; capability-specific visible UI
  handling remains inside each tool and LinkedIn decides whether a file type or
  size is accepted.
- Remove the central `AppContainer`. The host now owns process lifecycle
  directly, transport accepts an already configured FastMCP server, and each
  tool receives only its scheduler, concrete page, and optional cursor store at
  registration. Move task execution to `infra/queue/` and generic continuation
  state to `infra/cursor/store.py` without infrastructure importing tool
  contracts.
- Rename the narrowly scoped `execution` package to `queue`; its existing
  `Task` → FIFO `Scheduler` → single `Worker` behavior is unchanged.
- Keep MCP protocol wiring in `transport`, and move shared-process lifecycle,
  account locking, and the private launcher into `host`. Remove redundant
  application-level MCP session identities and bind opaque pagination cursors
  only to their account, capability, and semantic filters so reconnecting
  clients can continue them.
- Replace the capability executor, operation mixins, provider protocols, and
  per-client fair scheduler with a small `Task` → FIFO `Scheduler` → `Worker`
  pipeline. Each tool now owns its execution and optional pagination flow next
  to its page, evidence, and models; cursor state no longer uses queue-time
  leases.
- Remove the duplicate capability registry and custom
  `linkedin.capabilities.list` tool. FastMCP's standard MCP `tools/list`
  response is now the single source of truth for tool discovery, schemas, and
  annotations.
- Remove the process-local call/evidence repository, completed-read replay,
  duplicate-call coalescing, replay flags, and captured-source MCP resource.
  Every tool invocation now executes freshly and returns its result with source
  metadata directly.
- Support native Windows runtime ownership, CIM-brokered startup that survives
  client-owned Job Objects, console handling, and graceful instance-bound
  shutdown alongside POSIX platforms. Run the full
  offline suite in CI on macOS, Windows, and Linux ARM64 in addition to the
  Linux x86-64 Python-version matrix, with explicit UTF-8 fixture decoding and
  distinct evidence identities for every account-changing invocation. Reject
  the unused optional GET event stream so repeated Windows client sessions
  clean up without blocking the shared runtime.
- Run the offline Pytest suite across four work-stealing workers and shorten
  polling delays only for deterministic semantic-site fixtures, without
  changing production browser timing or collection verification rounds; keep
  timing-sensitive fixtures deterministic under load and run every CI matrix
  job with its declared Python interpreter.
- Extend the supported Python runtime range through 3.14 across PyPI, MCPB,
  CI, and contributor metadata.
- Standardize package, bundle, installer, catalog, and marketplace copy on the
  README's outcome-focused product description, retaining only the Official MCP
  Registry's schema-required 100-character variant.
- Publish checksum-pinned MCPB release assets alongside the immutable OCI image
  in future Official MCP Registry versions, and add a maintained distribution
  ledger for package, registry, catalog, and review status.
- Replace the fourteen public prepare/execute tools with seven direct atomic
  action tools: `linkedin.posts.create`, `linkedin.posts.comment`,
  `linkedin.posts.react`, `linkedin.invitations.send`,
  `linkedin.invitations.accept`, `linkedin.invitations.ignore`, and
  `linkedin.messaging.send`.
- Remove server capability scopes, effect allowlists, draft previews, action
  IDs, write idempotency keys, and write replay. MCP clients now own tool
  availability and approval; the server retains exact visible target/state
  inspection, capability-specific upload handling, pacing, bounded execution,
  terminal postcondition verification, and immutable evidence.
- Limit `linkedin.posts.comment` to top-level post comments. Read-only
  discussion results continue to include visible replies and their exact parent
  references.
- Limit `linkedin.posts.react` to exact posts. Comment reaction counts remain
  available through read-only post discussions, but setting reactions on
  comments is no longer exposed.
- Consolidate accumulated action lifecycle tests into current atomic protocol,
  worker, tool-execution, simulator, and workflow coverage while retaining the latest
  semantic page fixtures and safety cases.
- Remove deprecated pagination, title-keyword, and image-tag aliases, unused
  dependencies and helpers, stale publishing-status documentation, and legacy
  runtime-lock parsing. Reorganize fixtures and documentation around the
  current public contract.

### Fixed

- Let concurrent clients wait through the bounded interval between a shared
  runtime acquiring its account lock and publishing owner metadata, preventing
  a second client from abandoning a valid Windows startup election.
- Wait for a real active-member display name when LinkedIn's profile rail is
  still rendering instead of accepting a briefly visible numeric metrics link
  as the acting identity.
- Verify a newly submitted top-level comment only when exactly one new stable
  comment reference matches the requested payload. Treat LinkedIn's separate
  trailing `… more` expansion affordance as UI chrome when matching the exact
  requested text, and never retry or reload after invoking the final Comment
  control.
- Reconcile current invitation inventories when LinkedIn omits zero-count
  Received category controls or the empty Sent People control. Preserve those
  views as explicit `unadvertised_empty_views`, require stable structural empty
  evidence, and continue to fail closed for changed controls or unadvertised cards.
- Accept the single underlying share or UGC-post identity that LinkedIn renders
  for an unchanged requested activity URL when listing comments, commenting, or
  reacting. Post search now classifies selected cards whose stable post or
  author identity falls outside the typed contract instead of aborting valid
  neighboring results.
- Parse current Post-search cards through the same exact header, content, and
  engagement contracts as Post detail. Preserve relationship degree, headline,
  edited age, full expanded text, numeric engagement, and article/job/media
  classification; inventory virtualized card identities before bottom-up
  expansion so cursor pages retain their cumulative prefix.
- Parse compact Company counts such as `161K` and `8M`, keep social-proof text
  out of search-result locations, bind the smallest current company
  introduction region, and prefer the exact About-page associated-member count
  over employee ranges.
- Parse current member experience cards without treating employment type or
  description bullets as company and location fields, bind skill identity to
  the exact accessible endorsement control, and exclude About-section
  expansion and `Top skills` UI chrome. Read current roleless profile-detail
  collection cards and exclude recommendation rails from member-owned
  sections.
- Read the nearest current member introduction card, ignore self-only
  verification and guidance prompts, and retain visible top-card company and
  education summaries from LinkedIn's semantic organization buttons.
- Treat LinkedIn's visible post-success alert and exact View post link as the
  primary publication postcondition, preserve that confirmation across a
  post-click browser timeout, and classify a visible publishing rejection as a
  verified failure.
- Bind each flat visually indented reply to its nearest preceding root comment,
  including discussions with multiple roots in either sort order, and expand
  the current `See previous replies` control without weakening exact
  parent-reference binding. Keep the current comment-card `Author` badge out of
  the actor headline and retain the following visible headline instead.
- Parse the current hiring-team card when its only visible profile link contains
  the member name, connection degree, headline, and role as separate lines.

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
