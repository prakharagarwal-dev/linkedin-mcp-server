# Configuration

LinkedIn MCP Server is configured with environment variables using the
`LINKEDIN_MCP_` prefix. The package registers every currently implemented
typed capability. Actions that change LinkedIn are single-call tools; the MCP
client decides which tools are exposed and whether a destructive call requires
confirmation.

For `uvx` installations, put environment variables in the MCP client's server
entry. A source checkout can also use an uncommitted `.env` file based on
[`.env.example`](../.env.example).

## Tool availability

The server does not maintain capability scopes, effect allowlists, or per-tool
authorization records. MCP clients discover the complete installed tool set,
input schemas, descriptions, and read/write annotations through the standard
MCP `tools/list` request.

Enable, disable, or restrict tools in the MCP client. If a client makes a tool
available and invokes it, the server treats that invocation as authorized for
the configured LinkedIn account. The server still validates typed input,
canonical targets, LinkedIn authentication, exact visible preconditions,
capability-specific upload controls, bounded execution, and visible postconditions.

## Client tool policy

Read tools are annotated read-only. The seven account-changing tools are
annotated destructive:

- `linkedin.posts.create`
- `linkedin.posts.comment`
- `linkedin.posts.react`
- `linkedin.invitations.send`
- `linkedin.invitations.accept`
- `linkedin.invitations.ignore`
- `linkedin.messaging.send`

Tool annotations are hints to the client, not a server-side approval protocol.
The client's durable configuration decides whether to prompt, reject, or
pre-approve a tool. Chat text does not change that configuration.

Codex installations can make the default explicit:

```toml
[mcp_servers."linkedin-mcp"]
default_tools_approval_mode = "auto"
```

Codex accepts these server-wide or per-tool modes:

| Mode | Behavior |
| --- | --- |
| `auto` | Use each tool's annotations; this is the recommended default. |
| `prompt` | Ask before every configured tool call. |
| `writes` | Ask for tools not marked read-only. |
| `approve` | Treat the configured server or exact tool as pre-approved. |

For an unattended recurring publisher, pre-approve only the direct post tool:

```toml
[mcp_servers."linkedin-mcp".tools."linkedin.posts.create"]
approval_mode = "approve"
```

Do not approve the whole server unless every available action is intentionally
authorized for unattended use. Other MCP clients expose equivalent controls
through their own tool-permission interface.

## Settings reference

