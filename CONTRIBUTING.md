# Contributing

Thank you for helping improve LinkedIn MCP Server. Contributions should keep
the server narrow, typed, local-first, and safe for an operator-controlled
LinkedIn account.

## Before opening an issue

- Search existing issues first.
- Use a private security advisory for vulnerabilities; do not file them as
  public issues. See [SECURITY.md](SECURITY.md).
- Do not include cookies, access tokens, browser profiles, private messages,
  real member data, or screenshots from an authenticated account.

## Development setup

Install Python 3.12 or 3.13 and [`uv`](https://docs.astral.sh/uv/), then run:

```bash
git clone https://github.com/prakharagarwal-dev/linkedin-mcp-server.git
cd linkedin-mcp-server
uv sync --frozen --all-groups
uv run playwright install chromium
```

Create a branch from `main` and keep each pull request focused on one coherent
change.

## Product and safety boundaries

Contributions must preserve these boundaries:

- Use only visible LinkedIn web UI surfaces through Playwright.
- Expose typed capabilities, never generic browser, selector, JavaScript,
  click, network, or navigation tools.
- Keep read and account-changing capabilities separate.
- Require scopes, immutable hash-locked previews, idempotency, and native MCP
  client confirmation for writes.
- Do not add CAPTCHA bypass, proxy rotation, fingerprint spoofing, stealth
  plugins, credential collection, private endpoint access, or bulk-spam
  features.
- Do not add a database, external queue, agent runtime, scheduler, or dependency
  on another repository.

Propose a new capability in an issue before doing substantial implementation
work. Include its exact visible surface, inputs, outputs, authorization scope,
effect, bounds, postcondition, and failure behavior.

## Fixtures and live UI observations

Build vertical slices against offline fixtures first. The default suite must
never contact LinkedIn.

If you inspect the current LinkedIn UI locally, retain only a minimal,
synthetic fixture that represents the relevant structure. Never commit raw DOM
captures, traces, HAR files, cookies, browser storage, profile archives,
credentials, real identities, private content, or account-specific IDs. Mark
fixture provenance accurately; an offline fixture is `mock_verified`, not
`live_verified`.

## Verification

Run the complete gate before submitting a pull request:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv build
```

Use `uv run ruff format .` to apply formatting. New behavior needs positive,
empty, malformed, ambiguous, bounded, and relevant failure cases. New write
operations also need tamper, expiry, idempotency, interruption, and visible
postcondition coverage.

Update durable public documentation when a contract, configuration option,
security property, or accepted behavior changes. Add a concise entry under
`Unreleased` in [CHANGELOG.md](CHANGELOG.md).

## Pull requests

A pull request should explain:

- what contract or defect it changes;
- why the behavior is safe and bounded;
- which tests and fixtures verify it; and
- any compatibility, privacy, or account-risk implications.

By contributing, you agree that your contribution is licensed under the
repository's [Apache License 2.0](LICENSE).
