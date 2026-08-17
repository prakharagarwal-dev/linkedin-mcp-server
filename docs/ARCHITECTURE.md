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

On Windows, the first stdio bridge uses a short-lived local PowerShell CIM
launcher to ask `Win32_Process.Create` for the background runtime. Windows does
not associate that broker-created process with the bridge's Job Object, so the
single Python runtime survives individual MCP-client teardown. The launcher
passes the current process environment in memory, exits after the request, and
does not add another long-lived service or runtime.

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
7. The executor validates evidence and returns the typed result directly.
8. The temporary page closes; the browser context and login profile remain.

Calls are atomic at the MCP boundary. A client does not own a browser tab
between calls, and a cursor does not preserve a live page.

### Reads

Reads collect visible data, coverage metadata, source URLs, and capture times.
Every invocation executes the provider again. `request_id` is returned for
caller correlation; it does not cache, deduplicate, or lock the request arguments.

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

Write calls also execute once per invocation and are never retried by the
server. Clients should not blindly retry an `uncertain` result. MCP annotations mark these tools as destructive so the
client can apply its own approval policy; the server has no second approval or
permission database.

Local attachments are relative references under the configured asset root.
The server resolves the current file, rejects path escape, validates the
supported type and LinkedIn size limit, and passes the path to Playwright.

## Runtime state

The server has no call-result or evidence repository. Runtime coordination is
memory-only:

- queued and active calls;
- pagination cursors;
- queue ownership and progress; and
- navigation pacing.

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

`BrowserRuntime` owns one Playwright persistent context and creates a fresh
page lease for each serialized operation. `BrowserManager` layers LinkedIn
authentication, navigation pacing, and visible-UI safety checks over that
runtime. Navigation is restricted to configured LinkedIn hosts. The public MCP
surface never exposes URLs, selectors, arbitrary clicks, JavaScript, requests,
or browser pages.

The authentication coordinator pauses capability execution when the visible
session expires, LinkedIn shows a checkpoint or restriction, or browser setup
fails. Interactive login and logout use the same persistent profile through
the CLI.

## Code layout

Infrastructure is separated from the public LinkedIn capabilities. Inside
`tools/`, every public MCP name maps directly to one directory after removing
the `linkedin.` prefix:

```text
linkedin_mcp/
├── mcp/                     FastMCP composition, client context, and transports
├── app/                     queue, scheduling, pagination, assets, and composition
├── browser/                 Playwright installation, profile, and browser runtime
├── runtime/                 shared-process ownership and lifecycle
├── cli/                     CLI assembly and command hierarchy
└── tools/
    ├── _shared/             primitives genuinely reused across capabilities
    ├── server/status/       linkedin.server.status
    ├── session/status/      linkedin.session.status
    ├── jobs/
    │   ├── search/          linkedin.jobs.search
    │   └── get/             linkedin.jobs.get
    ├── people/{search,get}/
    ├── companies/{search,get}/
    ├── posts/
    │   ├── search/          linkedin.posts.search
    │   ├── get/             linkedin.posts.get
    │   ├── comments/list/   linkedin.posts.comments.list
    │   └── {create,comment,react}/
    ├── invitations/{list,send,accept,ignore}/
    ├── connections/{list,search}/
    └── messaging/
        ├── search/
        ├── conversation/get/
        └── send/
```

Every capability leaf contains a `models/` package with one owned type per
snake-case module. Browser-backed leaves additionally contain `tool.py`,
`operation.py`, `page.py`, and `evidence.py`. The tool module owns the FastMCP
definition; the operation owns application flow; the page module contains that
tool's concrete typed Playwright adapter; and models and evidence define that
capability's contract. Consumers import the exact model module rather than a
forwarding `models.py` facade. A model used by multiple tools is defined once
in the nearest domain `models/` package and imported by those leaves. Named
domain modules such as `posts/surface.py` or
`messaging/conversation_surface.py` contain only visible-UI mechanics that are
genuinely shared by multiple concrete page adapters. Domain `_shared/`
packages and forwarding-only page modules are not used. The global
`tools/_shared/` package remains the home of cross-domain primitives. There is
no second registry, broad operations facade, or aggregate model or page
implementation module.

For example, the full implementation boundary for `linkedin.jobs.search` is
`tools/jobs/search/`. `mcp/server.py` only creates FastMCP and attaches leaf
tools, while `app/executor.py` only composes leaf operations for the worker.
Generic Chromium lifecycle code remains under `browser/`.

## Adding a capability

A new capability gets a directory matching its public MCP name and needs:

1. strict input and output models;
2. a narrow provider/page-object contract;
3. a leaf-owned operation and worker wiring;
4. a leaf-owned FastMCP definition with accurate annotations;
5. synthetic current-UI fixtures and failure variants;
6. evidence and bounded-completeness behavior; and
7. contract, page, runtime, and workflow tests as applicable.

Collection tools must also follow
[COLLECTION_VERIFICATION_PROCESS.md](COLLECTION_VERIFICATION_PROCESS.md).
