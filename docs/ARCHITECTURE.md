# Architecture

## Boundary

LinkedIn MCP Server is a local Python MCP server. It exposes narrow, typed
LinkedIn tools and drives only visible LinkedIn web surfaces with Playwright.
It does not contain an agent, LLM, planner, scheduler, database, external
queue, or generic browser-control API.

```text
MCP clients
    │ stdio bridges or loopback Streamable HTTP
    ▼
shared local MCP runtime
    │ typed validation and client identity
    ▼
fair in-process scheduler
    │ one complete browser operation at a time
    ▼
Playwright page object ── visible UI ── LinkedIn
    │
    └── persistent Chromium profile (authentication only)
```

One background runtime owns the configured Chromium profile. Stdio clients
start or attach to that runtime through a loopback MCP endpoint. Direct
Streamable HTTP clients can use the same loopback endpoint. The account lock
prevents profile corruption by a second owner. It uses native advisory file
locking on POSIX and Windows; graceful stop requests are instance-bound local
files, so runtime lifecycle does not depend on POSIX process signals.

The loopback endpoint uses stateful Streamable HTTP with JSON responses. It
does not expose the optional standalone GET event stream because the server has
no unsolicited server-to-client messages; clients receive `405 Method Not
Allowed` for that optional channel and continue using POST and DELETE. This
also keeps repeated Windows client teardown bounded in the official SDK.

## Request lifecycle

Every tool call is one bounded operation:

1. FastMCP validates the public input schema.
2. The server binds the call to the current MCP client.
3. The worker places it in the bounded fair scheduler.
4. The scheduler applies global navigation pacing.
5. The executor opens a temporary Playwright page in the shared browser
   context.
6. A capability-specific page object navigates and uses visible controls.
7. The executor stores process-local evidence and returns a typed result.
8. The temporary page closes; the browser context and login profile remain.

Calls are atomic at the MCP boundary. A client does not own a browser tab
between calls, and a cursor does not preserve a live page.

### Reads

Reads collect visible data, coverage metadata, source URLs, and capture times.
The process-local repository can replay a completed read when the same MCP
client repeats the same `request_id` and arguments. Reusing a request ID with
different arguments fails closed.

Collections return one page plus an opaque cursor. Cursors are:

- process-local and expiring;
- bound to the client, account, capability, and semantic filters;
- single-use; and
- backed by a bounded set of identities already returned.

A continuation may revisit LinkedIn's visible prefix because the UI exposes no
snapshot token. Previously returned identities are removed before the next
page is selected. Completion is reported only when the collection-specific
inventory can be reconciled; otherwise the result exposes a safety bound or
truncation.

### Account-changing actions

Each write tool performs one complete action in one call:

1. validate the typed request;
2. resolve and inspect the exact visible target;
3. reject ambiguous, missing, or incompatible state;
4. invoke the one matching visible action;
5. verify a visible postcondition; and
6. return `verified`, `failed`, or `uncertain`.

Write calls are never replayed or coalesced. Clients should not blindly retry
an `uncertain` result. MCP annotations mark these tools as destructive so the
client can apply its own approval policy; the server has no second approval or
permission database.

Local attachments are relative references under the configured asset root.
The server resolves the current file, rejects path escape, validates the
supported type and LinkedIn size limit, and passes the path to Playwright.

## Runtime state

All application state is memory-only:

- active and completed read calls;
- evidence resources;
- pagination cursors;
- queue ownership and progress; and
- terminal action observations.

Restarting the shared runtime clears that state. The Chromium profile is the
only persistent server-owned state and contains LinkedIn authentication data.
It must be treated as sensitive.

## Scheduling and pacing

The runtime has one bounded `asyncio` scheduler and one browser worker. Calls
from the same client remain FIFO. Ready clients rotate fairly, so one client
cannot enqueue an entire pagination scan ahead of every other client.

Only one browser operation runs at a time. A global minimum navigation
interval is enforced across all clients and all tools. Delays inside a page
object are bounded waits for visible UI convergence, not public pacing
controls.

## Browser safety

`BrowserManager` owns one Playwright persistent context and creates a fresh
page for each operation. Navigation is restricted to configured LinkedIn
hosts. The public MCP surface never exposes URLs, selectors, arbitrary clicks,
JavaScript, requests, or browser pages.

The authentication coordinator pauses capability execution when the visible
session expires, LinkedIn shows a checkpoint or restriction, or browser setup
fails. Interactive login and logout use the same persistent profile through
the CLI.

## Code layout

| Layer | Responsibility |
| --- | --- |
| `server.py` | FastMCP tools, resources, annotations, and client binding |
| `domain/` | Strict Pydantic inputs, outputs, identifiers, and evidence |
| `capabilities/` | Registry of supported typed operations |
| `application/` | Worker, executor, scheduler, cursors, runtime election, and in-memory state |
| `browser/` | Chromium lifecycle, authentication, pacing, host guard, and page objects |
| `policy/` | Canonical LinkedIn URL and stable-reference parsing |
| `persistence/` | Process-local repository contracts and implementation |

Transport wiring, domain contracts, orchestration, browser mechanics, and page
extraction remain separate so a UI change does not leak into the MCP protocol.

## Adding a capability

A new capability needs:

1. strict input and output models;
2. a registry descriptor;
3. a narrow provider/page-object contract;
4. executor and worker wiring;
5. one MCP tool with accurate annotations;
6. synthetic current-UI fixtures and failure variants;
7. evidence and bounded-completeness behavior; and
8. contract, page, runtime, and workflow tests as applicable.

Collection tools must also follow
[COLLECTION_VERIFICATION_PROCESS.md](COLLECTION_VERIFICATION_PROCESS.md).
