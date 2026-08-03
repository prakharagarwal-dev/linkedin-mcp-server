# Collection Verification Process

This is the required acceptance process for every asynchronously rendered
LinkedIn search, list, feed, inbox, comment thread, invitation collection, or
other multi-item capability in this repository.

Its purpose is to prove completeness and honest truncation independently of
the implementation's own assumptions. A collector is not complete merely
because it stopped without an exception.

## Core invariant

For a fully traversed visible collection:

```text
advertised selected inventory
  = rendered selected cards
  = typed unique results + explicitly classified unsupported cards
```

For a server-defined union of overlapping visible views:

```text
sum(per-view advertised counts)
  = view memberships
  = unique stable results + repeated memberships
```

Every constituent view must first satisfy the single-view invariant. A union
cannot infer completeness from one preferred view.

This invariant applies to the selected collection only. Appended
recommendations, advertisements, navigation cards, and other neighboring
collections must be counted and reported separately.

A capability that claims every visible entity type, such as
`linkedin.invitations.list` `4.0.0`, cannot use “unsupported card” as a normal
escape hatch: every valid invitation must become a typed result, including a
loss-preserving `other` result for a newly introduced surface.

During cursor pagination, individual pages need not equal the full inventory.
The invariant applies to the cumulative terminal scan. Earlier pages must
retain disjoint stable identities, and terminal metadata may claim completion
only after a fresh bounded traversal reconciles the selected inventory.

When LinkedIn exposes no unambiguous inventory, completion requires independent
terminal evidence. The absence of a count must never be replaced with a guessed
count.

## Phase 1: Observe the complete live surface

Before designing or changing a collector:

1. Use the saved authenticated profile, official Playwright, and visible
   LinkedIn UI only.
2. Traverse to the actual tail with a read-only, bounded diagnostic.
3. Identify the real scroll container. Do not assume document scrolling.
4. Record aggregate, non-personal facts:
   - selected filter and its advertised count;
   - raw candidate count before normalization;
   - normalized selected-card count;
   - typed-card count;
   - rejected-card counts grouped by reason;
   - neighboring-card counts grouped by category;
   - loader, busy-state, tail-control, and end-copy behavior;
   - scroll geometry and progress rounds; and
   - whether the surface appends or virtualizes cards.
5. Inspect empty, small, multi-batch, filtered, and terminal states when they
   can be reached safely at low volume.

Do not retain names, profile URLs, card text, screenshots, DOM snapshots,
traces, cookies, storage state, credentials, or other personal account data in
the repository. A temporary trace may be used for diagnosis only when needed
and must not become a fixture.

## Phase 2: Define the collection contract

Document these facts before declaring the implementation done:

- What exact visible label, if any, describes the selected inventory?
- What exact current card-root selector belongs to that direction and layout?
- Which visible action or semantic marker identifies a selected card?
- Which neighboring card categories must be excluded?
- What creates a stable typed identity?
- Which cards are valid but cannot satisfy the typed contract?
- What proves progress independently of successful parsing?
- What proves completion?
- What private traversal and raw-DOM bounds apply?
- What output and stop reason are returned when proof is unavailable?

Count labels must bind to the active direction and filter. For example,
received `Focused (N)` cannot be compared with sent `People (N)`, and neither
can be compared with appended `Connect` recommendations. If the current UI
has no All control, an `all` result must be an explicitly defined union of
individually reconciled views, not a guessed total.

## Phase 3: Implement fail-closed collection mechanics

The collector must:

1. Use the exact, currently observed card-root selector when the surface
   provides one. Do not replace it with action-ancestor walking or a legacy
   selector union.
2. Only on surfaces without an exact card root, normalize observed wrappers
   and duplicate ancestor/descendant candidates before applying any limit.
3. Build progress signatures from raw visible identities before domain
   parsing, so parser rejection cannot hide DOM progress.
4. Deduplicate typed items by a stable domain identity.
5. Categorize every rendered selected card as typed or rejected with a
   specific reason during diagnosis.
