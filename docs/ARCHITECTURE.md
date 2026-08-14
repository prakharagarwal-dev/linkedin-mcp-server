# Architecture

## System boundary

The project is one standalone Python MCP server for one configured LinkedIn
account.

```text
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│ MCP client A        │  │ MCP client B        │  │ MCP client C        │
│ stdio bridge        │  │ stdio bridge        │  │ direct HTTP         │
└──────────┬──────────┘  └──────────┬──────────┘  └──────────┬──────────┘
           └────────────────────────┼────────────────────────┘
                                    │ stateful loopback MCP
┌───────────────────────────────────▼────────────────────────────────┐
│ One shared local runtime for one configured LinkedIn account       │
│                                                                    │
│ session identity -> typed registry -> fair asyncio queue            │
│                                          │                         │
│ client-scoped read calls/cursors           ▼                         │
│                              one atomic browser operation           │
│                                          │                         │
│                    typed page objects + global navigation pacer     │
│                                          │                         │
│                    one Chromium context + one temporary Page        │
└──────────────────────────────────────────┬─────────────────────────┘
                                           │ Playwright, visible UI
                              ┌────────────▼────────────┐
                              │ exact LinkedIn hosts   │
                              └─────────────────────────┘

Persistent local filesystem:
  browser cache ─ matching Playwright Chromium revision
  browser profile ─ LinkedIn cookies and normal Chromium preferences
  asset root ─ explicitly selected user files
  runtime lock ─ non-secret owner, version, endpoint, and configuration hash
```

The server does not contain an agent, LLM, LangGraph graph, ranking algorithm,
workflow scheduler, cross-run memory, or database. It does not expose generic
browser, click, JavaScript, selector, URL, HTTP, or network capabilities.

## Composition and layers

### Transport

`server.py` builds the official SDK `FastMCP` server and registers each typed
tool and evidence resource.

- stdio is the default client-facing transport;
- every stdio process is a transparent bridge to the shared loopback runtime;
- direct Streamable HTTP is restricted to the same loopback endpoint;
- the first client elects and starts the runtime, and later clients attach;
- browser installation and authentication bootstrap run as background tasks,
  keeping initialization responsive.

The loopback listener owns the application lifecycle. One container, internal
ownership lock, fair queue, browser context, pacing history, cursor manager,
operation store, and authentication coordinator remain alive when an
individual stdio or HTTP client disconnects. `linkedin-mcp stop` gracefully
ends the exact elected owner. The lock is runtime election and maintenance
coordination; normal MCP clients do not compete for browser-profile ownership.
The lock's SHA-256 configuration fingerprint also prevents a client with
different profile, browser, pacing, or endpoint settings from silently
inheriting the first client's runtime configuration.

The runtime uses stateful MCP sessions. It assigns each server session an
opaque internal identity; callers cannot provide or override it. That identity
scopes read replay, in-flight read coalescing, cursor ownership, and progress.

Tool annotations distinguish read-only and destructive behavior. The MCP client
may prompt for a destructive call or durably pre-approve an exact tool. The
server receives the call only after that client-side boundary.

### Domain contracts

`domain/models.py` contains strict, frozen Pydantic v2 models for:

- capability names, effects, surfaces, and status;
- Jobs, People, Company, post, comment, connection, and messaging inputs;
- stable LinkedIn identifiers and bounded filter values;
- observations, coverage, and evidence;
- shared collection `page_size`/`cursor` inputs and pagination metadata;
- internal action commands, visible inspections, and terminal outcomes.

Undeclared fields are rejected. IDs, slugs, URLs, tuple sizes, text lengths,
time windows, and enumerated choices are bounded before browser access.

The public networking namespaces follow the resource lifecycle:

- `linkedin.invitations.*` owns invitation listing, sending, accepting, and
  ignoring;
- `linkedin.connections.*` owns listing and searching established
  first-degree connections; and
- `linkedin.people.search` owns broader People discovery across explicit
  connection degrees.

`linkedin.connections.search` deliberately has no connection-degree input.
The executor binds its shared People-search adapter to first degree and rejects
any returned card that is not visibly first-degree.

