# Low-Level Design

This is the implemented design. It deliberately keeps execution generic and
puts LinkedIn behavior inside the tool that owns it.

## Core classes

```text
┌──────────────────────────────────────────────────────────────────┐
│ AppContainer                                                     │
│                                                                  │
│ owns: Settings, Scheduler, Worker, BrowserManager,                │
│       PaginationManager, AccountProcessLock, concrete tool pages │
│                                                                  │
│ start()   quiesce()   close()                                    │
└──────────────┬───────────────────────────────────────────────────┘
               │ supplied to every registered tool
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
- `AppContainer` wires long-lived dependencies. It contains no business flow.

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
   ├── starts cursor state
   ├── calls page.collect(...)
   ├── selects unseen results
   ├── calls evidence builder
   ├── finishes cursor state
   └── returns JobSearchOutput
                    │
                    ▼
page.py ──> BrowserManager ──> BrowserRuntime ──> Playwright
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
host/ ──> transport/server.py ──> tools/*/tool.py
                                      │
                                      ├──> execution/Task, Scheduler, Worker
                                      └──> tool-owned models, page, evidence, optional pagination
                                      │
                                      ▼
                            shared LinkedIn UI helpers
                                      │
                                      ▼
                               browser runtime
                                      │
                                      ▼
                                  Playwright

transport/stdio.py ──> shared host endpoint
```

Lower layers never import MCP tool definitions. Page objects never retain a
Playwright `Page`; they obtain an operation-scoped page from the browser layer.