6. Treat a polling timeout or loading pause as idleness, not completion.
7. Give newly observed progress precedence over simultaneous end copy.
8. Reject stable-bottom or explicit-end completion while a known selected
   inventory remains incomplete.
9. Exclude loaders, busy regions, and visible `Show more`/`Load more` controls
   from terminal evidence.
10. Return `safety_bound`, `truncated`, or a safe parser-drift error when
    completeness cannot be proven. Never return a false
    `visible_page_complete`.

Identity fallbacks must be target-specific and cross-checked. Arbitrary card
text is not an identity source. If a profile link is image-only, for example,
an accessible action target may supply the name only when it agrees with the
visible card identity and valid profile URL.

## Phase 4: Build independent offline fixtures

Synthetic fixtures must test the contract rather than reproduce only the happy
path expected by the implementation.

Every collection family should cover the applicable cases:

- empty collection;
- one small complete batch;
- multiple asynchronously appended batches;
- several complete idle windows before a later batch;
- explicit end copy before the final cards render;
- final progress and end copy in the same update;
- stable physical bottom with no end copy;
- visible loader or busy state at the tail;
- visible tail control;
- same-count virtualization or replacement;
- nested wrapper/card candidates exceeding the former or current raw bound;
- duplicated identities;
- malformed or unsupported selected cards;
- neighboring recommendation or advertisement cards;
- exact selected inventory that reconciles;
- advertised inventory that never reconciles;
- filter-specific inventory;
- valid edge-case identifiers; and
- identity mismatch that must fail closed.

Fixtures remain sanitized. A fixture may be marked `mock_verified` when its
structural contract was manually compared with the current visible UI and its
content remains synthetic. Its provenance must not claim a recorded DOM unless
an approved recorder actually produced and sanitized it.

## Phase 5: Verify every layer

Verification proceeds from narrowest to broadest:

1. Pure parsing and count-binding tests.
2. Real Playwright page-object tests against semantic fixtures.
3. Convergence, queue, pacing, cancellation, and safety-bound tests.
4. Executor tests for coverage, completion reasons, evidence, error mapping,
   and cumulative live traversal targets across cursor pages.
5. Official MCP client tests for schemas and structured output.
6. Cursor workflow tests proving disjoint identities, cumulative counts,
   filter binding, single-use cursors, terminal metadata, and honest
   truncation.
7. Semantic simulator workflows using production page objects.
8. The complete offline verification suite and package build.

Tests must assert expected inventory and rejection categories independently.
They must not use the collector's own output as the source of the expected
count.

## Phase 6: Perform low-volume live acceptance

Live acceptance is opt-in, read-only where possible, and never part of the
default pytest suite.

For a paginated collection, acceptance must:

1. Start through the official MCP transport, not only a page-object script.
2. Traverse every cursor page until terminal state or an honest safety bound.
3. Verify disjoint stable identities between pages.
4. Reconcile the terminal cumulative typed count plus classified unsupported
   count with the selected rendered inventory.
5. Confirm neighboring collections were excluded.
6. Record rounds, stop reason, cumulative count, `has_more`, and `truncated`.
7. Confirm authentication remains valid and the server is not paused.
8. Retain only aggregate evidence in a dated live-acceptance ledger.

A successful first page, a non-hanging cursor, or a clean terminal response is
not sufficient acceptance.

## Definition of done

A collection change may be called complete only when all of these are true:

- the complete live surface was inspected;
- selected and neighboring collections were classified;
- terminal reconciliation passes or truncation is reported honestly;
- raw candidate normalization occurs before private bounds;
- offline fixtures include the observed failure shape;
- page-object, executor, MCP, cursor, simulator, and complete-suite checks pass;
- a low-volume production-MCP replay passes when live acceptance is in scope;
- the capability matrix, changelog, and relevant durable documentation are updated;
  and
- no live personal data or authentication material was retained.

If any item is missing, describe the result as incomplete, blocked, or
mock-verified as appropriate. Do not call it fully fixed or live-accepted.

## Required static gates

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv build
```

Also run:

```bash
uv lock --check
git diff --check
```
