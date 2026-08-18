# Security Model

## Trust boundaries

The server is intended for one authorized LinkedIn account, one shared local
runtime, one browser worker, and trusted local MCP clients. Each stdio client
uses its own bridge and stateful MCP session, but all attach to that runtime.

Trust is split between:

- the operator, who selects the LinkedIn account, profile, and trusted MCP
  clients;
- the MCP client, which controls tool availability and approval for each
  account-changing call;
- the server, which validates typed inputs, exact visible targets, attachment
  boundaries, and action postconditions;
- LinkedIn's visible web UI, which supplies identity, current state, data, and
  postconditions.

The server has no database, application-secret service, scope allowlist,
server-side approval ledger, call-result cache, or evidence store. Only active
queue coordination, pacing, and cursors live in process memory.

## Authentication profile

Authentication uses an official Playwright persistent Chromium context. The
profile defaults to the operating system's per-user `linkedin-mcp`
application-data directory. POSIX permissions are tightened to the owner;
Windows uses the current user's application-data directory and inherited user
profile ACL.

Windows background startup uses the operating system's local PowerShell CIM
provider to create the elected runtime outside an MCP client's process Job
Object. The launcher executes a fixed script against `Win32_Process.Create`,
passes the current process environment in memory, removes its two internal
command-routing variables before runtime creation, and makes no network call.
Only the elected Python runtime remains after the launcher exits.

Normal `serve` startup creates this dedicated profile automatically when it is
missing. The first client elects one runtime; subsequent clients attach instead
of opening the profile again. Explicit `profile create`, `login`, `logout`, and
`profile reset` commands acquire the same ownership lock, so maintenance and
the runtime cannot operate the profile concurrently. The project does not
import or adopt an existing general-purpose Chrome profile.

The profile can contain:

- LinkedIn session cookies;
- browser preferences;
- cache and site data;
- other normal Chromium profile material.

Treat the entire profile as a credential:

- never commit it;
- never place it in an MCP response or log;
- never share it with another user or account;
- restrict backup access;
- mount it intentionally in a container;
- remove it and any `*.backup-*` or `*.failed-*` sibling when revoking all
  retained local browser data is required.

The server does not request, read, log, or persist a LinkedIn password. Login
occurs directly on LinkedIn in a headed browser. Completion requires a visible
LinkedIn session cookie with a persistent expiry and departure from login,
checkpoint, and authwall surfaces. The login context is then closed normally,
and the exact profile must still reach the authenticated feed after reopening
in the configured headed or headless mode.

Existing sessions are validated through a normal visible LinkedIn page. An
expired login may open a headed reauthentication flow. Restriction-shaped
pages pause work for operator attention rather than being treated as an
ordinary login.

Explicit logout uses LinkedIn's visible account menu and Sign Out link, waits
for the session cookie to disappear, closes Chromium, and verifies the
signed-out state after a clean reopen. Profile reset first archives the exact
configured directory and restores it if replacement creation fails; that
archive remains credential-sensitive until the operator deletes it.

## Managed Chromium

The managed bootstrap invokes only the official installed Playwright module:

```text
<current Python> -m playwright install chromium
```

It installs the exact revision declared by that Playwright package into a
persistent user cache. The operation is bounded by timeout, captures all child
output, and returns only a fixed safe error on failure. Child output cannot
corrupt MCP stdio or expose environment values to the client.

An explicit `PLAYWRIGHT_BROWSERS_PATH` is treated as an operator-managed cache
override. No browser executable is downloaded from application-controlled
URLs.

## Tool boundary

The server registers only narrow typed tools. It does not implement an
additional scope, effect, or per-tool permission system. Tool availability is
configured in the MCP client. If a trusted client exposes and invokes a tool,
the server treats the call as authorized for the configured account.

Read tools are annotated read-only; account-changing tools are annotated
destructive. A client may prompt, reject, disable, or durably approve an exact
tool. Those annotations and client choices determine whether the call reaches
the server. They do not weaken target validation, host restrictions, bounded
browser execution, attachment validation, or visible postcondition verification.

The server constructs canonical targets from validated identifiers. It never
accepts arbitrary URLs for LinkedIn navigation and never exposes a general
browser primitive.

## Browser restrictions

All LinkedIn access uses visible web UI through the official Playwright async
API.

The browser layer enforces:

- exact configured LinkedIn hosts;
- one configured account and one elected runtime owner;
- one persistent context and serialized operations;
- internal navigation pacing;
- private traversal, scrolling, detail, and expansion bounds behind typed
  `page_size` and opaque cursor contracts;
- authentication, authwall, checkpoint, permission, and restriction guards;
- accessible, user-facing locators where available.

