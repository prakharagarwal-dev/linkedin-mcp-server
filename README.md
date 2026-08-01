# LinkedIn MCP Server

<!-- mcp-name: io.github.prakharagarwal-dev/linkedin-mcp-server -->

[![CI](https://github.com/prakharagarwal-dev/linkedin-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/prakharagarwal-dev/linkedin-mcp-server/actions/workflows/ci.yml)
[![CodeQL](https://github.com/prakharagarwal-dev/linkedin-mcp-server/actions/workflows/codeql.yml/badge.svg)](https://github.com/prakharagarwal-dev/linkedin-mcp-server/actions/workflows/codeql.yml)
[![PyPI](https://img.shields.io/pypi/v/linkedin-mcp-local.svg)](https://pypi.org/project/linkedin-mcp-local/)
[![Python 3.12–3.13](https://img.shields.io/badge/Python-3.12%E2%80%933.13-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

A standalone Python MCP server that exposes narrow, typed LinkedIn capabilities
through the visible LinkedIn web UI.

> [!IMPORTANT]
> This is an unofficial, beta project. It is not affiliated with, endorsed by,
> or sponsored by LinkedIn. LinkedIn is a trademark of LinkedIn Corporation.
> Visible-UI automation can stop working when LinkedIn changes its interface and
> may cause checkpoints, restrictions, or other account consequences. You are
> responsible for complying with applicable terms, laws, consent requirements,
> and organizational policies. Do not use this project for spam, deceptive
> activity, high-volume extraction, or bypassing access controls.

This repository is the LinkedIn harness, not an agent runtime. LangGraph,
schedulers, ranking, memory, and natural-language planning belong in clients
that call this server. Agents never receive cookies, arbitrary browser control,
generic navigation, JavaScript execution, or unrestricted network access.

Version `0.14.1` has no database, migration, Docker-service, keyring, or
application-state dependency. It uses one local Playwright Chromium profile to
preserve the LinkedIn login and keeps capability execution state only for the
lifetime of one server process.

## Runtime model

```text
LangGraph / Codex / another MCP client
                  |
          stdio or loopback HTTP
                  |
          typed MCP capabilities
                  |
      bounded asyncio.Queue (one worker)
                  |
     policy -> executor -> page objects
                  |
    one persistent Playwright context
                  |
       visible linkedin.com surfaces
```

The server owns:

- official MCP Python SDK transport and typed Pydantic contracts;
- one bounded in-process queue and one capability worker;
- one account-scoped persistent Playwright Chromium context;
- internal navigation pacing and per-operation safety bounds;
- exact-host, surface, scope, and effect authorization;
- visible page extraction and field-level evidence;
- expiring, filter-bound continuation cursors for collection reads;
- immutable prepare/confirm/execute envelopes for writes;
- process-local request replay, evidence, action drafts, and idempotency.

It has no dependency on LangGraph, Temporal, `startup-scanner`, PostgreSQL,
RabbitMQ, Redis, or another LinkedIn MCP implementation.

## What survives a restart

| Data | Location | Lifetime |
| --- | --- | --- |
| LinkedIn cookies and browser preferences | local Chromium profile | across restarts |
| Managed Chromium binaries | local Playwright browser cache | across package environments |
| Explicit post/message assets | configured local asset directory | user managed |
| Calls and request replay | memory | current process only |
| Evidence resources | memory | current process only |
| Action drafts and attempts | memory | current process only |
| Execution idempotency keys | memory | current process only |
| Queue and pacing history | memory | current process only |
| Collection cursors, seen identities, and invitation snapshots | memory | current process only |

The browser profile is sensitive authentication material. Its directory is
created with owner-only permissions on supported POSIX systems. Never commit,
copy, log, or share it.

Because operation state is intentionally ephemeral:

- read retries deduplicate only while the same server process is alive;
- `linkedin://sources/{source_id}` must be read before that process exits;
- a prepare and its matching execute call must use the same process;
- after a hard process interruption during a write, inspect LinkedIn's visible
  state before preparing any new action. Never blindly retry the old execute
  request.

LangGraph should checkpoint workflow history, cross-run deduplication,
notifications, rankings, and conversations outside this server.

## MCP surface

| MCP primitive | Purpose |
| --- | --- |
| `linkedin.server.status` | Non-secret runtime metadata |
| `linkedin.capabilities.list` | Installed capabilities and policy status |
| `linkedin.session.status` | Browser setup, profile, authentication, and pause state |
| `linkedin.jobs.search` | Cursor-paged current Jobs search with optional keywords, Any time by default, and every current account-visible filter |
| `linkedin.jobs.get` | Expanded JD, header metadata, application method, and hiring team for a numeric job ID |
| `linkedin.people.search` | Bounded People search with every current account-visible filter |
| `linkedin.people.get` | Selected or all visible member-profile sections |
| `linkedin.companies.search` | Cursor-paged Company search with keywords and every current native filter: headquarters, industry, all eight size buckets, job listings, and first-degree connection presence |
| `linkedin.companies.get` | Exact Company Overview plus About, including all visible structured About fields and field evidence |
| `linkedin.posts.search` | Post search with every current visible filter, including live videos, followed authors, and Author Keywords |
| `linkedin.posts.get` | Exact post read with fully expanded text, typed current media/link/poll variants, engagement and visibility, field evidence, completeness coverage, and bounded repost-original resolution |
| `linkedin.posts.comments.list` | Top-level comments and nested replies |
| `linkedin.posts.create.prepare` / `.execute` | Nine current personal composer modes: text/link, edited images, video, document, poll, celebration, event, existing-job hiring, and expert request; plus audience/group, comment control, brand partnership, eligible collaborators, and scheduling |
| `linkedin.posts.comment.prepare` / `.execute` | Top-level comment or exact-thread reply with text/emoji/link, exact mentions, one photo, or one exact GIF |
| `linkedin.posts.reaction.prepare` / `.execute` | Set, change, remove, or no-op any current post/comment reaction: Like, Celebrate, Support, Love, Insightful, or Funny |
| `linkedin.invitations.list` | Exact sent view or deduplicated union of every current received invitation view |
| `linkedin.connections.list` | Cursor-page and sort the existing first-degree connection inventory |
| `linkedin.connections.search` | Search established first-degree connections with first-degree enforced by the server |
| `linkedin.invitations.send.prepare` / `.execute` | Connection invitation with optional note |
| `linkedin.invitations.accept.prepare` / `.execute` | Accept an exact received invitation |
| `linkedin.invitations.ignore.prepare` / `.execute` | Ignore an exact received connection request |
| `linkedin.messaging.search` | Cursor-paged recipient/message-keyword search across Focused, Other, Archived, or Spam with exactly one optional Jobs, Unread, Connections, InMail, or Starred filter |
| `linkedin.messaging.conversation.get` | Bounded reverse-virtualized one-to-one history with incoming/outgoing messages, visible attachments, replies, edits, reactions, and explicit completeness |
| `linkedin.messaging.message.prepare` / `.execute` | Exact-recipient text/emoji, current desktop image/file, exact KLIPY GIF, or exact-message reply with hash-locked confirmation and visible postconditions |
| `linkedin://sources/{source_id}` | Evidence captured by the current process |

Every operation accepts a caller-owned `context_id` and `request_id`. Direct
detail reads do not require a prior search. The server constructs bounded,
canonical LinkedIn targets from validated job IDs, profile slugs, company
slugs, post references, comment references, and conversation references.

### Collection pagination

Every LinkedIn search or list tool accepts `page_size` (1–100) and an optional
opaque `cursor`. Omit `cursor` for the first page, then copy
`pagination.next_cursor` into the next call with a new `request_id`. A terminal
page has `pagination.has_more=false`.

Cursors are process-local, single-use, expire after 15 minutes by default, and
are bound to the account, capability, and semantic filters that created them.
Changing `page_size` between pages is allowed; changing the search target,
query, sort, direction, or filters is rejected as `invalid_cursor`. The server
rescans a bounded live prefix and removes stable identities already returned,
so `consistency=live_deduplicated` prevents duplicates but does not claim a
frozen LinkedIn snapshot. `truncated=true` means an internal safety or cursor
state bound ended the scan and no further cursor is issued.

`linkedin.invitations.list` uses a stronger contract. A single-filter call
captures and exactly reconciles that view against LinkedIn's visible count.
Received `all` is server-defined because the latest UI has no reliable All
control: it reconciles Focused, Other, Verified, Mutual Connections, Your
Company, and Your School separately, then deduplicates their stable invitation
identities. Coverage reports the per-view counts, their membership sum, the
overlap removed, and the exact unique snapshot count. Continuations slice that
immutable process-local snapshot without reopening LinkedIn and report
`consistency=captured_snapshot`. A quiet list, physical bottom, loader state,
or end message can never substitute for count reconciliation.

For asynchronously rendered feeds, the server compares raw visible card
identities independently of parsing. A quiet polling window is not treated as
the end of a list. Completion requires either an explicit visible empty/end
state or, for LinkedIn member lists, three unchanged probes at the physical
bottom of the visible scroll container with no loader or tail control. When
LinkedIn exposes an exact count for another selected member collection, such
as `N connections`, neither an early end message nor a stable bottom is
accepted until that visible inventory has rendered. Invitation recommendations
are excluded from the invitation snapshot and reported separately. Exhaustion
of a private traversal bound returns an honest truncated result.

The paginated tools are Jobs, People, Company, post, broad Connections, and
message search; post comments; and invitation and first-degree connection
lists. Exact single-resource reads remain non-cursor
operations. Company-authored posts use `linkedin.posts.search` with
`author_company_*` filters; company employees use `linkedin.people.search`
with `current_company_*` filters.
For transition compatibility, compatible non-v2 collection tools still accept
the older `max_results` or `max_comments` aliases for `page_size`.

See [the visible-feature matrix](docs/CAPABILITY_MATRIX.md) for exact filters,
selectors, payloads, exclusions, capability versions, and visible
postconditions.

## Package and local setup

Prerequisites are Python 3.12 or 3.13 and
[`uv`](https://docs.astral.sh/uv/). Docker is not required.

Run the published PyPI package without a permanent installation:

```bash
uvx --from linkedin-mcp-local linkedin-mcp doctor
uvx --from linkedin-mcp-local linkedin-mcp setup
```

Clone and validate a source checkout:

```bash
git clone https://github.com/prakharagarwal-dev/linkedin-mcp-server.git
cd linkedin-mcp-server
uv sync --frozen --all-groups
uv run linkedin-mcp doctor
```

Chromium installs automatically into the per-user application-data cache when
live access is first enabled. To install it explicitly:

```bash
uv run linkedin-mcp setup
```

The project builds as a normal wheel:

```bash
uv build
uvx --from ./dist/linkedin_mcp_local-0.14.1-py3-none-any.whl \
  linkedin-mcp doctor
```

The wheel does not contain Chromium or a LinkedIn session. On first use, the
installed CLI downloads the matching official Playwright Chromium revision to
the shared user cache. A later wheel or `uvx` environment reuses that cache.

## First LinkedIn login

Enable live access:

```dotenv
LINKEDIN_MCP_LIVE_ENABLED=true
```

Then either start the MCP server or run login explicitly:

```bash
LINKEDIN_MCP_LIVE_ENABLED=true uv run linkedin-mcp login
```

The login command:

1. ensures the matching official Playwright Chromium revision is installed;
2. opens a headed browser with the persistent LinkedIn MCP profile;
3. selects LinkedIn's visible **Keep me signed in** control when available;
4. waits for the user to complete LinkedIn login, MFA, or a checkpoint;
5. requires a persistent LinkedIn session cookie and departure from login
   surfaces;
6. closes Chromium normally, then reopens the exact profile in the configured
   headed or headless mode; and
7. verifies the authenticated LinkedIn feed before reporting success.

The server never asks for or stores a LinkedIn password itself. Later starts
reuse and validate the same profile. Expired authentication can open the same
human login flow. Restriction-shaped pages pause work for operator attention.

With `LIVE_ENABLED=true` and `AUTO_LOGIN_ON_START=true`, Chromium setup and
login run in background tasks, so the MCP handshake itself does not wait for a
download or human interaction.

## Run as an MCP server

For a local client, stdio is the smallest transport:

```bash
uv run linkedin-mcp serve --transport stdio
```

For several local clients sharing one worker, browser, profile, and pacing
state:

```bash
uv run linkedin-mcp serve --transport streamable-http
```

The HTTP endpoint is `http://127.0.0.1:8000/mcp` by default. Non-loopback binds
are rejected because this release does not implement HTTP authentication.

One account lock prevents two server processes from concurrently owning the
same configured runtime lock. Use one shared Streamable HTTP process if
multiple local agents need simultaneous access.

### Codex configuration

Use the published package from any repository:

```toml
[mcp_servers.linkedin]
command = "uvx"
args = [
  "--from",
  "linkedin-mcp-local==0.14.1",
  "linkedin-mcp",
  "serve",
  "--transport",
  "stdio",
]
env = { LINKEDIN_MCP_LIVE_ENABLED = "true" }
startup_timeout_sec = 30
tool_timeout_sec = 900
```

For contributors, this source-checkout configuration does not depend on an
activated virtual environment:

```toml
[mcp_servers.linkedin]
command = "uv"
args = [
  "run",
  "--project",
  "/absolute/path/to/linkedin-mcp-server",
  "linkedin-mcp",
  "serve",
  "--transport",
  "stdio",
]
env = { LINKEDIN_MCP_LIVE_ENABLED = "true" }
startup_timeout_sec = 30
tool_timeout_sec = 900
```

An installed-wheel configuration can point `command` directly at the installed
`linkedin-mcp` executable. Both forms reuse the same default browser profile
and browser cache for the operating-system user.

## Account-changing actions

Writes are separate from reads and use:

```text
prepare visible target and payload
  -> action_id + payload_hash + exact approval_preview
  -> MCP client displays native destructive-tool confirmation
  -> execute validates the unchanged in-memory draft
  -> browser performs one final action
  -> visible postcondition is verified | failed | uncertain
```

Prepare tools do not change LinkedIn. Execute tools are marked destructive and
require the exact `action_id`, SHA-256 `payload_hash`, `approval_preview`, and a
new execution `idempotency_key`. An annotation asks the MCP client to confirm;
it does not grant a server scope or bypass runtime authorization.

Connection invite preparation opens and validates LinkedIn's current
confirmation dialog, including the visible `0/200` personalized-note counter,
without invoking Send. Accept and ignore preparation resolve the exact member
profile and require the current, paired `Accept … request to connect` and
`Ignore … request to connect` controls. Their execute tools re-open that same
profile immediately before the click and verify the terminal state on a fresh
exact-profile read.

Enable only the required surfaces, scopes, and effects. A trusted MCP client
must prompt the user for each execute tool. If the user denies the client
prompt, the client must not call the server.

An execute call is never automatically retried after an `uncertain` result.
With this database-free design, a hard process exit also erases the attempt
record; visible LinkedIn state must be inspected before any follow-up.

## Configuration

All environment settings use the `LINKEDIN_MCP_` prefix.

| Variable | Default | Meaning |
| --- | --- | --- |
| `ACCOUNT_ID` | `personal` | One configured LinkedIn account |
| `LIVE_ENABLED` | `false` | Master switch for LinkedIn browser access |
| `BROWSER_PROFILE_PATH` | per-user app data | Persistent LinkedIn Chromium profile |
| `BROWSER_CACHE_PATH` | native Playwright cache | Managed Playwright browser cache |
| `BROWSER_AUTO_INSTALL` | `true` | Install the matching Chromium revision when needed |
| `BROWSER_INSTALL_TIMEOUT_SECONDS` | `600` | Browser installation bound |
| `AUTO_LOGIN_ON_START` | `true` | Validate/recover login in the background |
| `ALLOWED_HOSTS` | exact LinkedIn hosts | Navigation allowlist |
| `ALLOWED_SURFACES` | Jobs and People reads | Authorized LinkedIn UI surfaces |
| `ALLOWED_SCOPES` | Jobs and People reads | Authorized named capabilities |
| `ALLOWED_EFFECTS` | `read` | `read`, `prepare`, and/or `write` |
| `QUEUE_CAPACITY` | `100` | Maximum waiting local capability calls |
| `MINIMUM_NAVIGATION_INTERVAL_SECONDS` | `2` | Internal pacing interval |
| `PAGINATION_CURSOR_TTL_SECONDS` | `900` | Lifetime of an idle continuation cursor |
| `PAGINATION_MAX_ACTIVE_CURSORS` | `64` | Maximum process-local continuation states |
| `PAGINATION_MAX_SEEN_ITEMS_PER_CURSOR` | `5000` | Stable-identity memory bound per scan |
| `ACTION_DRAFT_TTL_SECONDS` | `86400` | Maximum in-process unexecuted draft age |
| `ASSET_ROOT_PATH` | per-user app data | Allowed local files for posts/comments/messages |
| `RUNTIME_LOCK_PATH` | per-user app data | Single-account process lock |
| `BROWSER_HEADLESS` | `true` | Capability browser mode; login remains headed |
| `BROWSER_TIMEOUT_SECONDS` | `20` | Browser operation timeout |
| `LOGIN_TIMEOUT_SECONDS` | `900` | Human login bound |
| `TRANSPORT` | `stdio` | `stdio` or `streamable-http` |
| `HTTP_HOST` / `HTTP_PORT` | `127.0.0.1:8000` | Loopback HTTP listener |

Page and scroll traversal, member-profile section, comment-expansion,
invitation, connection, and messaging safety bounds remain private server
configuration. Callers control only the typed `page_size` and opaque `cursor`,
not browser traversal or pacing. See [.env.example](.env.example) for every
variable and read-only defaults.

## Container image

Pull the signed multi-architecture image, or build it locally. It has no
companion database:

```bash
docker pull ghcr.io/prakharagarwal-dev/linkedin-mcp-server:0.14.1
docker build -t linkedin-mcp-server:0.14.1 .
```

It runs as UID/GID `10001`, includes Chromium, defaults to stdio, and stores the
persistent browser profile and user assets under `/data/linkedin-mcp`. Mount
that directory intentionally. Automatic headed login is disabled in the image;
create and mount a profile through an environment that can display Chromium.

## Verification

The default suite is the complete `mock_verified` acceptance gate. It blocks
external network access and never contacts LinkedIn:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv run pytest --cov=linkedin_mcp --cov-branch
uv build
```

The enforced branch-coverage floor is 85%; the public-release gate passes 434
offline tests at 85.24%, with the executor, in-process operation store,
capability registry, and MCP protocol layer at 96–98%. The repository contains
no live LinkedIn tests.

## Safety boundary

There is no generic click, selector, navigation, JavaScript, browser, SQL, or
network tool. The server uses only visible LinkedIn UI through official
Playwright APIs and exact configured hosts.

Live access pauses on authentication expiry, authwalls, checkpoints,
restriction-shaped pages, permission failures, and invalid configuration. The
project does not implement CAPTCHA bypass, proxy rotation, fingerprint
spoofing, credential harvesting, stealth plugins, or private LinkedIn
endpoints.

Company/Page publishing, auto-apply, referral semantics, groups, paid InMail,
and other materially different effects require separate future typed
contracts. Operators are responsible for using the server only with accounts
and activity they are authorized to operate.

See [Architecture](docs/ARCHITECTURE.md),
[security design](docs/SECURITY.md),
[testing and mock verification](docs/TESTING.md),
[visible-feature matrix](docs/CAPABILITY_MATRIX.md),
[publishing and package identifiers](docs/PUBLISHING.md),
[contributing guide](CONTRIBUTING.md),
[security policy](SECURITY.md), and
[changelog](CHANGELOG.md).
