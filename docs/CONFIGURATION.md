# Configuration

`Settings` in `linkedin_mcp/config.py` is the only configuration object. It
loads environment variables with the `LINKEDIN_MCP_` prefix. A source checkout
may also use an uncommitted `.env` based on [`.env.example`](../.env.example).

## Tool authorization

The server registers every implemented typed capability. It does not maintain
capability scopes, effect allowlists, previews, idempotency records, or its own
approval database. The MCP client decides which tools are available and
whether an account-changing call requires confirmation.

Read tools are annotated read-only. These account-changing tools are annotated
destructive:

- `linkedin.posts.create`
- `linkedin.posts.comment`
- `linkedin.posts.react`
- `linkedin.invitations.send`
- `linkedin.invitations.accept`
- `linkedin.invitations.ignore`
- `linkedin.messaging.send`

Annotations are client hints, not a second server-side authorization layer.
Configure unattended approval only for the exact tools you intend to permit.

## Settings reference

| Variable after `LINKEDIN_MCP_` | Default | Purpose |
| --- | --- | --- |
| `ACCOUNT_ID` | `personal` | Logical name for the configured LinkedIn account |
| `BROWSER_PROFILE_PATH` | per-user application data | Persistent Chromium profile containing LinkedIn login state |
| `BROWSER_CACHE_PATH` | native Playwright cache | Managed Playwright browser binaries |
| `BROWSER_AUTO_INSTALL` | `true` | Install the matching Chromium revision when needed |
| `BROWSER_INSTALL_TIMEOUT_SECONDS` | `600` | Browser installation time bound |
| `ALLOWED_HOSTS` | exact LinkedIn hosts | Navigation hostname allowlist |
| `BROWSER_ACTION_DELAY_SECONDS` | `2` | Delay immediately before paced Playwright actions |
| `JOB_SEARCH_MAX_PAGES_PER_CALL` | `100` | Job-search traversal safety bound |
| `PEOPLE_SEARCH_MAX_PAGES_PER_CALL` | `100` | People-search traversal safety bound |
| `PROFILE_MAX_DETAIL_PAGES_PER_CALL` | `20` | Member-profile detail-page bound |
| `COMPANY_SEARCH_MAX_PAGES_PER_CALL` | `100` | Company-search traversal safety bound |
| `POST_SEARCH_MAX_PAGES_PER_CALL` | `100` | Post-search traversal safety bound |
| `POST_COMMENTS_MAX_EXPANSION_ROUNDS_PER_CALL` | `20` | Comment-expansion safety bound |
| `INVITATIONS_MAX_SCROLL_ROUNDS_PER_CALL` | `100` | Invitation traversal safety bound |
| `CONNECTIONS_MAX_SCROLL_ROUNDS_PER_CALL` | `100` | Connection traversal safety bound |
| `MESSAGING_MAX_SCROLL_ROUNDS_PER_CALL` | `100` | Inbox/conversation traversal safety bound |
| `PAGINATION_CURSOR_TTL_SECONDS` | `900` | Lifetime of a process-local continuation cursor |
| `PAGINATION_MAX_ACTIVE_CURSORS` | `64` | Maximum live cursor states |
| `PAGINATION_MAX_SEEN_ITEMS_PER_CURSOR` | `5000` | Stable identities retained by one live scan |
| `BROWSER_HEADLESS` | `true` | Normal capability-browsing mode; interactive login remains visible |
| `BROWSER_TIMEOUT_SECONDS` | `20` | Default browser-operation bound |
| `LOGIN_TIMEOUT_SECONDS` | `900` | Human login/checkpoint time bound |
| `HTTP_HOST` | `127.0.0.1` | Streamable HTTP bind host |
| `HTTP_PORT` | `8000` | Streamable HTTP port |
| `LOG_LEVEL` | `INFO` | Server log level |

There is no transport, queue, worker, scheduler, runtime-lock, or host-manager
configuration.

## Browser profile and login

The browser profile is the server's only authentication persistence. It stores
normal Chromium cookies and preferences and must be treated as sensitive. The
server never receives or stores a LinkedIn password.

Initialize and authenticate it before first use:

```bash
uvx --from linkedin-mcp-local linkedin-mcp setup
uvx --from linkedin-mcp-local linkedin-mcp profile create
uvx --from linkedin-mcp-local linkedin-mcp login
```

`setup` is optional when automatic browser installation is enabled.
`profile create` is idempotent. `login` opens a visible browser, waits for the
operator to finish login, MFA, or a checkpoint, and verifies that the session
survives a clean reopen.

Every `serve` startup validates the saved session synchronously. If it has
expired, the server completes the same visible login flow before accepting MCP
requests. Authentication is never a background task racing with tools.

Other lifecycle commands are:

```bash
uvx --from linkedin-mcp-local linkedin-mcp profile status
uvx --from linkedin-mcp-local linkedin-mcp profile reset
uvx --from linkedin-mcp-local linkedin-mcp logout
uvx --from linkedin-mcp-local linkedin-mcp doctor
```

`profile reset` renames the exact profile to a sibling backup and creates a
clean replacement. The backup still contains sensitive browser data.

Keep one server process per browser profile. The application has no background
owner process, runtime lock, `status` command, or `stop` command. Stop the
foreground `serve` process normally before login, logout, or profile changes.

## Streamable HTTP

The server supports Streamable HTTP only:

```bash
uvx --from linkedin-mcp-local linkedin-mcp serve
```

Connect the MCP client to `http://127.0.0.1:8000/mcp`. FastMCP directly owns
the HTTP server and MCP session handling; there is no custom Uvicorn wrapper,
proxy, stdio bridge, or readiness poller.

The endpoint has no application authentication. Keep `HTTP_HOST=127.0.0.1`
unless a trusted network boundary provides equivalent isolation. Setting
`HTTP_HOST=0.0.0.0` exposes the listener on every interface available to the
process and must not be used on an untrusted network.

## File uploads

File-bearing tools pass the client-supplied path to the tool's visible LinkedIn
upload control. The path may be absolute or relative to the server process. No
asset root or filesystem-containment layer is applied, so an authorized client
can upload any file readable by the server's operating-system user. Use only
trusted clients and restrict the process's filesystem permissions.

## Process-local state

Every tool invocation executes freshly. The server stores no call results or
evidence. Only the operation lock, browser status, and bounded continuation
cursors live in memory; a restart clears them. The browser profile and managed
browser cache persist.

## Container image

```bash
docker pull ghcr.io/prakharagarwal-dev/linkedin-mcp-server:latest
docker run --rm \
  --publish 127.0.0.1:8000:8000 \
  --volume linkedin-mcp-data:/data/linkedin-mcp \
  ghcr.io/prakharagarwal-dev/linkedin-mcp-server:latest
```

The image listens on `0.0.0.0:8000` inside its network namespace so the host
can publish it. Bind the published host port to `127.0.0.1` as shown. The image
includes Chromium, runs as UID/GID `10001`, and stores its profile below
`/data/linkedin-mcp`. Mount intended upload directories explicitly, preferably
read-only. A headless container normally cannot complete a new visible login,
so mount an already authenticated profile when necessary.