### Capability registry

The capability registry maps every public capability to:

- version;
- input and output model;
- effect: `read` or `write`; and
- required visible LinkedIn surfaces.

The server registers every implemented capability. Tool availability and
approval belong to the MCP client. Required surfaces are implementation
metadata used to keep each page adapter narrow; they are not a second
permission system.

### Fair queue and atomic worker

A bounded in-process scheduler uses `asyncio.Queue` for ready client lanes and
FIFO deques within each lane. It preserves submission order for one client and
round-robins across clients. A client with a large backlog therefore cannot
indefinitely delay another client, while queue backpressure remains internal.

One worker still permits exactly one browser-backed capability call at a time.
A call is atomic: it is never paused halfway through so another client can
reuse its Page. Each call starts from its typed target, obtains one temporary
Page, finishes or fails, and closes that Page. Fairness happens between calls.
A paginated workflow can interleave with other clients only when it returns a
page and the client later submits its next cursor call.

The queue is not durable. A runtime exit rejects queued work. If a caller
cancels its last waiter, queued work is removed; an active read is cancelled;
an active account-changing action continues in the background until it reaches
a verified, failed, or uncertain result. This avoids interrupting a LinkedIn
mutation whose external effect may already have started.

`status` inspects non-secret owner and queue metadata without browser access.
`stop` rechecks exact ownership, sends `SIGTERM`, and waits for release. Clean
shutdown stops admission, rejects queued calls, preserves an active write to a
terminal result, closes memory and Chromium, and releases the lock. The CLI
never escalates to a force kill.

### Executor

The executor owns the common capability lifecycle:

1. resolve the registered descriptor;
2. validate session-scoped replay for reads;
3. use the cursor lease reserved before queue admission for collection calls;
4. call the narrow page-object provider with an internal traversal target;
5. remove already-seen stable identities and retain one-item lookahead;
6. normalize typed output, pagination metadata, and captured evidence;
7. store read replay/evidence in the current process;
8. return structured MCP output.

For an action, the executor creates a unique internal call record, inspects the
exact visible actor, target, and current state, snapshots any local assets,
builds an internal typed command, performs the narrow mutation, and records the
terminal result. The internal inspection and command are never separate public
tools.

Browser and page-object exceptions are projected as safe domain errors.
Secrets, raw page dumps, subprocess output, and internal exception details are
not sent to clients.

Invitation listing follows the same cursor lifecycle. Its page object still
preserves the stricter LinkedIn-specific inventory contract: one selected view
must reconcile its exact advertised count before a terminal response, while
the synthetic Received `all` selection must reconcile every current visible
view and deduplicate overlapping invitation identities into one exact union.
Earlier pages may stop at a bounded live prefix; a continuation revisits the
visible UI and suppresses identities already returned by the scan.

### Process-local operation store

`MemoryRepository` implements the operation-store contract with dictionaries
protected by one async lock. It retains only what a live process needs:

- read request fingerprints and completed result replay; and
- captured evidence resources, including terminal action evidence.

Nothing is serialized. A server restart creates a new empty store. This is an
intentional local-runtime tradeoff, not an accidental loss of durability.

Read replay is scoped by the internal MCP-session identity. Every
account-changing invocation is new and bypasses read replay and coalescing.
Evidence remains an immutable runtime resource. The store is not workflow
memory and cannot be used for cross-run tracking or write deduplication.

### General collection cursor manager

The cursor manager is separate from `MemoryRepository`. It keeps a bounded
process-local map from random opaque cursor tokens to:

- client session, account, capability, and canonical semantic-input binding;
- one scan ID and the stable identities already returned;
- expiry and a short-lived in-use reservation.

The first call has no cursor. A continuation cursor is validated and reserved
before its call waits in the fair queue. Queue delay therefore cannot expire
the reserved continuation or let a second call consume it. If more live items
are visible, successful completion consumes the input cursor and returns a new
single-use cursor. Failed or cancelled browser/parser work releases the
reservation so the same originating client can retry. Successful consumption,
expiry before reservation, client/filter/account/capability mismatch, runtime
restart, and concurrent reuse fail closed with `invalid_cursor`.

