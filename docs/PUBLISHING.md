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

## Release contract

1. Update the version in `pyproject.toml`, `server.json`, and
   `packaging/mcpb/manifest.json`, then regenerate `uv.lock`.
2. Move the release notes from `Unreleased` to the matching version in
   `CHANGELOG.md`.
3. Run the complete offline verification gate documented in `README.md`.
4. Merge the focused release pull request into `main`.
5. Publish a GitHub release from an annotated `vX.Y.Z` tag.

Publishing the GitHub release triggers `.github/workflows/publish.yml`. The
workflow builds and validates the wheel, source distribution, and MCPB bundle;
attaches them and their checksums to the release; publishes the Python
distributions to PyPI using Trusted Publishing; and publishes the versioned
container to GitHub Container Registry.

The `pypi` GitHub environment and PyPI Trusted Publisher must remain scoped to:

- owner: `prakharagarwal-dev`
- repository: `linkedin-mcp-server`
- workflow: `publish.yml`
- environment: `pypi`
- PyPI project: `linkedin-mcp-local`

No long-lived PyPI token belongs in GitHub secrets.

## Registry metadata

`server.json` is the canonical Official MCP Registry metadata. Validate it
with the current official `mcp-publisher validate` command and publish it only
after the exact PyPI version is available. The hidden `mcp-name` marker in the
packaged README proves PyPI ownership to the registry.

`packaging/mcpb/manifest.json` is the canonical desktop-bundle manifest. The
release workflow stages the runtime-only project files and icon before packing
the `.mcpb` artifact; generated bundles are release artifacts and are not
committed.

Third-party catalogs should point to the canonical GitHub repository, PyPI
project, Official MCP Registry entry, GitHub release, or GHCR package. A
catalog listing must not imply official LinkedIn affiliation or claim a hosted
remote service.
