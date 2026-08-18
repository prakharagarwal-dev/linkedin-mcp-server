# Architecture

## Boundary

LinkedIn MCP Server is a local Python MCP server. It exposes narrow, typed
LinkedIn tools and drives only visible LinkedIn web surfaces with Playwright.
It does not contain an agent, LLM, planner, database, external queue, or
generic browser-control API.

```text
MCP client
    │ stdio bridge or loopback Streamable HTTP
    ▼
FastMCP tool
    │ creates Task
    ▼
Scheduler ── asyncio.Queue ──> Worker
                                  │ calls the tool's execute function
                                  ▼
                         tool page object
                                  │ visible UI
                                  ▼
                              LinkedIn
```

One background runtime owns the configured Chromium profile. Stdio clients
start or attach to that runtime through a loopback MCP endpoint. Direct
Streamable HTTP clients use the same endpoint. The account lock prevents a
second process from owning the profile at the same time.

The loopback endpoint uses stateful Streamable HTTP with JSON responses. It
does not expose the optional standalone GET event stream because the server has
no unsolicited server-to-client messages. On Windows, a short-lived local CIM
launcher starts the background runtime so it can survive individual stdio
client teardown.

## Request lifecycle

Every browser-backed tool call follows one short path:

1. FastMCP validates the public arguments.
2. `tool.py` builds the tool's typed input model.
3. `tool.py` creates a `Task` around that tool's execution function.
4. `Scheduler` puts the task in its bounded FIFO `asyncio.Queue`.
5. `Scheduler` gives the next task to the one `Worker`.
6. The tool's code calls its page object and builds evidence and output.
7. The task's future resolves and FastMCP returns the typed result.

There is no capability registry, central dispatcher, executor, or operation
class between the worker and the tool. `Task` carries only a name, an async
callable, its result future, and cancellation behavior.

Only one browser task runs at a time. This protects the one browser context and
makes account-changing actions atomic at the MCP boundary. A client never owns
a browser tab between calls.

### Reads

Reads collect current visible data, coverage metadata, source URLs, and capture
times. Every invocation executes again; `request_id` is correlation data and
does not cache or deduplicate a call.

Collection tools keep their output and cursor assembly in a leaf-local
`pagination.py`. Opaque cursors are process-local, expiring, single-use, and
bound to the client, account, tool, and semantic filters. The cursor stores
only the stable identities already returned. A failed collection does not
consume its input cursor; a successful one does.

A continuation may revisit LinkedIn's visible prefix because the UI exposes no
snapshot token. Previously returned identities are filtered before the next
page is selected. Completion is reported only when the selected visible
inventory can be reconciled; otherwise the output reports a safety bound or
truncation.

### Account-changing actions

Each write tool performs one complete action in one call:

1. inspect the exact visible target;
2. reject ambiguous, missing, or incompatible state;
3. invoke the final matching control at most once;
4. verify the visible postcondition; and
5. return `verified`, `failed`, or `uncertain`.

Write tasks are non-interruptible after the worker starts them. If their MCP
caller disconnects, the worker still lets the started action reach a terminal
outcome. The server never retries a write automatically. The small shared
`tools/action.py` helper builds the command, outcome, and evidence; it does not
select or dispatch tools.

## Runtime state

The server has no result or evidence repository. Process-local state is limited
to:

- queued and active tasks;
- pagination cursors; and
- navigation pacing.

Restarting clears that state. The Chromium profile is the only persistent
server-owned state and contains LinkedIn authentication data.

## Browser safety

`BrowserRuntime` owns one Playwright persistent context and creates a fresh
page for each serialized task. `BrowserManager` adds authentication,
navigation pacing, and visible-UI safety checks. Navigation is limited to the
configured LinkedIn hosts. Public tools never expose URLs, selectors, arbitrary
clicks, JavaScript, requests, or browser pages.

Authentication expiry, checkpoints, restriction pages, and configuration
failures pause LinkedIn access. Login and logout use the same persistent
profile through the CLI.

## Code layout

```text
linkedin_mcp/
├── execution/               Task, Scheduler, Worker
├── browser/                 Playwright setup, profile, low-level runtime
├── transport/               FastMCP, stdio bridge, shared host and lock
├── cli/                     CLI assembly and commands
├── container.py             process-wide dependency composition
├── pagination.py            bounded process-local cursor state
├── assets.py                safe local attachment resolution
└── tools/
    ├── action.py            shared single-attempt write helper
    ├── _shared/             cross-tool contracts and UI helpers
    ├── server/status/
    ├── session/status/
    ├── jobs/{search,get}/
    ├── people/{search,get}/
    ├── companies/{search,get}/
    ├── posts/{search,get,create,comment,react}/
    ├── posts/comments/list/
    ├── invitations/{list,send,accept,ignore}/
    ├── connections/{list,search}/
    └── messaging/{search,send}/ and messaging/conversation/get/
```

Every public MCP name maps directly to a tool leaf after removing the
`linkedin.` prefix. A browser-backed leaf contains:

```text
tool.py          FastMCP registration, typed request, Task creation
page.py          Playwright behavior for this tool
evidence.py      evidence construction for this tool
models/          one owned model per file
pagination.py    collection/output assembly, only when the tool paginates
```

Named domain modules such as `posts/surface.py` contain visible-UI mechanics
that are genuinely shared by neighboring page objects. `tools/_shared/`
contains only cross-domain contracts and helpers. There is no `operation.py`,
capability registry, aggregate model facade, or central capability executor.

## Adding a capability

A new capability gets a directory matching its public MCP name and needs:

1. strict input and output models;
2. `tool.py`, `page.py`, and `evidence.py`;
3. `pagination.py` only for a collection;
4. accurate MCP annotations;
5. bounded visible-UI behavior and synthetic fixtures; and
6. contract, page, execution, and workflow tests as applicable.

Collection tools must also follow
[COLLECTION_VERIFICATION_PROCESS.md](COLLECTION_VERIFICATION_PROCESS.md).
