# Configuration

LinkedIn MCP Server is configured with environment variables using the
`LINKEDIN_MCP_` prefix. The standard package configuration enables every
currently implemented capability. Actions that change LinkedIn still use the
prepare, client-confirmation, and execute flow described in
[Security](SECURITY.md).

For `uvx` installations, put environment variables in the MCP client's server
entry. A source checkout can also use an uncommitted `.env` file based on
[`.env.example`](../.env.example). Values for surfaces, scopes, and effects are
JSON arrays encoded as strings.

## Authorization model

A capability is enabled only when all four checks pass:

1. the capability is registered by this server version;
2. every required visible LinkedIn surface is allowed;
3. every required named scope is allowed; and
4. its `read`, `prepare`, or `write` effect is allowed.

Client approval annotations do not grant server permissions. Use
`linkedin.capabilities.list` to see which installed tools are enabled and why
another tool is disabled.

## Default capabilities

No permission environment variables are needed for a normal installation. The
defaults cover every currently implemented surface and scope:

```text
surfaces: all currently implemented LinkedIn surfaces
scopes:   all currently implemented capability scopes
effects:  read, prepare, write
```

`linkedin.capabilities.list` therefore reports every installed capability as
enabled. Execute tools remain destructive MCP operations and should always be
confirmed by the user in the MCP client.

## Optional restriction presets

Only add one of these `env` objects when you want to restrict the local server.

### Read-only access

```json
"env": {
  "LINKEDIN_MCP_ALLOWED_SURFACES": "[\"job-search\",\"job-detail\",\"people-search\",\"member-profile\",\"company-search\",\"company-profile\",\"company-about\",\"content-search\",\"post-detail\",\"post-discussion\",\"connections\",\"messaging\"]",
  "LINKEDIN_MCP_ALLOWED_SCOPES": "[\"linkedin.jobs.search\",\"linkedin.jobs.read\",\"linkedin.people.search\",\"linkedin.people.read\",\"linkedin.companies.search\",\"linkedin.companies.read\",\"linkedin.posts.search\",\"linkedin.posts.read\",\"linkedin.posts.comments.read\",\"linkedin.invitations.read\",\"linkedin.connections.read\",\"linkedin.messaging.read\"]",
  "LINKEDIN_MCP_ALLOWED_EFFECTS": "[\"read\"]"
}
```

### Jobs and People only

```json
"env": {
  "LINKEDIN_MCP_ALLOWED_SURFACES": "[\"job-search\",\"job-detail\",\"people-search\",\"member-profile\"]",
  "LINKEDIN_MCP_ALLOWED_SCOPES": "[\"linkedin.jobs.search\",\"linkedin.jobs.read\",\"linkedin.people.search\",\"linkedin.people.read\"]",
  "LINKEDIN_MCP_ALLOWED_EFFECTS": "[\"read\"]"
}
```

You can also create a custom subset. `linkedin.capabilities.list` returns each
capability's exact surface, scope, and effect requirements. The
[capability matrix](CAPABILITY_MATRIX.md) describes the corresponding visible
feature contracts.

## Settings reference

| Variable after `LINKEDIN_MCP_` | Default | Purpose |
| --- | --- | --- |
| `ACCOUNT_ID` | `personal` | Logical name for the one configured LinkedIn account |
| `BROWSER_PROFILE_PATH` | per-user application data | Persistent Chromium profile containing LinkedIn login state |
| `BROWSER_CACHE_PATH` | native Playwright cache | Managed Playwright browser binaries |
| `BROWSER_AUTO_INSTALL` | `true` | Install the matching Chromium revision when needed |
| `BROWSER_INSTALL_TIMEOUT_SECONDS` | `600` | Browser installation time bound |
| `AUTO_LOGIN_ON_START` | `true` | Validate or recover login after MCP initialization |
| `ASSET_ROOT_PATH` | per-user application data | Only local files below this directory may be attached |
| `ALLOWED_HOSTS` | exact LinkedIn hosts | Navigation hostname allowlist |
| `ALLOWED_SURFACES` | all implemented surfaces | Authorized visible LinkedIn UI surfaces |
| `ALLOWED_SCOPES` | all implemented scopes | Authorized named capability scopes |
| `ALLOWED_EFFECTS` | `read`, `prepare`, `write` | Authorized effect classes |
| `QUEUE_CAPACITY` | `100` | Maximum waiting process-local capability calls |
| `MINIMUM_NAVIGATION_INTERVAL_SECONDS` | `2` | Minimum internal delay between navigations |
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
| `ACTION_DRAFT_TTL_SECONDS` | `86400` | Maximum age of an unexecuted in-process draft |
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

Normal first use remains automatic: `serve` installs Chromium when needed,
creates the dedicated profile when missing, opens LinkedIn for login, and then
reuses that same profile on later starts. The MCP handshake remains responsive
while setup and authentication run in the background.

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
health, attached client count, queue depth, and current browser operation.
`stop` sends that exact owner a graceful termination request and waits for lock
release; it never force-kills a process. During clean shutdown the runtime
rejects new and queued calls, lets an active write reach a terminal result,
closes Chromium, and releases the lock.

Profile-changing and LinkedIn authentication commands hold the same account
lock as `serve`, preventing a server from starting halfway through them. Give
separate accounts distinct profile and lock paths.

## Local assets

Posts, comments, and messages never accept an arbitrary desktop path. Place an
attachment below `LINKEDIN_MCP_ASSET_ROOT_PATH` and pass its relative
`asset_ref`. Preparation records the file's media type, size, and SHA-256; the
execute call must reference the same unchanged file.

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
instead of silently inheriting different profiles, permissions, browser
behavior, pacing, or transport settings.

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

Calls, evidence, request replay, action drafts, attempts, idempotency keys,
queue state, and continuation cursors exist only in shared-runtime memory. A
runtime restart clears them; disconnecting one client does not. Request replay,
cursors, and prepared actions belong to the MCP session that created them,
while execution idempotency keys remain account-wide. The persistent browser
profile, managed browser cache, and explicitly selected local assets survive.

After a hard interruption during a write, inspect LinkedIn's visible state
before preparing another action. Never blindly retry an old execute request.
See the [security design](SECURITY.md) for the complete lifecycle.

## Container image

```bash
docker pull ghcr.io/prakharagarwal-dev/linkedin-mcp-server:latest
```

The image includes Chromium, runs as UID/GID `10001`, and stores the browser
profile and assets below `/data/linkedin-mcp`. Mount that directory only when
you intend to persist it. Automatic headed login is disabled in the image, so
create and mount an authenticated profile from an environment that can display
Chromium.
