# Troubleshooting

Start with the package's non-secret diagnostics:

```bash
uvx --from linkedin-mcp-local linkedin-mcp setup
uvx --from linkedin-mcp-local linkedin-mcp doctor
uvx --from linkedin-mcp-local linkedin-mcp status
```

`setup` ensures the matching Playwright Chromium revision is installed.
`doctor` reports browser, profile, configuration, and runtime readiness without
exposing cookies or credentials. `status` identifies the exact shared runtime
and reports safe health, client, queue, and active-operation metadata.

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

Stop any server that owns the profile, inspect or create the dedicated profile,
then run the LinkedIn-only login flow:

```bash
uvx --from linkedin-mcp-local linkedin-mcp stop
uvx --from linkedin-mcp-local linkedin-mcp profile status
uvx --from linkedin-mcp-local linkedin-mcp profile create
uvx --from linkedin-mcp-local linkedin-mcp login
```

`stop` is idempotent, and `profile create` does nothing when an initialized
profile already exists. `login` intentionally refuses to create a missing
profile.

Complete login, MFA, or checkpoints only in the opened LinkedIn browser. The
server never needs the password. A successful login is verified through a
clean browser restart before the command exits.

If LinkedIn shows a checkpoint, restriction, or security review, resolve it
manually. The server intentionally pauses and does not bypass those pages.

## A runtime or maintenance command owns the browser profile

Multiple normal MCP clients automatically attach to one shared runtime, so
opening a second client should not produce a profile-lock error. The ownership
lock still prevents a second runtime or a login/profile maintenance command
from opening the same Chromium profile. You do not need to find or kill its PID
manually:

```bash
uvx --from linkedin-mcp-local linkedin-mcp status
uvx --from linkedin-mcp-local linkedin-mcp stop
```

`stop` addresses only the elected process currently holding the configured
lock, asks it to shut down gracefully, and waits for release. It does not use
`SIGKILL`. If the timeout expires, an active bounded LinkedIn write may still
be reaching its terminal verification; run `status` again rather than deleting
the lock.

If a normal client still reports a competing owner, check that every client is
using the same current package version and effective `LINKEDIN_MCP_` runtime
settings. A configuration-fingerprint error identifies this mismatch without
exposing the values. A background startup failure is recorded in `runtime.log`
beside the configured runtime lock.

Do not delete the runtime lock while a server or browser process is still
running.

## The dedicated browser profile is damaged

First stop its owner. Then reset the exact configured profile:

```bash
uvx --from linkedin-mcp-local linkedin-mcp stop
uvx --from linkedin-mcp-local linkedin-mcp profile reset
uvx --from linkedin-mcp-local linkedin-mcp login
```

Reset archives the old directory before creating a replacement and rolls back
if replacement creation fails. The reported `*.backup-*` directory remains
sensitive and is not deleted automatically.

## A tool is installed but disabled

Call `linkedin.capabilities.list` to confirm the installed server version
contains the capability. If it does, enable the exact tool in the MCP client's
tool configuration and restart that client. The server has no separate scope
or effect allowlist.

## A scheduled action stops for confirmation

Account-changing tools are annotated destructive, and
an unattended run cannot answer that prompt. Explicitly pre-approve only the
required tool in the MCP client's durable configuration. For example,
Codex recurring post publishing uses:

```toml
[mcp_servers."linkedin-mcp".tools."linkedin.posts.create"]
approval_mode = "approve"
```

Restart Codex after changing the configuration. Do not use a chat message as a
persistent approval and do not approve the entire server unless all LinkedIn
writes are intentionally unattended. Exact target inspection, attachment hash
rechecks, visible revalidation, and postcondition checks still run.

## A collection stops at a safety bound

Collection tools return pagination and completeness metadata. Continue with
`pagination.next_cursor` when present. A `truncated` or parser-drift result is
an honest incomplete result, not a successful end of the LinkedIn collection.

Cursors are runtime-local, single-use, client-session-bound, and filter-bound.
They expire before reservation, but a valid cursor reserved for a queued call
survives that queue wait. Continue from the same MCP client session; start a
new scan after reconnecting, runtime restart, cursor expiry, or filter change.

## A write result is uncertain

Do not immediately retry. An uncertain result means the server could not prove
the visible postcondition within its bound; it does not prove that LinkedIn
rejected the action. Read the exact profile, conversation, post, or invitation
state first, then invoke the tool again only if that visible state proves the
effect did not occur. Every later invocation is a new action.

## An attachment is rejected

The file must be below `LINKEDIN_MCP_ASSET_ROOT_PATH` and referenced by a
relative `asset_ref`. It must also satisfy the capability's visible media type
and size constraints. Do not pass a raw Downloads/Desktop path to a tool.

The action snapshots and rechecks the current file before upload. If the bytes
change during the operation, correct the file and invoke a new action.

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