LinkedIn does not provide a public snapshot token through the visible UI. A
continuation therefore performs another bounded traversal from the beginning,
skips stable identities already emitted, and reads one unseen lookahead item.
This is reported as `live_deduplicated`: it prevents duplicates within the scan
but does not promise snapshot isolation while LinkedIn results change.

### Invitation terminal reconciliation

Invitation reads use the general cursor manager but retain stronger terminal
proof. A bounded request selects the exact Received or Sent view—or the current
six-view Received union—captures advertised counts, accumulates typed cards
across lazy-loaded or virtualized windows, excludes neighboring
recommendations, and deduplicates stable identities. Reaching the requested
live prefix returns `result_limit`; exhausting the private traversal bound
returns `safety_bound`. Only a complete exact count, or an exact reconciled
multi-view union, returns `visible_page_complete` and terminal
`has_more=false` without truncation.

### Browser bootstrap

`BrowserRuntimeBootstrap` reads the browser revision registry shipped by the
installed Playwright Python package. When the required Chromium and headless
shell markers are absent, it runs the official command:

```text
python -m playwright install chromium
```

The command uses a persistent per-user browser cache rather than an ephemeral
wheel or `uvx` environment. Subprocess output is captured and never forwarded
to MCP stdout or error responses. Installation is bounded and can be invoked
explicitly with `linkedin-mcp setup`.

`PLAYWRIGHT_BROWSERS_PATH` remains an operator override. Otherwise the cache
defaults to Playwright's platform-native persistent cache (for example,
`~/Library/Caches/ms-playwright` on macOS). Keeping the native cache location
preserves headed/headless Chromium profile compatibility.

### Browser and authentication manager

The browser manager owns one official Playwright persistent context:

```text
chromium.launch_persistent_context(
    user_data_dir=<configured profile>,
    headless=<runtime setting>,
)
```

The profile is the only server-owned authentication persistence. Chromium
writes cookies and preferences normally when the context closes.

Startup behavior:

1. acquire the configured account lock and publish non-secret owner metadata;
2. schedule managed Chromium setup when automatic installation is enabled;
3. initialize the dedicated persistent profile when it is missing;
4. silently validate an existing session when profile data is already present;
5. otherwise open one headed LinkedIn login context on that profile;
6. select LinkedIn's visible **Keep me signed in** control when available;
7. wait for the user to finish LinkedIn login/checkpoint work;
8. require a persistent LinkedIn session cookie and departure from interactive
   auth surfaces;
9. close the login context normally and reopen the exact profile in the
   configured headed or headless mode;
10. navigate to the authenticated feed and apply the normal safety guard; and
11. only then report login success and start the normal runtime context.

The MCP handshake does not wait for steps 2–11. A capability that requires the
browser waits for the background authentication task.

The same profile manager backs explicit `profile create`, `profile status`, and
recoverable `profile reset` commands. Manual `login` operates only on an
initialized profile. Manual `logout` follows LinkedIn's visible account menu
and Sign Out control, then proves the session remains absent after a clean
profile reopen. No command imports or adopts a user's general Chrome profile.

For each capability operation, the manager creates a fresh Page within the one
persistent context and closes that Page afterwards. The context itself is
reused until process shutdown or reauthentication.

### Navigation and page objects

Every page object:

- constructs only canonical URLs for configured LinkedIn hosts;
- uses user-facing or accessible Playwright locators;
- calls the shared pacer before navigation or important UI interaction;
- checks login, authwall, checkpoint, permission, and restriction surfaces;
- enforces private pagination, scroll, expansion, and detail-page bounds;
- extracts only visible data into typed observations;
- retains exact source URL, capture time, visible text, and field evidence.

Facet name resolution uses the visible LinkedIn filter UI. A missing or
ambiguous exact match fails closed instead of silently broadening a search.

