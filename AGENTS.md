# Repository Instructions

## Product boundary

- This repository is a standalone Python MCP server. It must not import from or
  depend on `startup-scanner` or another LinkedIn MCP server.
- The server exposes typed LinkedIn capabilities. It does not contain agents,
  LangGraph, natural-language planning, ranking, scheduling, or an LLM runtime.
- LinkedIn access is contract-driven and limited to configured hosts, declared surfaces,
  accounts, one local process, one browser worker, and internal navigation timing.
- Do not expose generic browser, JavaScript, network, click, or navigation tools.
- Read and account-changing capabilities are separate. Each account-changing tool is
  one complete action call. Tool availability and the MCP client's approval policy
  are the authorization boundary; the server does not maintain a second scope,
  preview, or idempotency permission layer. Write annotations request interactive
  confirmation by default, while explicit durable per-tool client configuration may
  authorize unattended invocation.

## Access and secrets

- Use only visible LinkedIn web UI surfaces through Playwright.
- Do not implement CAPTCHA bypass, proxy rotation, fingerprint spoofing,
  credential harvesting, or private endpoint access.
- Never commit cookies, browser storage state, encryption keys, passwords,
  database credentials, API tokens, or `.env` files.
- Pause live access on authentication expiry, checkpoints, restriction pages,
  permission failures, or configuration errors.

## Technical conventions

- Python 3.12+, strict Pyright, Ruff, Pydantic v2, and async I/O.
- Use the official `mcp` Python SDK and official Playwright async API.
- Use an in-process `asyncio.Queue` for local capability execution. Do not store
  call results, observations, or evidence. The browser profile is the only
  server-owned authentication persistence. Client approval choices are not stored
  as server authorization records. Do not add a database or external work queue.
- Keep MCP transport wiring, policy, browser mechanics, page extraction, and domain
  contracts in separate modules.
- Return immutable field-level evidence with source URL and capture time in the
  tool response.
- Prefer accessible, user-facing Playwright locators.
- Every operation must be bounded and observable. Every read invocation executes
  freshly. Every write-tool invocation is a new action and must never be retried
  automatically after its final LinkedIn control may have been invoked.

## Working style

- Build vertical slices with offline fixtures before live access.
- Live tests are opt-in and low volume; they never run in the default suite.
- For every asynchronous search, list, feed, inbox, comment, invitation, or
  other collection, follow `docs/COLLECTION_VERIFICATION_PROCESS.md`.
- Do not call a collection complete merely because it stops cleanly. Reconcile
  the selected visible inventory with typed results plus explicitly classified
  unsupported cards, and keep neighboring collections separate.
- When reconciliation is unavailable or fails, return an honest safety bound,
  truncation, or parser-drift result instead of `visible_page_complete`.
- Update durable public documentation when behavior or safety contracts change.
- Preserve one intentional commit per accepted change.

## Verification

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
uv build
```
