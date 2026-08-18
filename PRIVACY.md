# Privacy Policy

Effective date: August 14, 2026

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
- the target and exact payload of an account-changing tool you invoke;
- local files whose paths you explicitly provide for a post, comment, or
  message; and
- non-secret configuration and operational metadata needed to run the local
  process.

LinkedIn login happens in a visible Playwright Chromium window, either through
the explicit CLI command or as awaited startup work when the saved session is
missing or expired. The server does not request, read, log, or persist your
LinkedIn password. Chromium stores the resulting session cookies and normal
browser data in the local persistent profile. Tool requests are not accepted
until startup login and clean-reopen validation have finished.

## How data is used and stored

Data is used only to perform the requested MCP capability, return typed results
and evidence to your MCP client, pace visible-UI navigation, enforce the typed
browser boundary, and verify account-changing actions.

The server has no analytics, advertising, telemetry, database, call-result
cache, evidence store, or external application-state service. Tool inputs,
observations, and results are not retained after the invocation completes.
Queue coordination, pacing, and continuation cursors remain temporarily in
process memory. The Chromium profile is the only location where the server
intentionally keeps user data across restarts.
Your MCP client may retain tool inputs or results under that client's own
settings and privacy policy.

## Third-party sharing

The server communicates with LinkedIn only through the visible web UI. LinkedIn
receives the same page requests and, for a client-authorized write, the same
content that a user would submit in the web interface. Tool results and
evidence are returned to the MCP client that invoked the server. Local files
selected by path are sent to LinkedIn only during the exact account-changing
action that references them.

The project does not sell personal data or send LinkedIn content, cookies,
credentials, messages, or local assets to the maintainer, advertisers, data
brokers, or an analytics provider. LinkedIn's processing is governed by the
[LinkedIn Privacy Policy](https://www.linkedin.com/legal/privacy-policy), and
your MCP client's processing is governed by that client's policy.

## Retention and deletion

- Queue coordination is discarded when calls complete. Continuation cursors and
  pacing state are discarded when the server exits and may expire earlier.
- The Chromium profile persists until you sign out and/or delete the configured
  profile directory. `profile reset` archives the old directory as a sibling
  `*.backup-*` path; backups and failed-creation archives persist until you
  remove them. Treat all of these directories as sensitive authentication data.
- Client-selected upload files remain in their original locations under the
  user's control; the server does not copy or retain them.
- Playwright browser binaries and ordinary browser cache may persist in their
  configured local cache locations until you remove them.
- Logs are emitted to the environment running the server and contain bounded
  operational metadata, not cookies, passwords, raw attachment contents, or
  full private message bodies. Retention of captured logs is controlled by
  that environment.

Use `linkedin-mcp status` and `linkedin-mcp stop` before deleting local profile
data. Its location is derived from your operating system's per-user
application-data directory and can be overridden with
`LINKEDIN_MCP_BROWSER_PROFILE_PATH`.

## Your choices

You can revoke the saved LinkedIn session with `linkedin-mcp logout`, delete the
local browser profile and its archives, disable tools in your MCP client, and
stop the process to clear cursors, pacing, and queue state. You control the
original files selected for upload and may remove them independently.

## Contact

For privacy questions, open a GitHub issue at
<https://github.com/prakharagarwal-dev/linkedin-mcp-server/issues> or email
<prakharagarwal3031@gmail.com>. Do not include credentials, cookies, browser
profiles, access tokens, private messages, or other sensitive LinkedIn content.
Report security vulnerabilities through the repository's private
[security-advisory process](SECURITY.md).