Asynchronously rendered collections share bounded observation mechanics.
Progress is measured from raw visible DOM identities, independently of domain
parsing, so a newly rendered card cannot disappear from progress detection
merely because its fields are malformed or unfamiliar. A polling timeout is
only an idle observation and never proves end-of-list. Completion requires an
explicit visible empty/end state or a surface-specific terminal observation.
For invitations, the current Received and Sent layouts have distinct exact card
roots. Received cards are direct children of current `data-display-contents`
wrappers; Sent cards are direct children of the current lazy column. No legacy
selector fallback exists. Target-bound Received Ignore/Accept and Sent
Withdraw controls identify invitation cards, while neighboring Connect
recommendations are reported separately. A real single view succeeds only
after exact reconciliation to its Focused, Other, Verified, Mutual
Connections, Your Company, Your School, or Sent People count. Received `all`
is the deduplicated union of the six real received views because the current
UI has no reliable All control or count. A changed count discards the partial
attempt and restarts once; repeated change asks the caller to retry.

For connections, fresh inspection established that LinkedIn may render no
terminal copy: the nested `main` scroller instead reaches physical bottom, its
raw-card signature and scroll geometry remain unchanged across additional
probes, and no loader or tail control is visible. An unambiguous visible
`N connections` inventory gates that terminal state.

## Read lifecycle

```text
client tool call (internal MCP-session identity)
  -> Pydantic input validation
  -> registered typed capability resolution
  -> reserve collection cursor when applicable
  -> enqueue in the client's FIFO lane
  -> fair selection of the next client
  -> session-scoped request-id check
  -> wait for browser setup/authentication
  -> paced visible LinkedIn interaction
  -> page safety check
  -> stable-identity deduplication + typed extraction + evidence
  -> consume cursor and return terminal/new pagination state
  -> process-local result/evidence storage
  -> structured MCP response
```

The client can read returned evidence through
`linkedin://sources/{source_id}` while the process is alive.

## Action lifecycle

Each account-changing capability is one public tool call:

```text
typed action input
  -> client tool-availability / approval policy
  -> fair queue and one uninterrupted browser operation
  -> inspect exact visible actor, target, and precondition
  -> snapshot and validate local assets when present
  -> build an internal typed action command
  -> recheck target, state, and attachment hashes
  -> perform one narrow final UI action
  -> verify visible postcondition
  -> return verified | failed | uncertain with immutable evidence
```

Invitation actions resolve exact member profiles rather than selecting a member
from a broad list scan. Message, post, comment, and reaction actions bind the
exact visible destination in the same operation. There is no public draft,
preview, scope grant, or idempotency key.

An uncertain result is never automatically retried. Every new tool invocation
is a new action, so an operator or agent must inspect visible LinkedIn state
before deciding whether another invocation is safe.

## LangGraph integration

LangGraph connects as an MCP client. A graph typically:

1. lists enabled capabilities;
2. allocates a workflow `context_id`;
3. calls bounded search and detail tools;
4. consumes structured observations and evidence;
5. ranks or deduplicates in graph state;
6. checkpoints graph state in the application's own checkpointer;
7. calls an action tool through the configured MCP client policy; and
8. continues based on the terminal result or later read observations.

The LangGraph checkpointer is independent of the MCP server. It may use
PostgreSQL, SQLite, Redis, or another backend without changing this server.

For recurring job search, the graph or scheduler starts each run. The MCP
server deliberately has no timer or continuous background search.

## Adding a capability

A multi-item capability must follow
[`COLLECTION_VERIFICATION_PROCESS.md`](COLLECTION_VERIFICATION_PROCESS.md);
clean termination by itself is not acceptance.

A new vertical slice normally requires:

1. strict input, output, observation, and coverage models;
2. a stable capability name and version;
3. exact required visible surfaces and read/write effect;
4. a narrow page-object provider;
5. bounded visible extraction or mutation;
6. field evidence and safe error mapping;
7. fixture tests;
8. executor and protocol tests;
9. capability-matrix and build-status updates.

A new write must additionally define one direct typed tool, internal target
inspection, asset-integrity rules, visible preconditions, cancellation
behavior, and a provable terminal postcondition.
