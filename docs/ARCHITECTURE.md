# Architecture

## Boundary

LinkedIn MCP Server is one local Python process. It exposes narrow, typed MCP
tools and drives only visible LinkedIn web surfaces through Playwright. It has
no agent, LLM, planner, database, task queue, worker pool, stdio bridge, or
generic browser-control tool.

```text
MCP client
    │ Streamable HTTP: POST/GET/DELETE /mcp
    ▼
FastMCP
    │ validates input and invokes the registered tool
    ▼
tool.py
    │ OperationManager.run(...) or run_write(...)
    ▼
one asyncio.Lock
    │ exactly one LinkedIn operation at a time
    ▼
tool-owned page.py ────────────── CursorManager
    │ Page/Locator reads              process-local continuation state
    │ UIManager paced actions
    ▼
BrowserManager
    │ one persistent Chromium context; one fresh page per call
    ▼
visible LinkedIn UI
```

FastMCP owns the ASGI application, Uvicorn server, MCP HTTP sessions, and event
loop. The server does not wrap or proxy that transport.

## Startup and shutdown

`linkedin-mcp serve` follows one path:

1. `CLIManager` parses the command and constructs `Settings`.
2. `linkedin_mcp.main.main()` creates `BrowserManager`, `UIManager`,
   `OperationManager`, `CursorManager`, `FastMCP`, and `ToolManager`.
3. `ToolManager` registers every typed tool with FastMCP.
4. FastMCP starts its Streamable HTTP server.
5. FastMCP's lifespan starts `BrowserManager` before accepting requests.
6. `BrowserManager` opens the persistent profile and validates authentication.
   If login is missing, it completes the visible login flow synchronously and
   validates the reopened profile.
7. On shutdown, the same lifespan closes Chromium and Playwright.

There is no separate host manager or background runtime. Keep one server
process per profile. Chromium's persistent profile must not be opened by a
second process at the same time.

## Request lifecycle

Every browser-backed call follows one direct flow:

1. FastMCP validates the public arguments with the tool's Pydantic models.
2. The registered function creates the tool's typed input.
3. `OperationManager` waits for its one process-local `asyncio.Lock`.
4. The tool calls its own page object.
5. The page object obtains a fresh `Page` from `UIManager`, reads visible UI,
   and uses paced methods such as `ui.click()` or `ui.fill()` for interactions.
6. The tool constructs immutable evidence and its typed output.
7. The lock is released and FastMCP serializes the response.

There is no `Task`, `Scheduler`, `Worker`, central dispatcher, capability
registry, or result repository. Waiting calls are simply coroutines waiting on
the lock.

### Reads

Reads execute freshly on every invocation. They return visible data with source
URLs, capture times, and coverage metadata. No result or evidence is cached.

Collection tools own their output and cursor assembly in leaf-local
`pagination.py` files. `CursorManager` retains only bounded stable identities
needed for an opaque continuation cursor. Cursors are process-local, expiring,
single-use, and bound to the account, tool, and semantic filters.

A continuation may revisit LinkedIn's visible prefix because the UI exposes no
snapshot token. Previously returned identities are filtered before selecting
the next page. Completion is reported only when the selected visible inventory
can be reconciled; otherwise the tool reports a safety bound, truncation, or
parser drift.

### Account-changing actions

Each write tool performs one complete action in one call:

1. inspect the exact visible target;
2. reject ambiguous, missing, or incompatible state;
3. invoke the final matching control at most once;
4. verify the visible postcondition; and
5. return `verified`, `failed`, or `uncertain`.

Once a write has acquired the operation lock and started, client cancellation
does not cancel the underlying action. `OperationManager.run_write()` lets it
reach a terminal outcome, releases the lock, and then propagates cancellation
to the disconnected caller. The server never retries a write automatically.

## Responsibilities

- `Settings` is the only configuration object and reads `LINKEDIN_MCP_*`
  environment variables.
- `CLIManager` owns command parsing and dispatch only.
- `ToolManager` constructs tool page objects and registers tools only.
- `OperationManager` serializes complete LinkedIn operations with one lock.
- `CursorManager` owns bounded in-memory continuation state only.
- `BrowserManager` owns Playwright, the persistent Chromium context,
  authentication, page creation/cleanup, access state, and shutdown.
- `UIManager` gives tools a page and exposes paced Playwright actions.
- `Pacer` applies the configured delay immediately before an interaction.

## Runtime state

Process-local state is limited to:

- the operation lock and its small status counters;
- pagination cursor identities; and
- browser authentication and access-pause state.

A restart clears that state. The Chromium profile is the only persistent
server-owned authentication state.

## Code layout

```text
linkedin_mcp/
├── main.py                  FastMCP composition and lifespan
├── config.py                Settings
├── errors.py                public error taxonomy
├── logging.py               structured logging setup
├── browser/                 Chromium lifecycle, profile, login/logout, access
├── ui/                      UIManager, Pacer, bounded UI-settling primitives
├── operations/manager.py    one-operation asyncio.Lock
├── cursors/manager.py       bounded continuation state
├── cli/
│   ├── manager.py           parser and dispatch
│   └── commands/            one module per command
└── tools/
    ├── manager.py           tool registration
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

A browser-backed tool leaf contains:

```text
tool.py          FastMCP registration and direct execution entrypoint
page.py          LinkedIn UI behavior for this tool
evidence.py      evidence construction for this tool
models.py        all contracts owned by this tool
pagination.py    output/cursor assembly, only for collections
```

Named family modules such as `posts/surface.py` contain visible-UI mechanics
shared only by neighboring tools. Identifier and URL parsing belongs to the
relevant tool family. There is no `tools/_shared`, `operation.py`, aggregate
model package, or generic capability executor.

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
