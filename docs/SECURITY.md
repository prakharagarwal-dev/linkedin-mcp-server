# Security Model

## Trust boundaries

The server is intended for one authorized LinkedIn account, one local process,
one browser worker, and trusted local MCP clients.

Trust is split between:

- the operator, who configures allowed hosts, surfaces, scopes, and effects;
- the MCP client, which decides whether to show and approve a destructive tool
  call;
- the server, which validates capability authorization and exact prepared
  action data;
- LinkedIn's visible web UI, which supplies identity, current state, data, and
  postconditions.

A client confirmation does not grant a LinkedIn scope. A server scope does not
prove that a client displayed confirmation. Both boundaries are required for
account-changing actions.

The server has no database or application-secret service. Capability calls,
evidence, action drafts, attempts, and idempotency live only in process memory.

## Authentication profile

Authentication uses an official Playwright persistent Chromium context. The
profile defaults to the operating system's per-user `linkedin-mcp`
application-data directory and is created owner-only on supported POSIX
systems.

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
- remove it when revoking the local session is required.

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

Runtime authorization is deny-by-default and requires:

1. `LIVE_ENABLED=true`;
2. a registered capability;
3. every required `ALLOWED_SURFACES` entry;
4. every required `ALLOWED_SCOPES` entry;
5. the required `ALLOWED_EFFECTS` entry.

Read, prepare, and write effects are distinct. Default configuration permits
only Jobs and People reads. Company, post, discussion, connection, messaging,
and every write scope require explicit opt-in.

The server constructs canonical targets from validated identifiers. It never
accepts arbitrary URLs for LinkedIn navigation and never exposes a general
browser primitive.

## Browser restrictions

All LinkedIn access uses visible web UI through the official Playwright async
API.

The browser layer enforces:

- exact configured LinkedIn hosts;
- one configured account and one process lock;
- one persistent context and serialized operations;
- internal navigation pacing;
- private traversal, scrolling, detail, and expansion bounds behind typed
  `page_size` and opaque cursor contracts;
- authentication, authwall, checkpoint, permission, and restriction guards;
- accessible, user-facing locators where available.

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

One bounded `asyncio.Queue` supplies backpressure and one worker serializes
capability execution. Queue entries and pacing history are not durable.

The process-local operation store retains request replay, evidence, action
drafts, attempts, and idempotency only while the process is alive. This limits
local data retention and removes database credentials and services, but it
also narrows safety guarantees across hard restarts:

- request IDs do not deduplicate after restart;
- evidence resources disappear after restart;
- prepared writes cannot execute after restart;
- execution reservations and uncertain outcomes disappear after restart.

Collection cursors are also process-local authentication-adjacent state. They
contain no cookies, URLs, or captured content, only random tokens plus hashed
semantic bindings and stable identities. They are single-use, expire, have
global/per-scan memory bounds, and never authorize a capability or broaden its
configured account, surface, scope, or effect.

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

MCP annotations request native client confirmation but cannot attest that a
specific user approved a call. Writes should use stdio or an equivalently
trusted local client that always asks the user before invoking destructive
execute tools.

No execute capability interprets conversational text such as “yes” as server
authorization. The client either invokes the exact execute tool after its
approval boundary or it does not invoke it.

## Evidence and client-visible data

Each captured source includes:

- source type;
- exact validated LinkedIn URL;
- capture time;
- retained visible text;
- normalized structured content;
- field-level quotes where the contract requires them.

Evidence objects are immutable after insertion, but available only through the
same live process at `linkedin://sources/{source_id}`. Clients that need durable
audit records must copy the required structured data into their own authorized
store before process exit.

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
interface. Multiple clients connected to one loopback server share the same
account, queue, browser context, pacing, and in-process action store.

## Reporting a vulnerability

Follow the private reporting instructions in the repository
[security policy](../SECURITY.md).

Do not include cookies, passwords, browser-profile archives, access tokens,
private messages, or other personal LinkedIn content in a report. Provide the
smallest synthetic reproduction that demonstrates the issue.
