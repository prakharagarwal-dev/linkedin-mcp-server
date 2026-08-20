# LinkedIn MCP Server

<!-- mcp-name: io.github.prakharagarwal-dev/linkedin-mcp-server -->

[![CI](https://github.com/prakharagarwal-dev/linkedin-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/prakharagarwal-dev/linkedin-mcp-server/actions/workflows/ci.yml)
[![CodeQL](https://github.com/prakharagarwal-dev/linkedin-mcp-server/actions/workflows/codeql.yml/badge.svg)](https://github.com/prakharagarwal-dev/linkedin-mcp-server/actions/workflows/codeql.yml)
[![PyPI](https://img.shields.io/pypi/v/linkedin-mcp-local.svg)](https://pypi.org/project/linkedin-mcp-local/)
[![Python 3.12–3.14](https://img.shields.io/badge/Python-3.12%E2%80%933.14-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![MCP Registry](https://img.shields.io/badge/MCP_Registry-listed-5A67D8.svg)](https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.prakharagarwal-dev%2Flinkedin-mcp-server)
[![Glama](https://glama.ai/mcp/servers/prakharagarwal-dev/linkedin-mcp-server/badges/score.svg)](https://glama.ai/mcp/servers/prakharagarwal-dev/linkedin-mcp-server)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/prakharagarwal-dev/linkedin-mcp-server/badge)](https://scorecard.dev/viewer/?uri=github.com/prakharagarwal-dev/linkedin-mcp-server)
[![PyPI provenance](https://img.shields.io/badge/PyPI-provenance_attested-3775A9.svg?logo=pypi&logoColor=white)](https://pypi.org/project/linkedin-mcp-local/#files)
[![Container provenance and SBOM](https://img.shields.io/badge/Container-provenance_%2B_SBOM-2496ED.svg?logo=docker&logoColor=white)](https://github.com/prakharagarwal-dev/linkedin-mcp-server/attestations)

> **Disclaimer:** LinkedIn is a registered trademark of LinkedIn Corporation
> and its affiliates. LinkedIn MCP Server is an independent, unofficial project
> and is not affiliated with, endorsed by, sponsored by, or associated with
> LinkedIn Corporation or its affiliates.

A LinkedIn MCP server to find jobs, search people, research companies, manage
your network, publish and engage with posts, and read or send messages.

## ⚡ Quickstart

### 1. Create the dedicated browser profile

```bash
uvx --from linkedin-mcp-local linkedin-mcp profile create
```

### 2. Connect Claude Code

```bash
claude mcp add --scope user --transport stdio linkedin-mcp -- \
  uvx --from linkedin-mcp-local linkedin-mcp serve --transport stdio
```

### 3. Sign in to LinkedIn

Restart Claude Code. A dedicated browser window opens automatically—sign in to
LinkedIn and complete any required verification.

> [!NOTE]
> Your session is saved locally and reused automatically.

### Supported platforms

The server runs natively on Windows, macOS, and Linux. CI executes the complete
offline suite on Windows, macOS, Linux x86-64, and Linux ARM64. Browser and OS
version requirements follow the official
[Playwright Python system requirements](https://playwright.dev/python/docs/intro#system-requirements).

### 4. Try your first request

```text
Find remote software engineering jobs in India posted on LinkedIn this week.
```

## 🛠️ Tools

> [!TIP]
> **Verified** means the tool passed an end-to-end live compatibility test against LinkedIn's visible web UI on the date shown.

| Area | Function | MCP tool | LinkedIn UI compatibility | What it does |
| --- | --- | --- | --- | --- |
| **Jobs** | Search jobs | `linkedin.jobs.search` | ![LinkedIn UI compatibility][status-linkedin-jobs-search]<br>![Compatibility check date][status-checked-on] | Search by keywords, location, distance, date, workplace, experience, employment type, company, industry, function, title, benefits, Easy Apply, verification, applicant count, network, and other visible filters. |
|  | Read job details | `linkedin.jobs.get` | ![LinkedIn UI compatibility][status-linkedin-jobs-get]<br>![Compatibility check date][status-checked-on] | Read the complete job description, company, application method, and visible hiring team. |
| **People** | Search people | `linkedin.people.search` | ![LinkedIn UI compatibility][status-linkedin-people-search]<br>![Compatibility check date][status-checked-on] | Search by keywords, connection degree, hiring status, location, current or past company, title, school, industry, services, language, connections, and followers. |
|  | Read profiles | `linkedin.people.get` | ![LinkedIn UI compatibility][status-linkedin-people-get]<br>![Compatibility check date][status-checked-on] | Read the complete visible profile or request selected sections such as About, experience, education, skills, projects, certifications, and recommendations. |
| **Companies** | Search companies | `linkedin.companies.search` | ![LinkedIn UI compatibility][status-linkedin-companies-search]<br>![Compatibility check date][status-checked-on] | Search by keywords, headquarters, industry, size, available jobs, and first-degree connections. |
|  | Read company details | `linkedin.companies.get` | ![LinkedIn UI compatibility][status-linkedin-companies-get]<br>![Compatibility check date][status-checked-on] | Read Overview and About information, including website, headquarters, size, type, founding year, and specialties. |
| **Posts** | Search posts | `linkedin.posts.search` | ![LinkedIn UI compatibility][status-linkedin-posts-search]<br>![Compatibility check date][status-checked-on] | Search by keywords, date, content type, author, company, relationship, mentions, author industry, and other visible filters. |
|  | Read posts | `linkedin.posts.get` | ![LinkedIn UI compatibility][status-linkedin-posts-get]<br>![Compatibility check date][status-checked-on] | Read complete content, media, links, mentions, hashtags, reactions, and engagement. |
|  | Read discussions | `linkedin.posts.comments.list` | ![LinkedIn UI compatibility][status-linkedin-posts-comments-list]<br>![Compatibility check date][status-checked-on] | Read paginated comments, replies, attachments, and reactions. |
|  | Publish posts | `linkedin.posts.create` | ![LinkedIn UI compatibility][status-linkedin-posts-create]<br>![Compatibility check date][status-checked-on] | Publish supported personal text, link, image, video, document, poll, celebration, event, hiring, and expert-request posts. |
|  | Comment | `linkedin.posts.comment` | ![LinkedIn UI compatibility][status-linkedin-posts-comment]<br>![Compatibility check date][status-checked-on] | Add text, links, emoji, mentions, photos, or GIFs to posts. |
|  | React | `linkedin.posts.react` | ![LinkedIn UI compatibility][status-linkedin-posts-react]<br>![Compatibility check date][status-checked-on] | Add, change, or remove reactions on posts. |
| **Network** | List connections | `linkedin.connections.list` | ![LinkedIn UI compatibility][status-linkedin-connections-list]<br>![Compatibility check date][status-checked-on] | Browse established first-degree connections with sorting and pagination. |
|  | Search connections | `linkedin.connections.search` | ![LinkedIn UI compatibility][status-linkedin-connections-search]<br>![Compatibility check date][status-checked-on] | Search existing connections using applicable People filters. |
|  | List invitations | `linkedin.invitations.list` | ![LinkedIn UI compatibility][status-linkedin-invitations-list]<br>![Compatibility check date][status-checked-on] | Browse received and sent invitations using LinkedIn's visible filters. |
|  | Send invitations | `linkedin.invitations.send` | ![Not checked][status-not-checked] | Send connection requests with optional notes. |
|  | Accept invitations | `linkedin.invitations.accept` | ![Not checked][status-not-checked] | Accept incoming connection requests. |
|  | Ignore invitations | `linkedin.invitations.ignore` | ![Not checked][status-not-checked] | Ignore incoming connection requests. |
| **Messaging** | Search messages | `linkedin.messaging.search` | ![LinkedIn UI compatibility][status-linkedin-messaging-search]<br>![Compatibility check date][status-checked-on] | Search by recipient or message text using inbox categories and filters. |
|  | Read conversations | `linkedin.messaging.conversation.get` | ![LinkedIn UI compatibility][status-linkedin-messaging-conversation-get]<br>![Compatibility check date][status-checked-on] | Read message history, replies, edits, reactions, and attachments. |
|  | Send messages | `linkedin.messaging.send` | ![LinkedIn UI compatibility][status-linkedin-messaging-send]<br>![Compatibility check date][status-checked-on] | Send or reply in one-to-one conversations with text, links, emoji, files, images, and GIFs. |
| **Server** | Check runtime | `linkedin.server.status` | ![LinkedIn UI compatibility][status-linkedin-server-status]<br>![Compatibility check date][status-checked-on] | Inspect the shared runtime, queue, and active browser operation. |
|  | Check LinkedIn session | `linkedin.session.status` | ![LinkedIn UI compatibility][status-linkedin-session-status]<br>![Compatibility check date][status-checked-on] | Inspect browser-profile, saved-session, and pause state. |

`NOT CHECKED` tools remain covered by the offline simulator on every pull request.

[status-linkedin-jobs-search]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.jobs.search.json&label=
[status-linkedin-jobs-get]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.jobs.get.json&label=
[status-linkedin-people-search]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.people.search.json&label=
[status-linkedin-people-get]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.people.get.json&label=
[status-linkedin-companies-search]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.companies.search.json&label=
[status-linkedin-companies-get]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.companies.get.json&label=
[status-linkedin-posts-search]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.posts.search.json&label=
[status-linkedin-posts-get]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.posts.get.json&label=
[status-linkedin-posts-comments-list]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.posts.comments.list.json&label=
[status-linkedin-posts-create]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.posts.create.json&label=
[status-linkedin-posts-comment]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.posts.comment.json&label=
[status-linkedin-posts-react]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.posts.react.json&label=
[status-linkedin-connections-list]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.connections.list.json&label=
[status-linkedin-connections-search]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.connections.search.json&label=
[status-linkedin-invitations-list]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.invitations.list.json&label=
[status-linkedin-messaging-search]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.messaging.search.json&label=
[status-linkedin-messaging-conversation-get]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.messaging.conversation.get.json&label=
[status-linkedin-messaging-send]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.messaging.send.json&label=
[status-linkedin-server-status]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.server.status.json&label=
[status-linkedin-session-status]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Flinkedin.session.status.json&label=
[status-checked-on]: https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fprakharagarwal-dev%2Flinkedin-mcp-server%2Ftool-status%2Fbadges%2Fchecked-on.json&label=
[status-not-checked]: https://img.shields.io/badge/status-not_checked-lightgrey?label=

See the [capability matrix](docs/CAPABILITY_MATRIX.md) for exact filters,
supported formats, inputs, outputs, limits, and unsupported features.

## 📦 Installation

Before connecting an MCP client for the first time, create the dedicated
profile. Running `login` up front is recommended because it verifies that the
session survives a clean browser restart (`setup` only preinstalls Chromium and
is optional when automatic installation is enabled):

```bash
uvx --from linkedin-mcp-local linkedin-mcp setup
uvx --from linkedin-mcp-local linkedin-mcp profile create
uvx --from linkedin-mcp-local linkedin-mcp login
```

Every server start synchronously validates the saved session before accepting
tools. If login is missing or expired on a local desktop, the host opens the
visible headed login flow, waits for completion, reopens the profile, validates
it again, and only then publishes the MCP endpoint. This is startup work, not a
background task. Container deployments should mount an already authenticated
profile because they normally cannot display that window.

<details open>
<summary>Claude Code</summary>

```bash
claude mcp add --scope user --transport stdio linkedin-mcp -- \
  uvx --from linkedin-mcp-local linkedin-mcp serve --transport stdio
```

Check it with `claude mcp list`. See the
[Claude Code MCP documentation](https://code.claude.com/docs/en/mcp).

</details>

<details>
<summary>Claude Desktop</summary>

[![Download for Claude Desktop](https://img.shields.io/badge/Claude_Desktop-Download_.mcpb-D97757?style=flat-square)](https://github.com/prakharagarwal-dev/linkedin-mcp-server/releases/latest)

Download the `.mcpb` file, then open **Settings → Extensions → Advanced
settings → Install Extension**.
See [Claude Desktop's extension documentation](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop).

</details>

<details>
<summary>Codex and ChatGPT Desktop</summary>

```bash
codex mcp add linkedin-mcp -- \
  uvx --from linkedin-mcp-local linkedin-mcp serve --transport stdio
```

Check it with `codex mcp list`. Codex CLI, the Codex IDE extension, and ChatGPT
Desktop share this local configuration. Restart the client after adding it. See
the [Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp).

</details>

<details>
<summary>VS Code and GitHub Copilot</summary>

[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install_Server-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://insiders.vscode.dev/redirect?url=vscode%3Amcp%2Finstall%3F%257B%2522name%2522%253A%2522linkedin-mcp%2522%252C%2522command%2522%253A%2522uvx%2522%252C%2522args%2522%253A%255B%2522--from%2522%252C%2522linkedin-mcp-local%2522%252C%2522linkedin-mcp%2522%252C%2522serve%2522%252C%2522--transport%2522%252C%2522stdio%2522%255D%257D)
[![Install in VS Code Insiders](https://img.shields.io/badge/VS_Code_Insiders-Install_Server-24bfa5?style=flat-square&logo=visualstudiocode&logoColor=white)](https://insiders.vscode.dev/redirect?url=vscode-insiders%3Amcp%2Finstall%3F%257B%2522name%2522%253A%2522linkedin-mcp%2522%252C%2522command%2522%253A%2522uvx%2522%252C%2522args%2522%253A%255B%2522--from%2522%252C%2522linkedin-mcp-local%2522%252C%2522linkedin-mcp%2522%252C%2522serve%2522%252C%2522--transport%2522%252C%2522stdio%2522%255D%257D)

Or add this to `.vscode/mcp.json`:

```json
{
  "servers": {
    "linkedin-mcp": {
      "command": "uvx",
      "args": ["--from", "linkedin-mcp-local", "linkedin-mcp", "serve", "--transport", "stdio"]
    }
  }
}
```

See the [VS Code MCP documentation](https://code.visualstudio.com/docs/agent-customization/mcp-servers).

</details>

<details>
<summary>Cursor</summary>

[![Install in Cursor](https://cursor.com/deeplink/mcp-install-dark.svg)](https://cursor.com/en/install-mcp?name=LinkedIn%20MCP&config=eyJjb21tYW5kIjoidXZ4IC0tZnJvbSBsaW5rZWRpbi1tY3AtbG9jYWwgbGlua2VkaW4tbWNwIHNlcnZlIC0tdHJhbnNwb3J0IHN0ZGlvIn0%3D)

For manual setup, open **Cursor Settings → MCP →
Add new MCP server**, set the command to `uvx`, and set the arguments to
`--from linkedin-mcp-local linkedin-mcp serve --transport stdio`.
See the [Cursor MCP documentation](https://docs.cursor.com/en/tools/mcp).

</details>

<details>
<summary>Gemini CLI</summary>

In `~/.gemini/settings.json`, add a local server named `linkedin-mcp` under
`mcpServers` with command `uvx` and arguments
`--from linkedin-mcp-local linkedin-mcp serve --transport stdio`, then run
`gemini mcp list`.
See the [Gemini CLI MCP documentation](https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md).

</details>

<details>
<summary>Windsurf</summary>

Open **Settings → AI → Manage MCP Servers**, or add a local server named
`linkedin-mcp` to `~/.codeium/windsurf/mcp_config.json` with command `uvx` and
arguments `--from linkedin-mcp-local linkedin-mcp serve --transport stdio`.
See the [Windsurf MCP documentation](https://docs.windsurf.com/windsurf/cascade/mcp).

</details>

<details>
<summary>Cline</summary>

Open **MCP Servers → Configure**, then add a local server named `linkedin-mcp`
with command `uvx` and arguments
`--from linkedin-mcp-local linkedin-mcp serve --transport stdio`.
See the [Cline MCP documentation](https://docs.cline.bot/mcp/mcp-overview).

</details>

<details>
<summary>Roo Code</summary>

Open Roo Code's MCP settings and add a local server named `linkedin-mcp` to the
global file or `.roo/mcp.json`, using command `uvx` and arguments
`--from linkedin-mcp-local linkedin-mcp serve --transport stdio`.
See the [Roo Code MCP documentation](https://docs.roocode.com/features/mcp/using-mcp-in-roo).

</details>

<details>
<summary>Zed</summary>

Add this to Zed settings:

```json
{
  "context_servers": {
    "linkedin-mcp": {
      "command": "uvx",
      "args": ["--from", "linkedin-mcp-local", "linkedin-mcp", "serve", "--transport", "stdio"]
    }
  }
}
```

See the [Zed MCP documentation](https://zed.dev/docs/ai/mcp).

</details>

<details>
<summary>Goose</summary>

[![Install in Goose](https://block.github.io/goose/img/extension-install-dark.svg)](https://block.github.io/goose/extension?cmd=uvx&arg=--from&arg=linkedin-mcp-local&arg=linkedin-mcp&arg=serve&arg=--transport&arg=stdio&id=linkedin-mcp&name=LinkedIn%20MCP&description=A%20LinkedIn%20MCP%20server%20to%20find%20jobs%2C%20search%20people%2C%20research%20companies%2C%20manage%20your%20network%2C%20publish%20and%20engage%20with%20posts%2C%20and%20read%20or%20send%20messages.)

Or add a custom stdio extension with command `uvx` and arguments
`--from linkedin-mcp-local linkedin-mcp serve --transport stdio`, or start one
CLI session with:

```bash
goose session --with-extension \
  "uvx --from linkedin-mcp-local linkedin-mcp serve --transport stdio"
```

See the [Goose documentation](https://block.github.io/goose/).

</details>

<details>
<summary>OpenCode</summary>

For OpenCode v2, add this to `opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "linkedin-mcp": {
        "type": "local",
        "command": ["uvx", "--from", "linkedin-mcp-local", "linkedin-mcp", "serve", "--transport", "stdio"]
      }
    }
  }
}
```

See the [OpenCode MCP documentation](https://opencode.ai/v2/docs/mcp-servers).

</details>

<details>
<summary>JetBrains AI Assistant</summary>

Open **Settings → Tools → AI Assistant → Model Context Protocol (MCP)**, click
**Add**, set the command to `uvx`, and set the arguments to
`--from linkedin-mcp-local linkedin-mcp serve --transport stdio`.
See the [JetBrains MCP documentation](https://www.jetbrains.com/help/ai-assistant/mcp.html).

</details>

<details>
<summary>Continue</summary>

Create `.continue/mcpServers/linkedin-mcp.json` with a local server named
`linkedin-mcp`, command `uvx`, and arguments
`--from linkedin-mcp-local linkedin-mcp serve --transport stdio`.
See the [Continue MCP documentation](https://docs.continue.dev/customize/deep-dives/mcp).

</details>

<details>
<summary>Warp</summary>

Open **Settings → AI → Manage MCP Servers → Add**, name the server
`linkedin-mcp`, set the command to `uvx`, and set the arguments to
`--from linkedin-mcp-local linkedin-mcp serve --transport stdio`.
See the [Warp MCP documentation](https://docs.warp.dev/agent-platform/capabilities/mcp).

</details>

## 💡 Examples

### Find jobs

```text
Find remote software engineering jobs in India posted on LinkedIn this week with Easy Apply.
```

### Research people

```text
Find LinkedIn profiles for engineering managers at Stripe in India and show me their relevant experience.
```

### Research companies

```text
Find fintech companies in Bengaluru on LinkedIn with 51–200 employees and summarize each company.
```

### Explore posts

```text
Find recent LinkedIn posts about AI agents and summarize the most useful discussions.
```

### Manage your network

```text
Show my latest received connection requests on LinkedIn.
```

```text
Send a LinkedIn connection request to <profile URL> with the note <note>.
```

### Send messages

```text
Send <message> on LinkedIn to <profile URL>.
```

## 🏗️ Architecture

```text
[Claude | Codex | Cursor | ...]
               |
       stdio / loopback HTTP
               v
      [Typed MCP boundary]
               |
               v
        [Task + FIFO queue]
               |
      one operation at a time
               v
[Scheduler -> Worker] ---> [Process-local cursors]
               |
               v
 [Tool-owned execution + raw Page/Locator]
               |
               v
 [infra.playwright.Paced actions]
               |
               v
[BrowserManager: pages + one context] <--> [Persistent auth profile]
               |
        visible web UI only
               v
           [LinkedIn]
```

Everything runs locally. There is no hosted backend, telemetry, database,
external queue, LangGraph runtime, or credential service. Browser cookies live
only in the local Playwright profile. The first client starts one shared local
runtime; later clients attach to it. A bounded FIFO queue feeds one worker, so
browser calls run one at a time. Calls execute freshly; only queue, browser
status, and cursor coordination live in runtime memory.
Read the full [architecture](docs/ARCHITECTURE.md) and [privacy policy](PRIVACY.md).

## 🔒 Privacy Policy

The server has no maintainer-operated backend, analytics, advertising, or
telemetry. LinkedIn receives normal visible-UI requests, and the invoking MCP
client receives tool results under its own data policy; the project sends
nothing to the maintainer. Read the complete [privacy policy](PRIVACY.md) for
processing, storage, sharing, retention, and deletion details.

## 🛡️ Safety

Use of this software is at your own risk. You are solely responsible for
complying with [LinkedIn's User Agreement](https://www.linkedin.com/legal/user-agreement),
applicable laws, and third-party rights. LinkedIn may limit or restrict accounts
that use [prohibited automation](https://www.linkedin.com/help/linkedin/answer/a1341387/).
The maintainers do not authorize spam, unauthorized data collection, privacy
violations, or circumvention of access controls.

- Use only accounts and activity you are authorized to operate.
- The server pauses on authentication expiry, checkpoints, restriction pages,
  permission failures, and configuration errors.
- It does not implement CAPTCHA bypass, proxy rotation, fingerprint spoofing,
  credential harvesting, stealth plugins, or private LinkedIn endpoints.
- Never commit or share the persistent browser profile. File-bearing tools can
  upload any path readable by the server process, so use trusted MCP clients and
  approve only files intended for LinkedIn.

See [SECURITY.md](SECURITY.md) and [the security design](docs/SECURITY.md).

## 📚 More documentation

- [Configuration](docs/CONFIGURATION.md)
- [Capability matrix](docs/CAPABILITY_MATRIX.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Testing](docs/TESTING.md)
- [Collection verification](docs/COLLECTION_VERIFICATION_PROCESS.md)
- [Distribution and registry coverage](docs/DISTRIBUTION.md)
- [Publishing](docs/PUBLISHING.md)
- [Changelog](CHANGELOG.md)

## ❤️ Support the project

If LinkedIn MCP Server is useful to you:

- [Star the repository](https://github.com/prakharagarwal-dev/linkedin-mcp-server)
- [Sponsor continued development](https://github.com/sponsors/prakharagarwal-dev)

## 🌐 Let's connect

Have feedback or an idea for LinkedIn MCP Server?

- [Connect with me on LinkedIn](https://www.linkedin.com/in/prakhar-agarwal-byte/)
- [Follow me on GitHub](https://github.com/prakharagarwal-dev)
- [Report a bug or request a feature](https://github.com/prakharagarwal-dev/linkedin-mcp-server/issues)

## ⚖️ License

Licensed under the [Apache License 2.0](LICENSE).
