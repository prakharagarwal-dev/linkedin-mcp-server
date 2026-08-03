# Offline Testing and Mock Verification

The current acceptance level for every public capability is `mock_verified`.
No default test contacts LinkedIn, uses a real account, or performs a real
account mutation.

All asynchronous collection work must follow
[COLLECTION_VERIFICATION_PROCESS.md](COLLECTION_VERIFICATION_PROCESS.md).
That process makes terminal inventory reconciliation, independent failure
fixtures, cursor-level MCP replay, and honest truncation part of the definition
of done.

`mock_verified` means the capability has:

- strict input/output and MCP schema coverage;
- real policy, scope, queue, executor, evidence, action-draft, hash, expiry,
  and idempotency coverage;
- cursor lifecycle, filter binding, single-use continuation, expiry, capacity,
  stable-identity deduplication, and terminal truncation coverage;
- shared raw-DOM convergence coverage proving that timed idleness is not
  completion and that progress is parsed before a simultaneously rendered end
  marker;
- real Playwright page-object coverage against synthetic semantic HTML;
- an official MCP client round trip;
- expected success, ambiguity, parser-drift, authentication, interruption, and
  verification-failure behavior; and
- workflow coverage when the capability participates in a multi-tool flow.

It does not mean the current LinkedIn DOM has been observed. A capability must
not be described as `live_verified` based only on this suite.

## Test architecture

```text
official MCP test client
  -> production FastMCP tools and resources
  -> production policy and process-local operation store
  -> production asyncio.Queue and one worker
  -> production executor
  -> stateful typed simulator providers

real Playwright Chromium
  -> production page objects
  -> intercepted linkedin.com document requests
  -> synthetic accessible HTML fixtures
```

The two paths are intentionally independent. Stateful workflow providers test
cross-capability mutation semantics. Semantic HTML fixtures test production
Playwright locators and extraction. A defect must not be hidden by making one
mock implement both sides of the assertion.

## Simulator layout

The test-only simulator lives under `tests/simulator/`:

- `state.py` defines jobs, people, companies, posts, comments, invitations,
  connections, conversations, messages, action history, and ordered faults;
- `scenario.py` maps supported LinkedIn URL surfaces to versioned fixtures;
- `browser.py` runs official Playwright Chromium and fulfills document
  requests locally;
- `providers.py` applies confirmed writes to typed simulator state;
- `harness.py` composes the production executor, repository, worker, and
  policy around those providers; and
- `mcp.py` connects the official MCP client to that container.

Most general simulator fixtures have this provenance:

```text
source: synthetic
schema_version: 1
recorded_at: null
```

The invitation fixtures under `tests/fixtures/linkedin/invitations/latest/`
are separately marked `mock_verified`. Their synthetic identities and content
preserve the sanitized Received and Sent card-root and filter structure
inspected on 2026-07-29: the Focused/Other picker, four received radio filters,
and exact sent People target. They contain no live content, authentication
state, raw DOM dump, trace, or personal data.

The invitation-action fixtures under
`tests/fixtures/linkedin/invitations/actions/latest/` preserve the sanitized
current exact-profile Connect link, invitation confirmation and note dialogs,
visible `0/200` counter, paired incoming Accept/Ignore controls, and their
fresh-profile postconditions. Invitation send has only two synthetic terminal
states: a fresh profile showing Pending succeeds, while one still showing
Connect fails. They contain no live identity or account state.

The Jobs fixtures under `tests/fixtures/linkedin/jobs/latest/` are also
`mock_verified`. They preserve the current virtualized card shell and
pagination controls, every visible All Filters section, zero-result
recommendation replacement, optional company identity, expanded description,
Easy Apply/external/unavailable application methods, and hiring-team structure
observed on 2026-07-30. They contain synthetic identities and text only—no raw
live DOM, authentication state, trace, or account data.

The Company fixtures under `tests/fixtures/linkedin/companies/latest/` are
`mock_verified` from the authenticated visible UI inspected on 2026-07-30.
They preserve the current side-panel filter mechanics, all five filter
families, all eight size choices, exact location/industry typeaheads, submitted
query parameters, result identity and pagination, and the fixed
Overview-plus-About read. They contain synthetic identities and text only.

The Posts fixtures under `tests/fixtures/linkedin/posts/latest/` are
`mock_verified` from authenticated visible search and detail surfaces
inspected on 2026-07-30. Detail variants preserve current exact-menu identity,
body expansion, typed media/link/document/poll structures, engagement
controls, and bounded repost-original behavior. They contain no live post,
author, raw DOM, authentication state, trace, or account data.