The runtime lock contains only non-secret owner, version, and loopback endpoint
metadata. Normal clients attach through that endpoint; the lock is not a
per-client exclusion gate. It also stores a SHA-256 fingerprint of the
effective non-secret runtime configuration so clients with conflicting policy
cannot silently attach. `status` reads it without opening the browser and also
queries safe queue health. `stop` verifies the same owner before sending a
local stop request bound to that owner's random instance ID, and never
force-kills it. The request marker is non-secret and lives beside the lock.
Clean shutdown rejects queued work, lets an active write reach a terminal
result, closes local resources, and then releases the lock.

The project does not implement:

- CAPTCHA or checkpoint bypass;
- proxy rotation;
- fingerprint spoofing;
- stealth plugins;
- cookie harvesting or browser-profile import;
- private LinkedIn endpoints;
- arbitrary HTTP requests;
- generic JavaScript, selector, click, or navigation tools.

## In-process queue and state

One bounded FIFO scheduler backed by `asyncio.Queue` supplies backpressure and
one worker serializes tool execution. It never interrupts one browser call to
serve another. Queue entries and pacing history are not durable.

Every MCP tool invocation gets its own queue item and executes freshly. The
server does not cache completed reads, coalesce duplicate submissions, record
terminal calls, or retain captured evidence. Consequently:

- request IDs never deduplicate, even within one runtime;
- repeating a read invokes LinkedIn again;
- no MCP resource can retrieve evidence after the tool response; and
- uncertain action outcomes are not durable across restart.

Collection cursors are also process-local authentication-adjacent state. They
contain no cookies, URLs, or captured content, only random tokens plus a client,
account, capability, semantic binding, and stable identities. They are read
and consumed inside the serialized task, single-use, expiring, and bounded. They never
authorize a capability or broaden its configured account.

Therefore, a write interrupted by a hard process exit must never be blindly
retried. The caller must inspect the visible LinkedIn target, determine whether
the effect occurred, and invoke a new action only when safe.

Workflow checkpointing and cross-run deduplication belong to the agent
application, not this MCP server.

## Account-changing actions

Every write family is one direct typed tool. Within that single queued browser
operation, the server:

- reads the exact visible actor, target, and current state;
- validates the typed payload;
- resolves local attachments directly at upload time when applicable;
- builds an internal typed command;
- revalidates the target and visible precondition;
- performs only the capability's one narrow final action;
- requires a visible postcondition; and
- returns `verified`, `failed`, or `uncertain` with source metadata and typed evidence.

MCP annotations identify these tools as destructive but cannot attest how a
specific call was approved. Writes should use stdio or an equivalently trusted
local client that enforces the operator's tool policy. That policy may prompt
interactively or explicitly pre-approve one named tool for unattended use.

The server does not interpret conversational text such as “yes” as a durable
policy. It receives a direct action call only after the client permits it.

## Evidence and client-visible data

Each tool response includes source metadata:

- source type;
- exact validated LinkedIn URL;
- capture time; and
- a stable identifier for that capture.

Typed results also include the visible data and field-level quotes required by
their contracts. Internal captured text is used transiently to validate those
quotes and is discarded after the result is built.

Action-execution source IDs bind to a unique execution identity. Separate
account-changing invocations therefore return distinct source identities even
when their visible capture text and wall-clock timestamp match.

The server does not retain evidence or expose evidence resources. Clients that
need durable audit records must store the tool response in their own authorized
system.

Logs contain operational metadata and safe error categories. They must not
contain cookies, credentials, browser-profile contents, raw environment
secrets, local attachment contents, or full private message bodies.

## Local assets

Post, comment, and message files are constrained to the configured asset root.
References are validated relative paths; traversal and arbitrary filesystem
paths are rejected. Immediately before upload, the server resolves the current
file and validates its supported extension and LinkedIn size limit.

The asset directory is user managed and may contain sensitive files. Grant it
only the minimum filesystem access required by the server process.

## Network serving

stdio is the recommended local transport.

Streamable HTTP is restricted to `127.0.0.1`, `::1`, or `localhost`. This
release has no HTTP authentication and must not be exposed on a LAN or public
interface. Stdio bridges and direct HTTP clients share the same account,
browser context, pacing, and FIFO queue. Cursors remain isolated by their
server-assigned MCP-session identities.

## Reporting a vulnerability

Follow the private reporting instructions in the repository
[security policy](../SECURITY.md).

Do not include cookies, passwords, browser-profile archives, access tokens,
private messages, or other personal LinkedIn content in a report. Provide the
smallest synthetic reproduction that demonstrates the issue.
