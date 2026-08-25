# Troubleshooting

Run this first:

```bash
uvx --from linkedin-mcp-local linkedin-mcp doctor
```

It reports non-secret browser-installation, profile, configuration, and
Streamable HTTP information. Once the server is connected, call
`linkedin.session.status` for authentication/pause state and
`linkedin.server.status` for process-local operation-lock state.

## The browser is not installed

Run:

```bash
uvx --from linkedin-mcp-local linkedin-mcp setup
```

Automatic installation is enabled by default. Check
`BROWSER_CACHE_PATH`, filesystem permissions, available disk space, and network
access if installation still fails.

## The browser profile does not exist

Create the dedicated profile before login or serving:

```bash
uvx --from linkedin-mcp-local linkedin-mcp profile create
```

Inspect it without opening LinkedIn:

```bash
uvx --from linkedin-mcp-local linkedin-mcp profile status
```

## Login is required or expired

Stop the foreground server, then run:

```bash
uvx --from linkedin-mcp-local linkedin-mcp login
```

Complete login, MFA, or a checkpoint in the visible browser. The command closes
and reopens the profile to verify persistence. `serve` performs this check too,
but an explicit login is easier to diagnose.

If a restriction or checkpoint remains after login, stop live access and review
the account in a normal browser. The server does not bypass those controls.

## The HTTP endpoint is unavailable

Start the foreground server:

```bash
uvx --from linkedin-mcp-local linkedin-mcp serve
```

The default MCP endpoint is:

```text
http://127.0.0.1:8000/mcp
```

Check that the client is configured for Streamable HTTP, not stdio or SSE. Also
check `LINKEDIN_MCP_HTTP_HOST`, `LINKEDIN_MCP_HTTP_PORT`, local firewall rules,
and whether another process already owns the port. There is no separate health
server or readiness endpoint; FastMCP owns the listener directly.

## Another browser process owns the profile

Only one server or profile-changing command may use a persistent profile at a
time. Stop the other process cleanly and retry. Do not delete Chromium's own
profile lock files while Chromium is running.

Multiple MCP clients can connect to one running HTTP server. They share that
process's one browser context, one operation lock, and cursor manager. Do not
start one server per client with the same profile.

## A request is waiting

The server intentionally runs one complete LinkedIn operation at a time. Other
requests wait on one process-local `asyncio.Lock`; there is no task queue or
worker process. Call `linkedin.server.status` to see the active operation and
number of waiters.

If the active operation is stuck, allow its configured browser timeout to
expire. Force-stopping the process during an account-changing tool may leave the
outcome uncertain.

## A cursor is invalid or expired

Cursors are process-local, single-use, expiring, and bound to the account,
capability, and semantic filters. Start a new scan after server restart, cursor
expiry, consumption, or a filter change. Do not reuse the same cursor in
parallel requests.

## Results are truncated or report parser drift

This is an explicit safety result, not a successful complete scan. LinkedIn may
have reached a configured traversal bound, stopped exposing a verifiable end,
or changed visible markup. Preserve the result metadata and file a report with
synthetic details only—never attach cookies, profile data, or personal content.

## A write result is uncertain

Inspect LinkedIn's visible state before doing anything else. Do not blindly
retry. The final control may have run even if the client disconnected or the
postcondition could not be verified.

## An upload path is missing in Docker

Host files are not automatically visible in a container. Mount the intended
directory and pass its container path:

```bash
docker run --rm \
  --publish 127.0.0.1:8000:8000 \
  --volume /host/uploads:/uploads:ro \
  --volume linkedin-mcp-data:/data/linkedin-mcp \
  ghcr.io/prakharagarwal-dev/linkedin-mcp-server:latest
```

The server applies no asset-root containment. It can read any path permitted to
its OS user, so mount and approve only intended files.

## Resetting a damaged profile

Stop the server, then run:

```bash
uvx --from linkedin-mcp-local linkedin-mcp profile reset
```

The command creates a timestamped sibling backup before replacing the profile.
That backup remains sensitive. Recreate login after the reset.
