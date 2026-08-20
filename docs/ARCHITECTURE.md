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
                                  │ raw reads; paced actions
                                  ▼
                     BrowserManager + Paced
                                  │ visible Playwright UI
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
bound to the account, tool, and semantic filters. The cursor store retains
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
outcome. The server never retries a write automatically. Each write leaf owns
its input, command, inspection, outcome, evidence, and execution flow in its
local `models.py`, `evidence.py`, and `tool.py`; there is no shared action
executor.

## Runtime state

The server has no result or evidence repository. Process-local state is limited
to:

- queued and active tasks;
- pagination cursors; and
- browser authentication and access-pause state.

Restarting clears that state. The Chromium profile is the only persistent
server-owned state and contains LinkedIn authentication data.

## Browser safety

`BrowserManager` owns Playwright, the worker's one persistent Chromium context,
fresh task-page creation and popup cleanup, visible login/logout, access-state
checks, and clean shutdown. On startup it synchronously validates the saved
session. If authentication is required, it closes the context, waits for visible
headed login, reopens the configured context, and validates it again.
`HostManager` does not start the queue or publish the endpoint until this
finishes.

`Paced` is a small action wrapper in `infra/playwright/pacer.py`. The host creates
it once with the configured fixed delay and supplies it through
`BrowserManager`. Tool page objects use official Playwright `Page` and `Locator`
objects directly for reads and locator construction, then invoke mutations as
`self._paced.click(locator)`, `self._paced.fill(locator, value)`, or another
specific paced action. `Paced` has no lock, background task, safety policy, or
global state. The one queue worker serializes all tool browser operations, so
there is no second browser lock.

Authentication expiry, checkpoints, restriction pages, and configuration
failures pause an already running facade or fail startup. Navigation is limited
to configured LinkedIn hosts. Public tools never expose URLs, selectors,
arbitrary clicks, JavaScript, requests, or browser pages.

## Code layout

```text
linkedin_mcp/
├── __main__.py              public CLI/private-host process dispatch
├── browser/                 Chromium pages/context, access, URLs, login/logout
├── transport/               FastMCP HTTP server and stdio bridge
├── host/                    HostManager and account process lock
├── infra/
│   ├── queue/               Task, Scheduler, Worker
│   ├── cursor/store.py      bounded process-local cursor state
│   └── playwright/          Paced actions and collection settling
├── cli/                     CLI assembly and commands
└── tools/
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

`HostManager` is the process composition root. It handles stdio attachment or
Streamable HTTP ownership, acquires the account lock, starts and authenticates
the browser with its `Paced` dependency, constructs the scheduler/cursor/MCP
tools, starts the scheduler, and only then binds and publishes the endpoint. It
closes those components in reverse order. There is no dependency container,
service locator, browser runtime wrapper, or module-global runtime singleton.

Every public MCP name maps directly to a tool leaf after removing the
`linkedin.` prefix. A browser-backed leaf contains:

```text
tool.py          FastMCP registration, typed request, Task creation
page.py          Playwright behavior for this tool
evidence.py      evidence construction for this tool
models.py        all contracts owned by this tool
pagination.py    collection/output assembly, only when the tool paginates
```

Named domain modules such as `posts/surface.py` contain visible-UI mechanics
that are genuinely shared by neighboring page objects. Generic pacing and
collection-settling mechanics live in `infra/playwright/`. Browser lifecycle,
access checks, and URL validation live in `browser/`. Tool contracts, evidence construction, annotations,
safe MCP error projection, and single-attempt write execution stay in the leaf
that exposes them. There is no `tools/_shared/`, `tools/action.py`,
`operation.py`, capability registry, aggregate model facade, or central
capability executor.

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
