# Low-Level Design

This is the implemented design. It deliberately keeps the task queue generic
and puts LinkedIn behavior inside the tool that owns it.

## Core classes

```text
┌──────────────────────────────────────────────────────────────────┐
│ HostManager                                                      │
│                                                                  │
│ transport: attach stdio or own Streamable HTTP                   │
│ startup: lock -> browser/login -> queue/tools -> listener       │
│ shutdown: exact reverse order                                    │
└──────────────┬───────────────────────────────────────────────────┘
               │ supplies each tool only its concrete dependencies
               ▼
┌────────────────────┐       creates       ┌──────────────────────┐
│ FastMCP tool       │ ──────────────────> │ Task[Result]         │
│                    │                     │                      │
│ validates arguments│                     │ name                 │
│ builds typed input │                     │ execute() callable   │
│ awaits task.result │                     │ result Future        │
└────────────────────┘                     │ interruptible flag   │
                                           └──────────┬───────────┘
                                                      │ enqueue
                                                      ▼
┌──────────────────────────────────────────────────────────────────┐
│ Scheduler                                                        │
│                                                                  │
│ bounded FIFO asyncio.Queue[Task]                                 │
│ start()   schedule(task)   quiesce()   close()                   │
└──────────────────────────────┬───────────────────────────────────┘
                               │ gives one task at a time
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│ Worker                                                           │
│                                                                  │
│ active_task                                                      │
│ execute(task)   cancel_active()   wait_until_idle()              │
└──────────────────────────────┬───────────────────────────────────┘
                               │ calls Task.run()
                               ▼
                    tool-owned execute function
```

Responsibilities are intentionally narrow:

- `Task` carries one callable and one future. It knows nothing about LinkedIn
  capabilities or request model unions.
- `Scheduler` owns queue admission and FIFO ordering. It does not dispatch by
  capability name.
- `Worker` runs the task it receives. It has no tool methods.
- `CursorStore` holds bounded, expiring, single-use continuation state for all
  collection tools in the process. It knows only strings, bindings, and stable
  item identities; it imports no tool contracts.
- `HostManager` is the composition root, not a dependency container used by
  tools. It owns process election, transport choice, startup, and shutdown;
  tool registration captures explicit component references once.
- `Worker` is the only component that executes tool browser work. The host uses
  the browser only during awaited startup authentication and after worker
  shutdown, so browser access needs no additional operation lock.

## Browser and Playwright classes

```text
HostManager
    │ creates and supplies
    ├──────────────────────────────┐
    ▼                              ▼
BrowserManager                  Paced
    │                              │ fixed sleep before actions
    │ owns                         │ click / fill / press / goto / ...
    ▼
official Playwright ──> persistent BrowserContext
                              │ BrowserManager.page()
                              ▼
                         raw Page / Locator
                              ▲
                              │ reads directly; actions through Paced
                         tool page object
```

- `BrowserManager` owns Chromium installation readiness, the persistent
  context, saved-session validation, visible login/logout, task-page creation,
  popup cleanup, access-pause state, and browser close.
- `Paced` owns one fixed delay value and thin wrappers around specific official
  Playwright mutations. It has no lock, singleton, background task, or browser
  safety responsibility.
- Tool page objects ask `BrowserManager.page()` for a raw task-scoped `Page`.
  They read and construct locators directly, and perform mutations through the
  manager-supplied `Paced`, for example `await self._paced.fill(locator, value)`.
- Tools never create or close a persistent browser context.

## Startup and transport sequence

```text
stdio client                         Streamable HTTP client
     │ starts CLI                              │ connects directly
     ▼                                         │
HostManager.ensure_host()                      │
     │ attach to healthy owner, or             │
     │ spawn `python -m linkedin_mcp`          │
     │ with the private-host marker            │
     ▼                                         │
                 elected HostManager <─────────┘
                         │ acquire account lock
                         │ BrowserManager.start()
                         │   validate saved session
                         │   await visible login when required
                         │   reopen and revalidate
                         │ create BrowserManager(Paced(...))
                         │ create CursorStore, Scheduler, FastMCP/tools
                         │ start Scheduler
                         │ bind and publish loopback endpoint
                         ▼
                  ready Streamable HTTP host
                         ▲
                         │ MCP forwarding
                  per-client stdio bridge
```

