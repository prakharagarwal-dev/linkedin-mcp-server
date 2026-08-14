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
- real registry, queue, executor, evidence, direct-action, target-inspection,
  attachment-integrity, and terminal-outcome coverage;
- cursor lifecycle, filter binding, single-use continuation, expiry, capacity,
  stable-identity deduplication, and terminal truncation coverage;
- multi-client runtime election, fair scheduling, same-client FIFO ordering,
  session-scoped read replay/cursors, non-coalesced writes, disconnect survival,
  cancellation, and graceful stop coverage;
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
  -> production typed registry and process-local read/evidence store
  -> production fair asyncio scheduler and one worker
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
- `providers.py` applies client-authorized writes to typed simulator state;
- `harness.py` composes the production executor, repository, and worker around
  those providers; and
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
observed through 2026-08-05, including the current single composite profile
link whose separate lines carry name, degree, headline, and role. They contain
synthetic identities and text only—no raw
live DOM, authentication state, trace, or account data.

The Company fixtures under `tests/fixtures/linkedin/companies/latest/` are
`mock_verified` from the authenticated visible UI inspected on 2026-08-05.
They preserve the current side-panel filter mechanics, all five filter
families, all eight size choices, exact location/industry typeaheads, submitted
query parameters, result identity and pagination, compact counts and social
proof, the smallest exact company introduction region, and the fixed
Overview-plus-About read. Exact About-page associated-member counts remain
separate from company-size and compact top-card employee counts. They contain
synthetic identities and text only.

The sanitized `person-profile-self-current.html` fixture is `mock_verified`
from the authenticated self-profile UI inspected on 2026-08-05. It preserves
the nested introduction section, self-verification link, auxiliary guidance
detail link, separator-only location line, and semantic company/school button
icons using synthetic identity and profile text only.

The sanitized current member-detail fixtures were reverified on 2026-08-05.
They preserve experience cards where LinkedIn exposes a standalone employment
type but no visible company name or location, exact skill cards anchored by
their accessible `Endorse <skill>` control, and About-section expansion and
`Top skills` UI suffixes. They also preserve the current roleless detail-page
collection boundary used by licenses, honors, languages, and other generic
member-owned sections, while keeping recommendation rails outside the member
result. Legacy combined organization/employment and visible location cards
remain covered separately. No live identity or profile text is retained.

The Posts fixtures under `tests/fixtures/linkedin/posts/latest/` are
`mock_verified` from authenticated visible search and detail surfaces
inspected through 2026-08-05. Search variants preserve current compact author
headers, trailing-bullet edited ages, pointer-intercepted expansion controls,
numeric engagement buttons, content-card classification, virtualized prefix
inventory, dynamic card-text evidence, and cursor behavior. Detail variants
preserve current exact-menu identity, body expansion, typed
media/link/document/poll structures, engagement controls, and bounded
repost-original behavior. They contain no live post, author, raw DOM,
authentication state, trace, or account data.

The sanitized `personal-post-composer.html` fixture additionally preserves the
current visible `Post successful. View post` alert contract and a visible
publishing-rejection state observed on 2026-08-05; the synthetic fixture never
contains the live post or account identity.

The sanitized `personal-post-composer.html` and `post-engagement.html` fixtures
are also `mock_verified` from the
authenticated visible UI inspected through 2026-08-05. They preserve the
bounded composer loader, disabled Save and
Done controls for unchanged settings, all nine personal composer modes, nested
image/video/document/poll/celebration/event/hiring/expert controls, settings,
the current top-level comment photo/GIF controls, native UGC discussion aliases,
multiple sibling root threads whose visually indented read-only replies bind to
the nearest preceding root, `See previous replies`, and the six current post
reactions. Initial
discovery uploaded synthetic files into draft-only editors without invoking an
account-changing control.

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

`tests/verification_manifest.py` owns the explicit mapping for all 24 tools.
The manifest test fails when:

- the public tool registry and verification inventory differ;
- a named test file is missing;
- a write tool lacks page, action, runtime, and workflow ownership;
- a search-filter model gains an unaccounted field;
- a member-profile selector, Company-search filter, or reaction enum changes silently; or
- a generic browser, click, JavaScript, network, navigation, queue, or pacing
  control appears in the public MCP schema.

All seven direct action tools share a compact conformance suite that verifies
one atomic call, one typed terminal result, and immutable action evidence.

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

When current-UI validation is needed, use a trusted MCP client with the minimum
required tools enabled and an explicit approval policy. Convert
only the sanitized behavior into offline fixtures; never retain live identities,
content, raw DOM, traces, cookies, or browser state. Fixture manifests record
only sanitized provenance and the UI behaviors represented by each fixture.

### Aggregate live-acceptance ledger

