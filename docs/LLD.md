# Low-Level Design

This is the implemented design. It deliberately keeps the task queue generic
and puts LinkedIn behavior inside the tool that owns it.

## Core classes

```text
┌──────────────────────────────────────────────────────────────────┐
│ HostManager                                                      │
│                                                                  │
│ transport: attach stdio or own Streamable HTTP                   │
│ startup: lock -> browser/login -> UI -> queue/tools -> listener  │
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

## Browser and UI classes

```text
HostManager
    │ start / login / logout / close
    ▼
BrowserManager ──> official Playwright ──> persistent BrowserContext
                                             │ supplied once
                                             ▼
                                    LinkedInPlaywright
                                      │            │
                         page() owns  │            │ pacing/safety
                                      ▼            ▼
                                LinkedInPage ──> LinkedInLocator
                                      │               │
                                      └──── official Page/Locator
```

- `BrowserManager` owns Chromium installation readiness, the persistent
  context, saved-session validation, visible login/logout, and browser close.
- `LinkedInPlaywright` owns navigation pacing, exact-host validation, access
  pause state, task-page creation, popup cleanup, and safety checks.
- `LinkedInPage` and `LinkedInLocator` preserve familiar Playwright calls such
  as `page.goto(...)` and `locator.click()` while routing guarded actions
  through `LinkedInPlaywright`.
- Tool page objects depend only on `LinkedInPlaywright`; they never call
  `BrowserManager` or own a persistent context.

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
                         │ create LinkedInPlaywright
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
the scheduler, closes cursor state and the UI facade, closes Chromium, then
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
└── models/           input, output, filters, coverage, summaries
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
page.py ──> LinkedInPlaywright ──> wrapped official Playwright controls
```

A non-paginated read keeps its small `execute(...)` function directly in
`tool.py`. A write tool also keeps its execution function in `tool.py` and uses
the shared single-attempt action helper:

```text
tools/invitations/send/tool.py
   │
   ├── creates InvitationSendInput
   ├── creates non-interruptible Task
   └── execute(request, page)
           │
           ├── tools/action.py: inspect -> command -> perform once -> evidence
           └── page.py: exact visible controls and postcondition
```

There is no `Operation`, `CapabilityExecutor`, provider protocol hierarchy, or
capability switch statement.

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
      ├──────> ui/ ──> supplied BrowserContext
      ├──────> infra/{queue,cursor}
      └──────> tools/ (one-time explicit registration)
                         │
                         ├──> infra/queue: Task, Scheduler
                         ├──> infra/cursor: CursorStore (collections only)
                         ├──> ui/: LinkedInPlaywright Page/Locator facade
                         └──> owned models, page, evidence, optional pagination

transport/stdio.py ──> shared host endpoint
```

Transport does not import MCP tool definitions; `HostManager` performs the
single composition step. Page objects never retain a Playwright `Page`; they
obtain a task-scoped wrapped page from `LinkedInPlaywright`.