The sanitized `personal-post-composer.html` and `post-engagement.html`
fixtures are also `mock_verified` from the authenticated visible UI inspected
on 2026-07-30. They preserve all nine personal composer modes, nested
image/video/document/poll/celebration/event/hiring/expert controls, settings,
the current comment photo/GIF controls, native UGC discussion aliases, and the
six current reactions. Discovery uploaded synthetic files into draft-only
editors but never invoked Post, Comment, Reply, or a reaction option.

Recorded and sanitized fixtures can be introduced later without changing the
scenario or workflow contracts. Raw traces, HAR files, cookies, browser
profiles, scripts, tokens, and personal data must never become fixtures.

The collection variants deliberately include no-progress windows, delayed
appended tails, same-count virtualized replacement, delayed initial search
results, delayed comment expansion, explicit end markers, transient loaders,
and valid trailing-hyphen profile slugs. Invitation-specific fixtures add
every supported entity type, every current filter, Received/Sent root
differences, zero inventory, recommendations, count mismatch, one count-change
restart, repeated count change, identity ambiguity, duplicate identity, old
layout rejection, live result bounds, exact-count-only completion, six-view union
deduplication, and cross-view conflict rejection.

Invitation cursor tests cover bounded live prefixes, disjoint page identities,
page-size changes, canonical direction/filter binding, provider revisits,
cumulative traversal targets, terminal exact reconciliation, honest safety
bounds, reservation, abort, single use, capacity eviction, and process-restart
invalidation.

## Coverage ownership

`tests/verification_manifest.py` owns the explicit mapping for all 33 tools.
The manifest test fails when:

- the public tool registry and verification inventory differ;
- a named test file is missing;
- a write tool lacks page, action, runtime, and workflow ownership;
- a search-filter model gains an unaccounted field;
- a member-profile selector, Company-search filter, or reaction enum changes silently; or
- a generic browser, click, JavaScript, network, navigation, queue, or pacing
  control appears in the public MCP schema.

All seven prepare/execute families share a conformance suite that verifies
payload-hash tampering, preview tampering, one verified effect, and
idempotent replay.

## Network isolation

`tests/conftest.py` blocks non-loopback Python socket connections for every
test. Unix sockets and loopback connections remain available for Playwright
and Streamable HTTP protocol tests. The repository has no live LinkedIn tests;
the complete suite is offline.

The semantic browser also aborts any document route not registered by the
simulator.

## Live acceptance

The former one-off live-acceptance runners have been removed. The repository
contains no executable live LinkedIn test scripts, and `pytest` remains fully
offline and network-blocked.

When current-UI validation is needed, use a confirmation-capable MCP client
with the minimum required effects, scopes, and surfaces. Convert only the
sanitized behavior into offline fixtures; never retain live identities,
content, raw DOM, traces, cookies, or browser state. Fixture manifests record
only sanitized provenance and the UI behaviors represented by each fixture.

## Test groups

| Group | Responsibility |
| --- | --- |
| `tests/unit/` | Models, URLs, policy, repository, queue, pacing, cursor state, browser lifecycle, page objects |
| `tests/contract/` | MCP discovery, schemas, annotations, evidence, write conformance, transports |
| `tests/simulator/` | Typed state, synthetic site, faults, real Playwright routing |
| `tests/workflows/` | Multi-page job scan, job/referral, connection/message, and post-engagement journeys |
| `tests/package/` | Wheel contents, entry point, forbidden dependencies, secret/profile exclusion |

## Running verification

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv run pytest --cov=linkedin_mcp --cov-branch
uv build
```

The package test also performs an offline wheel build and proves that tests,
simulator code, profiles, secrets, and other repositories are not shipped.

The enforced whole-repository branch floor is 85%. The accepted public-release
run reached 85.24% across 11,953 production statements and 4,078 branches. The
safety-critical executor, operation/action store, capability registry, and MCP
server modules are individually at 96–98%; strict domain contracts are at 91%.
Dynamic LinkedIn layout adapters retain lower numeric coverage because the
suite prioritizes meaningful semantic variants over invoking unreachable
defensive branches solely to increase a percentage.

## Maintenance rule

A new tool is not `mock_verified` until it has:

1. a manifest entry;
2. strict schema and policy tests;
3. synthetic page fixtures or an explicit non-browser operational boundary;
4. normal, empty, malformed, ambiguous, and bounded cases;
5. evidence assertions for reads;
6. the shared safety suite for writes;
7. an MCP round trip; and
8. a workflow case when it composes with other capabilities.

Future sanitized recordings should add variants alongside synthetic fixtures.
They should improve DOM realism without replacing deterministic negative and
fault-injection scenarios.
