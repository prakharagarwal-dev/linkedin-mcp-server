# Testing

The default suite is completely offline. It never signs in to LinkedIn,
contacts LinkedIn, or changes a real account.

Every public tool is `mock_verified`, which means its current contract is
covered through strict schemas, production orchestration, synthetic visible-UI
fixtures, official MCP protocol calls, and relevant workflow tests. It does
not mean the current LinkedIn site was contacted during CI.

## Test layers

| Layer | What it verifies |
| --- | --- |
| `tests/unit/` | Models, identifiers, configuration, browser lifecycle, host restrictions, pacing, scheduler fairness, cursors, executor behavior, and Playwright page objects |
| `tests/contract/` | Tool discovery, schemas, annotations, fresh execution, stdio/HTTP behavior, shared-runtime attachment, client isolation, and direct action conformance |
| `tests/simulator/` | Stateful LinkedIn-like data, synthetic HTML routing, controlled failures, and mutations |
| `tests/workflows/` | Multi-tool job, referral, connection, messaging, publishing, and engagement journeys |
| `tests/package/` | Wheel contents, CLI entry point, forbidden dependencies, and secret/profile exclusion |

The protocol simulator and HTML page-object fixtures are independent:

```text
official MCP client                 Playwright Chromium
        │                                   │
production FastMCP tools             production page objects
        │                                   │
worker / executor                    synthetic LinkedIn HTML
        │                                   │
stateful typed providers             accessible DOM assertions
```

This prevents a single mock implementation from both producing and validating
the same behavior.

## Fixtures

Fixtures live in domain-specific `latest` directories under
`tests/fixtures/linkedin/`. They contain synthetic identities and content while
preserving only the visible structure needed by a current parser behavior.
Each domain manifest records provenance and the UI behaviors represented.

Never commit:

- browser profiles, cookies, storage state, credentials, or tokens;
- raw authenticated DOM, screenshots, traces, or HAR files;
- private messages or real member/account content; or
- local paths or machine-specific state.

Fixtures include success, empty, delayed-render, virtualization, ambiguity,
parser-drift, explicit-end, safety-bound, and terminal-action variants where
those cases apply.

## Collection verification

Every asynchronous search, list, feed, inbox, discussion, or invitation tool
must follow
[COLLECTION_VERIFICATION_PROCESS.md](COLLECTION_VERIFICATION_PROCESS.md).
Stopping cleanly is not sufficient evidence of completeness. Tests must cover
stable identity deduplication, delayed progress, explicit terminal evidence,
reconciliation, truncation, and cursor behavior.

## Contract ownership

`tests/verification_manifest.py` maps every public tool to its required test
files. `tests/contract/test_mock_verification_manifest.py` fails when:

- the tool registry and verification inventory differ;
- a required test file is missing;
- a write tool lacks page, action, runtime, or workflow ownership;
- a filter or enum changes without explicit fixture coverage; or
- a generic browser-control primitive appears in the MCP schema.

All action tools share conformance checks for one atomic invocation, exact
typed terminal outcomes, visible postcondition evidence, interruption, and
uncertainty. Attachment cases validate the current path, file type, size, and
direct Playwright upload behavior.

## Network isolation

`tests/conftest.py` rejects non-loopback Python socket connections. Loopback
and Unix sockets remain available for Playwright and local MCP transport tests.
The semantic browser aborts any document route not registered by its scenario.

## Run the suite

During development, run the smallest affected test module or test selection.
The default Pytest configuration uses four work-stealing workers; pass `-n 0`
when serial execution is useful for debugging. Before merging, run the complete
gate once:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest --cov=linkedin_mcp --cov-branch --cov-report=term-missing
uv build
```

CI runs formatting, linting, type checking, packaging, and the full offline
suite on Python 3.12, 3.13, and 3.14 for every pull request. Native platform
jobs also run the full suite on macOS, Windows, and Linux ARM64; the primary
Linux x86-64 jobs remain the version matrix and coverage gate.

## Adding or changing a tool

A changed capability is not complete until it has:

1. strict input and output contract coverage;
2. current synthetic fixtures and manifest updates;
3. positive, empty, malformed, ambiguous, and bounded cases as applicable;
4. evidence assertions for reads or visible postcondition assertions for
   actions;
5. an official MCP round trip; and
6. a workflow case when the tool composes with other capabilities.
