# Security Model

## Trust boundaries

The server is intended for one authorized LinkedIn account, one shared local
runtime, one browser worker, and trusted local MCP clients. Each stdio client
uses its own bridge and stateful MCP session, but all attach to that runtime.

Trust is split between:

- the operator, who configures allowed hosts, surfaces, scopes, and effects;
- the MCP client, which applies the operator's configured approval policy to
  each account-changing tool call;
- the server, which validates capability authorization and exact prepared
  action data;
- LinkedIn's visible web UI, which supplies identity, current state, data, and
  postconditions.

A client approval policy does not grant a LinkedIn scope. A server scope does
not prove that a client prompted the user or held an explicit durable per-tool
approval. Both boundaries are required for account-changing actions.

The server has no database or application-secret service. Capability calls,
evidence, action drafts, attempts, and idempotency live only in process memory.

## Authentication profile

Authentication uses an official Playwright persistent Chromium context. The
profile defaults to the operating system's per-user `linkedin-mcp`
application-data directory and is created owner-only on supported POSIX
systems.

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

## Authorization

Runtime authorization requires:

1. a registered capability;
2. every required `ALLOWED_SURFACES` entry;
3. every required `ALLOWED_SCOPES` entry;
4. the required `ALLOWED_EFFECTS` entry.

Read, prepare, and write effects are distinct. The default allowlists contain
every currently implemented capability so a normal installation works without
additional permission configuration. Operators can replace those allowlists
with a narrower set. Final write tools remain destructive MCP operations and
still require an exact prepared action. Their annotations request interactive
confirmation by default, while an explicit durable per-tool client policy may
authorize unattended execution.

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
graceful termination signal and never force-kills it. Clean shutdown rejects
queued work, lets an active write reach a terminal result, closes local
resources, and then releases the lock.

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

One bounded fair scheduler backed by `asyncio.Queue` supplies backpressure and
one worker serializes capability execution. Each MCP session has a FIFO lane;
the worker round-robins lanes between atomic calls. It never interrupts one
browser call to serve another. Queue entries and pacing history are not
durable.

The process-local operation store retains request replay, evidence, action
drafts, attempts, and idempotency only while the shared runtime is alive.
Request replay and drafts are scoped to the internal MCP-session identity;
write idempotency keys remain account-global. This limits local data retention
and removes database credentials and services, but it also narrows safety
guarantees across hard restarts:

- request IDs do not deduplicate after restart;
- evidence resources disappear after restart;
- prepared writes cannot execute after restart;
- execution reservations and uncertain outcomes disappear after restart.

Collection cursors are also process-local authentication-adjacent state. They
contain no cookies, URLs, or captured content, only random tokens plus a client,
account, capability, hashed semantic binding, and stable identities. They are
reserved before queue waiting, single-use, expiring, and bounded. They never
authorize a capability or broaden its configured account, surface, scope, or
effect.

Therefore, a write interrupted by a hard process exit must never be blindly
retried. The caller must inspect the visible LinkedIn target, determine whether
the effect occurred, and create a new prepared action only when safe.

Workflow checkpointing and cross-run deduplication belong to the agent
application, not this MCP server.

## Account-changing actions

Every write family has separate prepare and execute capabilities.

Prepare:

- reads the exact visible actor and target;
- validates the typed payload and configured effect;
- hashes local assets where applicable;
- constructs a canonical SHA-256 payload hash;
- creates a human-readable exact approval preview;
- records an expiring immutable draft in process memory;
- binds that draft to the originating MCP session;
- performs no final LinkedIn account change.

Execute:

- is annotated as destructive;
- requires the exact action ID, payload hash, approval preview, and a fresh
  idempotency key;
- reloads the process-local draft;
- rejects any preview, target, payload, actor, action-type, or expiry drift;
- revalidates current visible preconditions and asset hashes;
- performs only the capability's one narrow final action;
- requires a visible postcondition;
- records `verified`, `failed`, or `uncertain` while the process remains alive.

MCP annotations request interactive client confirmation by default but cannot
attest how a specific call was approved. Writes should use stdio or an
equivalently trusted local client that enforces the operator's configured tool
approval policy. That policy may prompt interactively or explicitly pre-approve
one named execute tool for unattended operation.

No execute capability interprets conversational text such as “yes” as a durable
approval policy or server authorization. The client either invokes the exact
execute tool after its configured approval boundary or it does not invoke it.

## Evidence and client-visible data

Each captured source includes:

- source type;
- exact validated LinkedIn URL;
- capture time;
- retained visible text;
- normalized structured content;
- field-level quotes where the contract requires them.

Evidence objects are immutable after insertion, but available only through the
same live runtime at `linkedin://sources/{source_id}`. Clients that need durable
audit records must copy the required structured data into their own authorized
store before runtime exit.

Logs contain operational metadata and safe error categories. They must not
contain cookies, credentials, browser-profile contents, raw environment
secrets, local attachment contents, or full private message bodies.

## Local assets

Post, comment, and message files are constrained to the configured asset root.
References are validated relative paths; traversal and arbitrary filesystem
paths are rejected. Preparation records hashes and metadata, and execution
rechecks them before use.

The asset directory is user managed and may contain sensitive files. Grant it
only the minimum filesystem access required by the server process.

## Network serving

stdio is the recommended local transport.

Streamable HTTP is restricted to `127.0.0.1`, `::1`, or `localhost`. This
release has no HTTP authentication and must not be exposed on a LAN or public
interface. Stdio bridges and direct HTTP clients share the same account,
browser context, pacing, and fair queue, but request IDs, cursors, and prepared
actions remain isolated by their server-assigned MCP-session identities.

## Reporting a vulnerability

Follow the private reporting instructions in the repository
[security policy](../SECURITY.md).

Do not include cookies, passwords, browser-profile archives, access tokens,
private messages, or other personal LinkedIn content in a report. Provide the
smallest synthetic reproduction that demonstrates the issue.
