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
| `RUNTIME_LOCK_PATH` | per-user application data | Single-account process lock file |
| `BROWSER_HEADLESS` | `true` | Capability browsing mode; human login remains headed |
| `BROWSER_TIMEOUT_SECONDS` | `20` | Default browser-operation bound |
| `LOGIN_TIMEOUT_SECONDS` | `900` | Maximum time for human login or checkpoint handling |
| `TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `HTTP_HOST` | `127.0.0.1` | Loopback Streamable HTTP bind host |
| `HTTP_PORT` | `8000` | Loopback Streamable HTTP port |
| `LOG_LEVEL` | `INFO` | Server log level |

Callers control typed `page_size` and opaque cursors. Browser traversal,
collection reconciliation, and pacing remain server-controlled safety policy.

## Browser profile and login

The browser profile is the server's only authentication persistence. It stores
normal Chromium cookies and preferences and must be treated as sensitive. The
server does not receive or store a LinkedIn password.

```bash
uvx --from linkedin-mcp-local linkedin-mcp setup
uvx --from linkedin-mcp-local linkedin-mcp login
uvx --from linkedin-mcp-local linkedin-mcp doctor
```

`login` opens a headed browser, waits for the operator to complete login, MFA,
or a checkpoint, closes Chromium normally, and verifies that the same profile
survives a clean restart. Later headed or headless server starts reuse it.

One account lock prevents two server processes from owning the same profile.
Give separate accounts distinct profile and lock paths.

## Local assets

Posts, comments, and messages never accept an arbitrary desktop path. Place an
attachment below `LINKEDIN_MCP_ASSET_ROOT_PATH` and pass its relative
`asset_ref`. Preparation records the file's media type, size, and SHA-256; the
execute call must reference the same unchanged file.

## Transports

### Stdio

Use stdio for one local MCP client:

```bash
uvx --from linkedin-mcp-local linkedin-mcp serve --transport stdio
```

The MCP client owns the process lifecycle. The server must keep stdout reserved
for MCP protocol messages.

### Loopback Streamable HTTP

Use one shared local process when several clients need the same worker, browser
profile, and pacing state:

```bash
uvx --from linkedin-mcp-local linkedin-mcp serve --transport streamable-http
```

The default endpoint is `http://127.0.0.1:8000/mcp`. Non-loopback binds are
rejected because the server does not implement HTTP authentication.

## Process-local state

Calls, evidence, request replay, action drafts, attempts, idempotency keys,
queue state, and continuation cursors exist only in memory. A restart clears
them. The persistent browser profile, managed browser cache, and explicitly
selected local assets survive.

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