Both launch methods reach the same host, browser context, queue, and worker.
The stdio bridge is only a transport adapter; disconnecting it does not close
the shared host. `HostManager.close()` closes the listener, quiesces and closes
the scheduler, closes cursor state and Chromium through `BrowserManager`, then
releases the account lock.

Read tasks are interruptible. Write tasks set `interruptible=False`, so a
caller cancellation cannot stop an action after its final LinkedIn control may
have been invoked.

## Tool slice

Job search is representative of a collection tool:

```text
tools/jobs/search/
├── tool.py          MCP adapter and Task creation
├── pagination.py    execute(), cursor selection, output assembly
├── page.py          visible LinkedIn search and extraction
├── evidence.py      immutable source construction
└── models.py         input, output, filters, coverage, summaries
```

```text
MCP call
   │
   ▼
tool.py
   ├── builds JobSearchInput
   ├── creates Task(execute=pagination.execute(...))
   └── schedules and awaits it
                    │
                    ▼
pagination.py
   ├── starts state in infra/cursor/store.py
   ├── calls page.collect(...)
   ├── selects unseen results
   ├── calls evidence builder
   ├── commits state in infra/cursor/store.py
   └── returns JobSearchOutput
                    │
                    ▼
page.py ──> BrowserManager.page() ──> raw official Page/Locator
    │
    └────> Paced ──> selected Playwright actions
```

A non-paginated read keeps its small `execute(...)` function directly in
`tool.py`. A write tool also keeps its complete single-attempt execution flow
in `tool.py`:

```text
tools/invitations/send/tool.py
   │
   ├── creates InvitationSendInput
   ├── creates non-interruptible Task
   └── execute(request, page)
           │
           ├── inspect -> local command -> perform once -> local evidence
           └── page.py: exact visible controls and postcondition
```

Its request, action, result, and evidence contracts are all in the same leaf's
`models.py`; it does not import a global tool contract. There is no
`tools/_shared`, shared action executor, `Operation`, `CapabilityExecutor`,
provider protocol hierarchy, or capability switch statement.

## Read sequence

```text
MCP Client
    │ linkedin.jobs.search(arguments)
    ▼
FastMCP tool
    │ validate -> JobSearchInput -> Task
    ▼
Scheduler queue
    ▼
Worker
    │ Task.run()
    ▼
jobs/search/pagination.execute
    │ start cursor state
    │ collect via JobSearchPage
    │ select results + build evidence
    │ finish cursor state
    ▼
JobSearchOutput
    │ resolves Task future
    ▼
MCP Client
```

## Write sequence

```text
MCP Client
    │ linkedin.invitations.send(arguments)
    ▼
FastMCP tool
    │ InvitationSendInput
    │ Task(interruptible=False)
    ▼
Scheduler -> Worker -> invitations/send/tool.execute
                          │
                          ▼
                    inspect target
                          │
                    build command
                          │
                  perform final control once
                          │
                 verify visible postcondition
                          │
                          ▼
                     ActionOutput
```

An unexpected interruption after execution begins returns `uncertain` when a
visible terminal state cannot be proven. The server never retries it.

## Dependency direction

```text
__main__.py ──> cli/ or private HostManager

HostManager ──> transport/{server,stdio}
      │
      ├──────> browser/ ──> official Playwright
      ├──────> infra/{queue,cursor,playwright}
      └──────> tools/ (one-time explicit registration)
                         │
                         ├──> infra/queue: Task, Scheduler
                         ├──> infra/cursor: CursorStore (collections only)
                         ├──> browser/: BrowserManager and task pages
                         ├──> infra/playwright: Paced and collection settling
                         └──> owned models, page, evidence, optional pagination

transport/stdio.py ──> shared host endpoint
```

Transport does not import MCP tool definitions; `HostManager` performs the
single composition step. Page objects never retain a Playwright `Page`; they
obtain a task-scoped raw page from `BrowserManager` for each call.