- 2026-08-05: Jobs search returned two disjoint five-result cursor pages and a
  five-result query combining recency, sort, workplace, experience, employment,
  and Easy Apply filters. Exact-detail readback returned a fully expanded JD,
  application method, metadata, and one current composite hiring-team profile
  card with separately typed name, degree, headline, and role. No account state
  changed.

- 2026-08-05: before the threaded-reply and comment-reaction mutation contracts
  were removed, the authorized Test Bot published one bounded validation post,
  added one root comment and three exact threaded replies, set and read back a
  post reaction, and set and read back `Celebrate` on the root comment. No
  duplicate post or blind action retry was performed.

- 2026-08-05: account-changing threaded comment replies were removed from the
  public schema. Offline contract tests reject the former
  `parent_comment_ref` input, while discussion fixtures continue to verify
  read-only reply ancestry and expansion.

- 2026-08-05: comment-targeted reaction changes were removed from the public
  schema. Offline contract tests reject the former `comment_ref` reaction
  target while preserving read-only comment reaction-count observations.

- 2026-08-05: a full member-profile replay traversed one overview and seven
  discovered detail pages. It excluded the self-only guidance destination,
  returned the visible headline and location from the nearest introduction
  card, retained both semantic top-card organization summaries, and completed
  without truncation. The replay also exposed the current standalone
  employment-type experience layout, accessible skill-card identity, and
  About-section UI suffixes; sanitized fixture coverage now locks those
  behaviors. Current roleless licenses, honors, and languages cards were then
  verified against their bounded semantic collection container, while
  recommendation rails remained outside the member result. No account state
  changed.

- 2026-08-05: People search resolved an exact first-degree member with current
  company criteria. Company search combined size, hiring, and network filters,
  while exact company readback returned the fixed Overview-plus-About contract.
  Connections inventory produced two disjoint recently-added cursor pages, and
  exact connection search enforced first degree. No account state changed.

- 2026-08-05: received and sent invitation inventories returned bounded typed
  pages with continuation state. One exact received invitation was accepted,
  another was ignored, and one alternate outbound target received a noted
  invitation from the authorized Test Bot account. Every action result was
  verified against its exact visible LinkedIn postcondition; no action was
  blindly retried.

- 2026-08-05: Posts search returned two disjoint three-result cursor pages from
  a cumulative live rescan. Current cards retained exact author headline and
  relationship degree, simple and edited trailing-bullet ages, fully expanded
  text, numeric reaction/comment/repost counts, and article/job/text content
  types without misclassifying author avatars. Exact Post detail readback
  independently matched one result's stable identity, full text, attachment,
  engagement, and evidence. No account state changed.

- 2026-08-05: both current comment sort orders returned two root threads with
  every visually indented reply attached to its nearest preceding root. The
  current actor-description card's `Author` badge remained UI metadata while
  the following visible line was retained as the comment author's headline.
  No account state changed during these read-only replays.

- 2026-08-05: exact-profile conversation lookup opened the authorized Test Bot
  one-to-one surface. One uniquely marked message was sent from
  the configured member account, execution verified the newly visible outgoing
  bubble, and independent conversation readback returned exactly that message.
  Searching its unique content then returned the Test Bot conversation. No
  duplicate send or blind retry was performed.

- 2026-08-04: a non-publishing personal-composer replay observed a bounded
  loading dialog, restored the exact personal composer, traversed unchanged
  audience/comment settings through their enabled Back controls, and did not
  invoke Post. A one-page read-only Posts search returned six typed cards; all
  six exact card snapshots reconciled with the immutable captured source.

## Test groups

| Group | Responsibility |
| --- | --- |
| `tests/unit/` | Models, URLs, registry, client identity, fair queue, repository, pacing, cursor state, cancellation, browser lifecycle, page objects |
| `tests/contract/` | MCP discovery, schemas, annotations, evidence, write conformance, stateful sessions, stdio proxying, shared-runtime election, and transports |
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

The enforced whole-repository branch floor is 85%. Dynamic LinkedIn layout
adapters retain lower numeric coverage than core orchestration because the
suite prioritizes meaningful semantic variants over invoking unreachable
defensive branches solely to increase a percentage.

## Maintenance rule

A new tool is not `mock_verified` until it has:

1. a manifest entry;
2. strict schema and registry tests;
3. synthetic page fixtures or an explicit non-browser operational boundary;
4. normal, empty, malformed, ambiguous, and bounded cases;
5. evidence assertions for reads;
6. the shared safety suite for writes;
7. an MCP round trip; and
8. a workflow case when it composes with other capabilities.

Future sanitized recordings should add variants alongside synthetic fixtures.
They should improve DOM realism without replacing deterministic negative and
fault-injection scenarios.
