# Privacy Policy

Effective date: August 2, 2026

This policy describes how the standalone, open-source LinkedIn MCP Server
processes data when you run it. The project is local software, not a hosted
service. The maintainer does not operate an application backend and does not
receive data from your installation.

## Data the server processes

The server processes only data needed for the typed MCP capability you invoke:

- content visible to your authorized LinkedIn account, such as jobs, profiles,
  companies, posts, invitations, connections, and messages;
- LinkedIn source URLs, capture times, visible evidence, and typed operation
  results;
- the target and exact payload of an account-changing action that you prepare
  and approve;
- local files that you explicitly place under the configured asset directory
  and reference for a post, comment, or message; and
- non-secret configuration and operational metadata needed to run the local
  process.

LinkedIn login happens directly in a Playwright Chromium window. The server
does not request, read, log, or persist your LinkedIn password. Chromium stores
the resulting session cookies and normal browser data in the local persistent
profile.

## How data is used and stored

Data is used only to perform the requested MCP capability, return typed results
and evidence to your MCP client, pace visible-UI navigation, enforce policy,
and verify account-changing actions.

The server has no analytics, advertising, telemetry, database, or external
application-state service. Calls, evidence, continuation state, action drafts,
attempts, and idempotency records remain in process memory. The Chromium
profile and user-managed asset directory are the only locations where the
server intentionally keeps user data across restarts. Your MCP client may
retain tool inputs or results under that client's own settings and privacy
policy.

## Third-party sharing

The server communicates with LinkedIn only through the visible web UI. LinkedIn
receives the same page requests and, for a client-authorized write, the same
content that a user would submit in the web interface. Tool results and
evidence are returned to the MCP client that invoked the server. Local assets
are sent to LinkedIn only when the specifically prepared action that references
them is executed.

The project does not sell personal data or send LinkedIn content, cookies,
credentials, messages, or local assets to the maintainer, advertisers, data
brokers, or an analytics provider. LinkedIn's processing is governed by the
[LinkedIn Privacy Policy](https://www.linkedin.com/legal/privacy-policy), and
your MCP client's processing is governed by that client's policy.

## Retention and deletion

- Process-memory data is discarded when the server process exits and may be
  removed earlier by expiry or bounded-capacity eviction.
- The Chromium profile persists until you sign out and/or delete the configured
  profile directory. `profile reset` archives the old directory as a sibling
  `*.backup-*` path; backups and failed-creation archives persist until you
  remove them. Treat all of these directories as sensitive authentication data.
- Files in the configured asset directory remain until you remove them.
- Playwright browser binaries and ordinary browser cache may persist in their
  configured local cache locations until you remove them.
- Logs are emitted to the environment running the server and contain bounded
  operational metadata, not cookies, passwords, raw attachment contents, or
  full private message bodies. Retention of captured logs is controlled by
  that environment.

Use `linkedin-mcp status` and `linkedin-mcp stop` before deleting local profile
or asset data. The locations are derived from your operating system's per-user
application-data directory and can be overridden with
`LINKEDIN_MCP_BROWSER_PROFILE_PATH` and `LINKEDIN_MCP_ASSET_ROOT_PATH`.

## Your choices

You can revoke the saved LinkedIn session with `linkedin-mcp logout`, delete the
local browser profile and its archives, remove local assets at any time,
restrict surfaces, scopes, or effects, and stop the process to clear its
in-memory state.

## Contact

For privacy questions, open a GitHub issue at
<https://github.com/prakharagarwal-dev/linkedin-mcp-server/issues> or email
<prakharagarwal3031@gmail.com>. Do not include credentials, cookies, browser
profiles, access tokens, private messages, or other sensitive LinkedIn content.
Report security vulnerabilities through the repository's private
[security-advisory process](SECURITY.md).
