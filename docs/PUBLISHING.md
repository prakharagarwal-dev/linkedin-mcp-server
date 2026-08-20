# Publishing

This project has three intentionally different identifiers:

| Surface | Identifier |
| --- | --- |
| GitHub repository | `prakharagarwal-dev/linkedin-mcp-server` |
| MCP Registry server | `io.github.prakharagarwal-dev/linkedin-mcp-server` |
| PyPI distribution | `linkedin-mcp-local` |
| Python import | `linkedin_mcp` |
| Executable | `linkedin-mcp` |
| Container | `ghcr.io/prakharagarwal-dev/linkedin-mcp-server` |

The PyPI name differs because `linkedin-mcp-server` is owned by an unrelated
project. Do not rename the executable, import package, MCP identity, or GitHub
repository to match the distribution.

## Product description

Use this exact outcome-focused description in package metadata, marketplace
submissions, catalogs, release copy, and repository profiles:

> A LinkedIn MCP server to find jobs, search people, research companies, manage
> your network, publish and engage with posts, and read or send messages.

Do not replace it with implementation, architecture, safety, or tool-count
positioning. The only exception is the Official MCP Registry `description`,
whose schema enforces a 100-character maximum; `server.json` keeps the tested
compact variant required by that schema.

## Release contract

1. Update the version in `pyproject.toml`, `server.json`, `manifest.json`,
   `Dockerfile`, `CITATION.cff`, and
   `src/linkedin_mcp/__init__.py`, then regenerate `uv.lock`.
2. Move the release notes from `Unreleased` to the matching version in
   `CHANGELOG.md`.
3. Run the complete offline verification gate documented in `README.md`.
4. Merge the focused release pull request into `main`.
5. Publish a GitHub release from an annotated `vX.Y.Z` tag.

Publishing the GitHub release triggers `.github/workflows/publish.yml` and
`.github/workflows/publish-registries.yml`. The release workflow builds and
validates the wheel, source distribution, and MCPB bundle; attaches them and
their checksums to the release; publishes the Python distributions to PyPI
using Trusted Publishing; and publishes the versioned container to GitHub
Container Registry. The registry workflow waits for the public OCI image and
MCPB release asset, calculates the MCPB checksum, adds that immutable download
to its working copy of `server.json`, validates the complete record, and
publishes it with GitHub OIDC. Official Registry versions are immutable, so the
MCPB package appears in the first version published after this workflow change;
an already-published record cannot be amended in place.

The `pypi` GitHub environment and PyPI Trusted Publisher must remain scoped to:

- owner: `prakharagarwal-dev`
- repository: `linkedin-mcp-server`
- workflow: `publish.yml`
- environment: `pypi`
- PyPI project: `linkedin-mcp-local`

No long-lived PyPI token belongs in GitHub secrets.

## Registry metadata

`server.json` is the canonical source for Official MCP Registry metadata.
Validate it with the current official `mcp-publisher validate` command. Its
committed package entry points to the exact versioned GHCR image, whose
Dockerfile carries the matching `io.modelcontextprotocol.server.name`
ownership label. At publication time the registry workflow adds the matching
GitHub Release MCPB URL and computed SHA-256 checksum without rewriting the
tagged source file. Registry publication is intentionally independent from
PyPI, so a PyPI account or outage cannot block Official Registry, GitHub
Registry, or downstream catalog discovery. The hidden `mcp-name` marker
remains in the packaged README so the PyPI distribution can also prove
registry ownership in a future metadata version.

The root `manifest.json` is the canonical desktop-bundle manifest. The release
workflow stages the runtime-only project files and icon before packing the
`.mcpb` artifact; generated bundles are release artifacts and are not committed.

Third-party catalogs should point to the canonical GitHub repository, PyPI
project, Official MCP Registry entry, GitHub release, or GHCR package. A
catalog listing must not imply official LinkedIn affiliation or claim a hosted
remote service.

The maintained coverage ledger, submission links, and follow-up state are in
[`DISTRIBUTION.md`](DISTRIBUTION.md).
