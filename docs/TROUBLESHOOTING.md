# Troubleshooting

Start with the package's non-secret diagnostics:

```bash
uvx --from linkedin-mcp-local linkedin-mcp setup
uvx --from linkedin-mcp-local linkedin-mcp doctor
```

`setup` ensures the matching Playwright Chromium revision is installed.
`doctor` reports package, browser, profile, authentication, pause, and lock
readiness without exposing cookies or credentials.

## The MCP server does not start

Run the exact package command outside the client:

```bash
uvx --from linkedin-mcp-local linkedin-mcp doctor
```

If `uvx` is not found, install [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
and restart the GUI client. GUI applications may not inherit the shell's PATH;
replace `uvx` in the client configuration with the absolute path from:

```bash
command -v uvx
```

On Windows, use:

```powershell
where.exe uvx
```

Cold `uvx` resolution can take longer than a client's default startup bound.
Use at least 60 seconds for MCP startup and up to 900 seconds for LinkedIn tool
calls when the client exposes those settings. Restart the client after changing
its MCP configuration.

## LinkedIn authentication is required

Run the persistent-profile login flow:

```bash
uvx --from linkedin-mcp-local linkedin-mcp login
```

Complete login, MFA, or checkpoints only in the opened LinkedIn browser. The
server never needs the password. A successful login is verified through a
clean browser restart before the command exits.

If LinkedIn shows a checkpoint, restriction, or security review, resolve it
manually. The server intentionally pauses and does not bypass those pages.

## Another process owns the browser profile

Only one server process may own one account profile. Close the other MCP client
or stop its LinkedIn MCP process before retrying. If several clients must use
the account simultaneously, run one loopback Streamable HTTP server and connect
each client to `http://127.0.0.1:8000/mcp`.

Do not delete the runtime lock while a server or browser process is still
running.

## A tool is installed but disabled

Call `linkedin.capabilities.list`. Its response identifies missing surfaces,
scopes, or effects. Add only the required values to the MCP server's `env`
configuration, then restart the client. Ready-made presets are in
[Configuration](CONFIGURATION.md).

Native client confirmation never grants a missing server scope. Conversely,
granting a server scope does not mean a client should auto-approve a write.

## A collection stops at a safety bound

Collection tools return pagination and completeness metadata. Continue with
`pagination.next_cursor` when present. A `truncated` or parser-drift result is
an honest incomplete result, not a successful end of the LinkedIn collection.

Cursors are process-local, single-use, filter-bound, and expire after an idle
period. Start a new scan after a restart, cursor expiry, or filter change.

## A write result is uncertain

Do not immediately retry. An uncertain result means the server could not prove
the visible postcondition within its bound; it does not prove that LinkedIn
rejected the action. Read the exact profile, conversation, post, or invitation
state first, then prepare a new action only if that visible state proves the
effect did not occur.

## An attachment is rejected

The file must be below `LINKEDIN_MCP_ASSET_ROOT_PATH` and referenced by a
relative `asset_ref`. It must also satisfy the capability's visible media type
and size constraints. Do not pass a raw Downloads/Desktop path to a tool.

Preparation hash-locks the current file. If the file changes before execute,
prepare a new action.

## Claude Desktop extension problems

Use the `.mcpb` from the
[latest GitHub release](https://github.com/prakharagarwal-dev/linkedin-mcp-server/releases/latest).
In Claude Desktop, open **Settings → Extensions → Advanced settings** to install
or inspect it, then restart Claude Desktop. A privately distributed `.mcpb`
must be updated manually when a newer release is published.

## Still blocked

Open an issue with the package version, operating system, MCP client, non-secret
`doctor` output, and sanitized error text. Never attach cookies, passwords,
browser profiles, raw authenticated DOM, messages, or private LinkedIn data.
