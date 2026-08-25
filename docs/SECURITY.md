# Security design

## Trust boundary

This is a local, single-process MCP server for one configured LinkedIn profile.
It trusts the operating-system user and explicitly configured MCP clients. It
does not provide multi-user isolation, HTTP authentication, or a hosted service.

The supported network transport is Streamable HTTP. It binds to
`127.0.0.1:8000` by default. Do not bind to a non-loopback interface unless a
trusted external network boundary supplies authentication and access control.

FastMCP owns MCP HTTP sessions and request correlation. Those protocol sessions
are not authorization records and do not own browser pages or operations.

## Product boundary

Public tools are typed LinkedIn capabilities. The server does not expose:

- arbitrary URLs or navigation;
- generic clicks, selectors, JavaScript, or browser pages;
- raw HTTP or private LinkedIn endpoints;
- CAPTCHA bypass, proxy rotation, fingerprint spoofing, or stealth plugins;
- credential collection; or
- an LLM, agent, planner, database, or external work queue.

Navigation is limited to the configured LinkedIn hostnames. Access checks pause
live use on authentication expiry, checkpoints, restriction pages, permission
failures, and configuration errors.

## Authentication persistence

The persistent Chromium profile is the only server-owned authentication
persistence. It contains sensitive cookies and browser preferences. Never
commit, upload, or share it. Protect it with operating-system permissions and
backups appropriate for authentication material.

The server does not accept a LinkedIn password. Login and logout use visible
LinkedIn controls in a headed browser. Startup validates the saved session
synchronously. If login is needed, it completes and verifies the visible login
flow before MCP requests are accepted; authentication is not a background task.

Use one server process per profile. Stop `serve` before running login, logout,
or profile-reset commands. Chromium also rejects concurrent use of the same
persistent profile, but operators should not rely on that error as coordination.

## Operation serialization

`OperationManager` uses one process-local `asyncio.Lock`. A complete LinkedIn
operation holds it from immediately before page work until its typed result or
error is produced. This guarantees that only one tool manipulates the shared
browser context at a time.

There is no queue object, scheduler, worker, background executor, or result
store. Waiting requests are ordinary coroutines waiting for the lock. Restarting
the process drops waiters and clears process-local state.

Read calls are cancellable and execute freshly. Once a write has started, a
caller disconnect does not cancel the underlying LinkedIn action. The action is
allowed to reach a terminal state before the lock is released. The server never
automatically retries a write after its final LinkedIn control may have run.

## Account-changing tools

Each write tool is one complete, typed action. It checks the exact visible
target and precondition, invokes the final control at most once, checks the
visible postcondition, and returns `verified`, `failed`, or `uncertain`.

MCP tool availability and the client's approval policy are the authorization
boundary. Write annotations request interactive confirmation by default. The
server does not keep a second scope, preview, approval, or idempotency layer.
After an uncertain or interrupted write, inspect LinkedIn before invoking it
again.

## Collection integrity

Collection tools use bounded traversal and must reconcile the selected visible
inventory with typed results and explicitly unsupported cards. A clean stop is
not enough to claim completeness. If reconciliation fails or cannot be
performed, the result reports a safety bound, truncation, or parser-drift state.

Opaque cursors retain only stable identities already returned. They are
process-local, expiring, single-use, and bound to an account, capability, and
semantic filter set. They contain no result or evidence payload. The one
operation lock protects cursor updates together with their associated browser
operation.

## File uploads

Upload tools can read any path supplied by an authorized MCP client that the
server process can read. There is deliberately no asset root or containment
check. Capability-specific code selects the intended visible LinkedIn upload
control, and LinkedIn accepts or rejects the file format and size.

This is a strong trust decision: a malicious client could transmit readable
local files to LinkedIn. Run the server as a least-privileged OS user, connect
only trusted MCP clients, and approve only intended file-bearing actions. In a
container, mount only required paths, preferably read-only.

## Secrets and logs

Never commit `.env`, cookies, storage state, passwords, private keys, database
credentials, or API tokens. The default test suite uses synthetic fixtures and
must not contain live sessions, HAR files, traces, or captured LinkedIn media.

Structured logs go to standard error and must contain only operational metadata.
Tool results, page contents, cookies, credentials, supplied message text, and
file contents must not be logged. Error projection exposes stable safe messages,
not raw Playwright exceptions or environment values.

## HTTP deployment

For a local installation, keep the default endpoint:

```text
http://127.0.0.1:8000/mcp
```

For Docker, the process listens on all interfaces inside its private network
namespace. Publish it only to host loopback:

```bash
docker run --publish 127.0.0.1:8000:8000 ...
```

Do not expose the unauthenticated endpoint to a LAN, public interface, ingress,
or reverse proxy without adding an appropriate external authentication and
authorization boundary.

## Stored state and deletion

The server stores no call results, observations, or evidence. The operation
lock, status counters, cursors, and browser access state exist only in memory.
The browser profile and Playwright cache are the only managed on-disk data.

`profile reset` moves the old profile to a timestamped sibling backup before
creating a clean profile. That backup remains sensitive until the operator
deletes it. See [PRIVACY.md](../PRIVACY.md) for retention details.

## Reporting

Report vulnerabilities through the private process described in
[SECURITY.md](../SECURITY.md). Do not include credentials, cookies, profile
archives, or personal LinkedIn data in a report.
