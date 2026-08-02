# LinkedIn MCP Server

<!-- mcp-name: io.github.prakharagarwal-dev/linkedin-mcp-server -->

[![CI](https://github.com/prakharagarwal-dev/linkedin-mcp-server/actions/workflows/ci.yml/badge.svg)](https://github.com/prakharagarwal-dev/linkedin-mcp-server/actions/workflows/ci.yml)
[![CodeQL](https://github.com/prakharagarwal-dev/linkedin-mcp-server/actions/workflows/codeql.yml/badge.svg)](https://github.com/prakharagarwal-dev/linkedin-mcp-server/actions/workflows/codeql.yml)
[![PyPI](https://img.shields.io/pypi/v/linkedin-mcp-local.svg)](https://pypi.org/project/linkedin-mcp-local/)
[![Python 3.12–3.13](https://img.shields.io/badge/Python-3.12%E2%80%933.13-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/prakharagarwal-dev/linkedin-mcp-server?style=social)](https://github.com/prakharagarwal-dev/linkedin-mcp-server/stargazers)

A local MCP server that lets AI assistants search LinkedIn and perform supported
LinkedIn actions through the visible website.

> Like the project? [Star the repository](https://github.com/prakharagarwal-dev/linkedin-mcp-server) to help other MCP users find it.

> If LinkedIn MCP saves you time, [sponsor its continued development](https://github.com/sponsors/prakharagarwal-dev).

> [!IMPORTANT]
> This is an unofficial project and is not affiliated with or endorsed by
> LinkedIn. LinkedIn interface changes can temporarily break features or prompt
> security checkpoints. Use it only with accounts and activity you are
> authorized to operate.

## What you can do

- Search current jobs with LinkedIn's visible filters and read complete job descriptions.
- Search people and companies, then read exact visible profiles and company details.
- Search and read posts, comments, replies, reactions, and media.
- Create personal posts, comment, reply, and react after confirmation.
- List and search connections, and send, accept, or ignore invitations.
- Search messages, read one-to-one conversations, and send text or attachments.
- Use it with Codex, Claude, Cursor, VS Code, Gemini, or any MCP client.

See the [capability matrix](docs/CAPABILITY_MATRIX.md) for every supported
filter, input, output, and visible postcondition.

## Getting started

### Requirements

- macOS, Linux, or Windows
- Python 3.12 or 3.13
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- a local MCP client and a LinkedIn account

Claude Desktop users can use the packaged `.mcpb` extension instead of the
standard `uvx` setup below.

### Standard configuration

This configuration works in most MCP clients:

```json
{
  "mcpServers": {
    "linkedin-mcp": {
      "command": "uvx",
      "args": [
        "--from",
        "linkedin-mcp-local",
        "linkedin-mcp",
        "serve",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

Every current capability is available after installation. Before the server
posts, messages, connects, comments, or reacts, your MCP client should show the
exact action and ask you to confirm. You can optionally restrict capabilities
in [Configuration](docs/CONFIGURATION.md).

### One-click installs

[![Install in VS Code](https://img.shields.io/badge/VS_Code-Install_Server-0098FF?style=flat-square&logo=visualstudiocode&logoColor=white)](https://insiders.vscode.dev/redirect?url=vscode%3Amcp%2Finstall%3F%257B%2522name%2522%253A%2522linkedin-mcp%2522%252C%2522command%2522%253A%2522uvx%2522%252C%2522args%2522%253A%255B%2522--from%2522%252C%2522linkedin-mcp-local%2522%252C%2522linkedin-mcp%2522%252C%2522serve%2522%252C%2522--transport%2522%252C%2522stdio%2522%255D%257D)
[![Install in Cursor](https://cursor.com/deeplink/mcp-install-dark.svg)](https://cursor.com/en/install-mcp?name=LinkedIn%20MCP&config=eyJjb21tYW5kIjoidXZ4IC0tZnJvbSBsaW5rZWRpbi1tY3AtbG9jYWwgbGlua2VkaW4tbWNwIHNlcnZlIC0tdHJhbnNwb3J0IHN0ZGlvIn0%3D)
[![Add to Kiro](https://kiro.dev/images/add-to-kiro.svg)](https://kiro.dev/launch/mcp/add?name=linkedin-mcp&config=%7B%22command%22%3A%22uvx%22%2C%22args%22%3A%5B%22--from%22%2C%22linkedin-mcp-local%22%2C%22linkedin-mcp%22%2C%22serve%22%2C%22--transport%22%2C%22stdio%22%5D%7D)
[![Add to LM Studio](https://files.lmstudio.ai/deeplink/mcp-install-light.svg)](https://lmstudio.ai/install-mcp?name=linkedin-mcp&config=eyJjb21tYW5kIjoidXZ4IiwiYXJncyI6WyItLWZyb20iLCJsaW5rZWRpbi1tY3AtbG9jYWwiLCJsaW5rZWRpbi1tY3AiLCJzZXJ2ZSIsIi0tdHJhbnNwb3J0Iiwic3RkaW8iXX0%3D)
[![Claude Desktop MCPB](https://img.shields.io/badge/Claude_Desktop-Download_.mcpb-D97757?style=flat-square)](https://github.com/prakharagarwal-dev/linkedin-mcp-server/releases/latest)

### Client quick setup

<details>
<summary>Codex and ChatGPT Desktop</summary>

Add this to `~/.codex/config.toml`:

```toml
[mcp_servers."linkedin-mcp"]
command = "uvx"
args = ["--from", "linkedin-mcp-local", "linkedin-mcp", "serve", "--transport", "stdio"]
startup_timeout_sec = 60
tool_timeout_sec = 900
```

Codex CLI, the Codex IDE extension, and ChatGPT Desktop share this local
configuration. Restart the client after saving it. See the
[Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp).

</details>

<details>
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

Download the `.mcpb` file from the
[latest release](https://github.com/prakharagarwal-dev/linkedin-mcp-server/releases/latest),
then open **Settings → Extensions → Advanced settings → Install Extension**.
See [Claude Desktop's extension documentation](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop).

</details>

<details>
<summary>VS Code and GitHub Copilot</summary>

Use the install button above, or add this to `.vscode/mcp.json`:

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

Use the install button above. For manual setup, open **Cursor Settings → MCP →
Add new MCP server** and use the standard configuration.
See the [Cursor MCP documentation](https://docs.cursor.com/en/tools/mcp).

</details>

<details>
<summary>Gemini CLI</summary>

Add the standard configuration under `mcpServers` in
`~/.gemini/settings.json`, then run `gemini mcp list`.
See the [Gemini CLI MCP documentation](https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md).

</details>

<details>
<summary>Windsurf</summary>

Open **Settings → AI → Manage MCP Servers**, or add the standard configuration
to `~/.codeium/windsurf/mcp_config.json`.
See the [Windsurf MCP documentation](https://docs.windsurf.com/windsurf/cascade/mcp).

</details>

<details>
<summary>Cline</summary>

Open **MCP Servers → Configure**, then paste the standard configuration.
See the [Cline MCP documentation](https://docs.cline.bot/mcp/mcp-overview).

</details>

<details>
<summary>Roo Code</summary>

Open Roo Code's MCP settings and paste the standard configuration into the
global file, or save it as `.roo/mcp.json` for one project.
See the [Roo Code MCP documentation](https://docs.roocode.com/features/mcp/using-mcp-in-roo).

</details>

<details>
<summary>Kiro</summary>

Use the install button above, or paste the standard configuration into
`~/.kiro/settings/mcp.json`.
See the [Kiro MCP documentation](https://kiro.dev/docs/mcp/configuration/).

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
<summary>LM Studio</summary>

Use the install button above, or open **Program → Install → Edit mcp.json** and
paste the standard configuration.
See the [LM Studio MCP documentation](https://lmstudio.ai/docs/app/mcp).

</details>

<details>
<summary>Goose</summary>

Add a custom stdio extension with command `uvx` and the arguments from the
standard configuration, or start one CLI session with:

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
**Add**, and paste the standard configuration.
See the [JetBrains MCP documentation](https://www.jetbrains.com/help/ai-assistant/mcp.html).

</details>

<details>
<summary>Continue</summary>

Save the standard configuration as `.continue/mcpServers/linkedin-mcp.json`.
See the [Continue MCP documentation](https://docs.continue.dev/customize/deep-dives/mcp).

</details>

<details>
<summary>Warp</summary>

Open **Settings → AI → Manage MCP Servers → Add** and paste the standard
configuration.
See the [Warp MCP documentation](https://docs.warp.dev/agent-platform/capabilities/mcp).

</details>

<details>
<summary>Any other MCP client</summary>

Configure a local stdio server with:

- command: `uvx`
- arguments: `--from linkedin-mcp-local linkedin-mcp serve --transport stdio`

Do not combine stdio with shell wrappers that print extra text to stdout.

</details>

## First LinkedIn login

1. Save the client configuration and restart the MCP client.
2. On first start, the server installs its managed Chromium build and opens a
   headed LinkedIn window.
3. Complete LinkedIn login, MFA, or any checkpoint yourself. The browser
   profile is then reused across restarts.
4. Ask the client to check your LinkedIn session or try one of the prompts below.

The server never asks for or stores your LinkedIn password. If the automatic
window does not appear, run:

```bash
uvx --from linkedin-mcp-local linkedin-mcp login
uvx --from linkedin-mcp-local linkedin-mcp doctor
```

## Try it

```text
Find software engineering jobs posted this week in Bengaluru.

Find engineering managers working at Stripe in India.

Read the About and Experience sections from this LinkedIn profile: <profile URL>.

Show my received connection invitations without changing anything.
```

For actions that make changes:

```text
Draft a connection invitation to <profile URL> with this note: <note>.

Prepare a LinkedIn message to <profile URL> saying: <message>.
```

The client should show the exact action and ask you to confirm before anything
changes on LinkedIn.

## Capabilities

| Domain | Available tools |
| --- | --- |
| Jobs | Search with current visible filters; read complete job details and JD |
| People | Search with current visible filters; read selected or all profile sections |
| Companies | Search companies; read exact Overview and About information |
| Posts | Search, read, create, comment, reply, and react |
| Network | List/search connections; list, send, accept, and ignore invitations |
| Messaging | Search messages, read conversations, and send text or attachments |

Each tool handles a specific LinkedIn task. The server does not give AI
assistants unrestricted browser, click, navigation, JavaScript, or network
access. See the
[capability matrix](docs/CAPABILITY_MATRIX.md) for the complete contract.

## How it works

```text
Codex / Claude / another MCP client
                  |
            LinkedIn MCP tools
                  |
       one bounded local queue
                  |
      one persistent Playwright browser
                  |
        visible linkedin.com pages
```

Everything runs locally. There is no hosted backend, telemetry, database,
external queue, LangGraph runtime, or credential service. Browser cookies live
only in the local Playwright profile; operation state lives only until the
server process exits. Read the full [architecture](docs/ARCHITECTURE.md) and
[privacy policy](PRIVACY.md).

## Actions that make changes on LinkedIn

Before posting, messaging, connecting, commenting, or reacting, the server:

1. prepares the exact action without making the change;
2. asks the MCP client to show you what will happen;
3. performs the action once after confirmation; and
4. checks the visible LinkedIn result.

Do not configure your MCP client to approve these actions automatically. See
the [security design](docs/SECURITY.md) for implementation details.

## Configuration

Common settings control:

- enabled LinkedIn surfaces, capability scopes, and effect classes;
- the persistent browser profile and headed/headless operation;
- the local attachment directory;
- internal pacing, queue capacity, and bounded collection traversal; and
- stdio or loopback-only Streamable HTTP transport.

See [Configuration](docs/CONFIGURATION.md) for ready-made permission presets,
every environment variable, local HTTP sharing, and the container image.

## Troubleshooting

```bash
uvx --from linkedin-mcp-local linkedin-mcp setup
uvx --from linkedin-mcp-local linkedin-mcp login
uvx --from linkedin-mcp-local linkedin-mcp doctor
```

If a GUI client cannot find `uvx`, use the absolute path returned by
`command -v uvx` (macOS/Linux) or `where.exe uvx` (Windows). Restart the client
after changing MCP configuration. See [Troubleshooting](docs/TROUBLESHOOTING.md)
for authentication, handshake, profile-lock, timeout, and permission errors.

## Development

```bash
git clone https://github.com/prakharagarwal-dev/linkedin-mcp-server.git
cd linkedin-mcp-server
uv sync --frozen --all-groups
uv run pytest
```

The default suite is fully offline and never contacts LinkedIn. Read
[CONTRIBUTING.md](CONTRIBUTING.md) and [the testing guide](docs/TESTING.md)
before submitting a change.

## Privacy Policy

The server has no maintainer-operated backend, analytics, advertising, or
telemetry. LinkedIn receives normal visible-UI requests, and the invoking MCP
client receives tool results under its own data policy; the project sends
nothing to the maintainer. Read the complete [privacy policy](PRIVACY.md) for
processing, storage, sharing, retention, and deletion details.

## Safety

- Use only accounts and activity you are authorized to operate.
- Do not use the server for spam, deceptive activity, high-volume extraction,
  or bypassing access controls.
- The server pauses on authentication expiry, checkpoints, restriction pages,
  permission failures, and configuration errors.
- It does not implement CAPTCHA bypass, proxy rotation, fingerprint spoofing,
  credential harvesting, stealth plugins, or private LinkedIn endpoints.
- Never commit or share the persistent browser profile or local assets.

See [SECURITY.md](SECURITY.md) and [the security design](docs/SECURITY.md).

## More documentation

- [Configuration](docs/CONFIGURATION.md)
- [Capability matrix](docs/CAPABILITY_MATRIX.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Testing](docs/TESTING.md)
- [Collection verification](docs/COLLECTION_VERIFICATION_PROCESS.md)
- [Publishing](docs/PUBLISHING.md)
- [Changelog](CHANGELOG.md)

## Let's connect

Have feedback or an idea for LinkedIn MCP Server?

- [Connect with me on LinkedIn](https://www.linkedin.com/in/prakhar-agarwal-byte/)
- [Follow me on GitHub](https://github.com/prakharagarwal-dev)
- [Report a bug or request a feature](https://github.com/prakharagarwal-dev/linkedin-mcp-server/issues)

## License

Licensed under the [Apache License 2.0](LICENSE).

If LinkedIn MCP Server is useful to you, please
[⭐ star the repository](https://github.com/prakharagarwal-dev/linkedin-mcp-server).