| Variable after `LINKEDIN_MCP_` | Default | Purpose |
| --- | --- | --- |
| `ACCOUNT_ID` | `personal` | Logical name for the one configured LinkedIn account |
| `BROWSER_PROFILE_PATH` | per-user application data | Persistent Chromium profile containing LinkedIn login state |
| `BROWSER_CACHE_PATH` | native Playwright cache | Managed Playwright browser binaries |
| `BROWSER_AUTO_INSTALL` | `true` | Install the matching Chromium revision when needed |
| `BROWSER_INSTALL_TIMEOUT_SECONDS` | `600` | Browser installation time bound |
| `ALLOWED_HOSTS` | exact LinkedIn hosts | Navigation hostname allowlist |
| `QUEUE_CAPACITY` | `100` | Maximum waiting process-local capability calls |
| `BROWSER_ACTION_DELAY_SECONDS` | `2` | Fixed delay before paced Playwright actions |
| `JOB_SEARCH_MAX_PAGES_PER_CALL` | `100` | Private job-search traversal safety bound |
| `PEOPLE_SEARCH_MAX_PAGES_PER_CALL` | `100` | Private people-search traversal safety bound |
| `PROFILE_MAX_DETAIL_PAGES_PER_CALL` | `20` | Private member-profile detail-page bound |
| `COMPANY_SEARCH_MAX_PAGES_PER_CALL` | `100` | Private company-search traversal safety bound |
| `POST_SEARCH_MAX_PAGES_PER_CALL` | `100` | Private post-search traversal safety bound |
| `POST_COMMENTS_MAX_EXPANSION_ROUNDS_PER_CALL` | `20` | Private comment-expansion safety bound |
| `INVITATIONS_MAX_SCROLL_ROUNDS_PER_CALL` | `100` | Private invitation traversal safety bound |
| `CONNECTIONS_MAX_SCROLL_ROUNDS_PER_CALL` | `100` | Private connection traversal safety bound |
| `MESSAGING_MAX_SCROLL_ROUNDS_PER_CALL` | `100` | Private inbox/conversation traversal safety bound |
| `PAGINATION_CURSOR_TTL_SECONDS` | `900` | Idle lifetime of a process-local continuation cursor |
| `PAGINATION_MAX_ACTIVE_CURSORS` | `64` | Maximum active cursor states |
| `PAGINATION_MAX_SEEN_ITEMS_PER_CURSOR` | `5000` | Stable identities retained by one live scan |
| `RUNTIME_LOCK_PATH` | per-user application data | Shared-runtime election and owner metadata file |
| `RUNTIME_START_TIMEOUT_SECONDS` | `30` | Maximum wait for the elected shared runtime to become healthy |
| `BROWSER_HEADLESS` | `true` | Capability browsing mode; human login remains headed |
| `BROWSER_TIMEOUT_SECONDS` | `20` | Default browser-operation bound |
| `LOGIN_TIMEOUT_SECONDS` | `900` | Maximum time for human login or checkpoint handling |
| `TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `HTTP_HOST` | `127.0.0.1` | Loopback Streamable HTTP bind host |
| `HTTP_PORT` | `8000` | Loopback Streamable HTTP port |
| `LOG_LEVEL` | `INFO` | Server log level |

Callers control typed `page_size` and opaque cursors. Browser traversal,
collection reconciliation, and pacing remain server-controlled safety policy.

## Browser profile and LinkedIn session

The browser profile is the server's only authentication persistence. It stores
normal Chromium cookies and preferences and must be treated as sensitive. The
server does not receive or store a LinkedIn password.

Before first use, run `profile create`; running `login` explicitly is
recommended because it proves persistence through a clean reopen. `setup` may
be run first to preinstall Chromium, otherwise `serve` installs it synchronously
when automatic browser installation is enabled.

At every start, the host opens the persistent context and validates the saved
session. When authentication is missing or expired, it closes that context,
opens the visible headed login flow, waits for the operator, reopens the
configured headed or headless context, and validates it again. Only then does
it start the task scheduler and publish the MCP endpoint. Authentication is
therefore awaited startup work, never a background task racing with tools. A
checkpoint or restriction fails startup for operator attention.

The explicit lifecycle commands are:

```bash
uvx --from linkedin-mcp-local linkedin-mcp setup
uvx --from linkedin-mcp-local linkedin-mcp profile create
uvx --from linkedin-mcp-local linkedin-mcp profile status
uvx --from linkedin-mcp-local linkedin-mcp profile reset
uvx --from linkedin-mcp-local linkedin-mcp login
uvx --from linkedin-mcp-local linkedin-mcp logout
uvx --from linkedin-mcp-local linkedin-mcp doctor
uvx --from linkedin-mcp-local linkedin-mcp status
uvx --from linkedin-mcp-local linkedin-mcp stop
```

`profile create` is idempotent and initializes only the configured dedicated
profile. `login` never creates a profile: it opens LinkedIn in an existing
profile, waits for the operator to complete login, MFA, or a checkpoint, closes
Chromium normally, and verifies that the same session survives a clean restart.
`logout` uses LinkedIn's visible **Me → Sign Out** controls and verifies the
signed-out state through another clean restart.

`profile reset` is a recoverable destructive operation. It requires typing
`RESET` in an interactive terminal or passing `--yes`, renames the exact
configured profile to a sibling `*.backup-*` directory, and creates a clean
replacement. If replacement creation fails, the old profile is restored. The
backup still contains sensitive browser data and remains until you delete it.

`profile status`, `status`, and `doctor` expose only non-secret local state and
do not open LinkedIn. `status` identifies the shared runtime and reports its
health, queue depth, and current browser operation. The server does not keep an
application-level registry of MCP clients or sessions.
`stop` sends that exact owner a graceful termination request and waits for lock
release; it never force-kills a process. During clean shutdown the runtime
rejects new and queued calls, lets an active write reach a terminal result,
closes Chromium, and releases the lock.

Profile-changing and LinkedIn authentication commands hold the same account
lock as `serve`, preventing a server from starting halfway through them. Give
separate accounts distinct profile and lock paths.

## File uploads

Post, comment, and message tools accept the client-supplied file path directly.
The path may be absolute or relative to the server process working directory;
there is no configured asset root or server-side filesystem containment check.
The server process must be able to read the path. Each tool selects only its
specific visible LinkedIn upload control, and LinkedIn ultimately accepts or
rejects the file's type and size.

This means an authorized MCP client can ask an upload tool to read any file that
the server's operating-system user can access and transmit it to LinkedIn. Run
the server only for trusted clients, limit the process's filesystem permissions,
and approve file-bearing write calls only when the selected path is intended for
that LinkedIn action.

## Transports

### Stdio

Use the normal stdio command in every local MCP client:

```bash
uvx --from linkedin-mcp-local linkedin-mcp serve --transport stdio
```

Each client starts a lightweight stdio bridge. The first bridge elects and
starts one background runtime on the configured loopback host and port; later
bridges attach to that same runtime. Closing one client closes only its bridge,
so other clients and queued work continue. Use `linkedin-mcp status` and
`linkedin-mcp stop` to inspect or end the shared runtime.

The bridge keeps stdout reserved for MCP protocol messages. All clients that
share an account must use the same effective runtime settings. The lock stores
only a SHA-256 configuration fingerprint, so a later client fails safely
instead of silently inheriting different profiles, browser behavior, pacing,
or transport settings.

### Loopback Streamable HTTP

Start the same shared runtime explicitly when a client connects directly over
Streamable HTTP:

```bash
uvx --from linkedin-mcp-local linkedin-mcp serve --transport streamable-http
```

The default endpoint is `http://127.0.0.1:8000/mcp`. Stdio bridges also use
this endpoint internally. Non-loopback binds are rejected because the server
does not implement HTTP authentication.

## Process-local state

The server does not retain call results or evidence. Every tool invocation is
executed freshly. Queue state, browser status, and continuation cursors exist
only in shared-host memory; a host restart clears them. Cursors are opaque,
single-use, and bound to their account, capability, and semantic filters; they
remain usable after an MCP client reconnects. The persistent browser profile,
and managed browser cache survive. Client-selected upload files remain in their
original locations and are not copied or retained by the server.

After an uncertain or hard-interrupted action, inspect LinkedIn's visible state
before invoking the tool again. Never blindly retry an account-changing call.
See the [security design](SECURITY.md) for the complete lifecycle.

## Container image

```bash
docker pull ghcr.io/prakharagarwal-dev/linkedin-mcp-server:latest
```

The image includes Chromium, runs as UID/GID `10001`, and stores the browser
profile below `/data/linkedin-mcp`. Mount that directory only when you intend to
persist it. A host file path is not automatically visible inside the container;
mount any directory containing intended uploads into the container, preferably
read-only, and pass the resulting container path to the tool. Startup login is
visible and headed, so create and mount an authenticated profile from an
environment that can display Chromium when the container has no display.
