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

Publishing the GitHub release triggers `.github/workflows/publish.yml` and
`.github/workflows/publish-registries.yml`. The release workflow builds and
validates the wheel, source distribution, and MCPB bundle; attaches them and
their checksums to the release; publishes the Python distributions to PyPI
using Trusted Publishing; and publishes the versioned container to GitHub
Container Registry. The registry workflow waits for that public OCI package,
validates `server.json`, and publishes it with GitHub OIDC.

The `pypi` GitHub environment and PyPI Trusted Publisher must remain scoped to:

- owner: `prakharagarwal-dev`
- repository: `linkedin-mcp-server`
- workflow: `publish.yml`
- environment: `pypi`
- PyPI project: `linkedin-mcp-local`

No long-lived PyPI token belongs in GitHub secrets.

## Registry metadata

`server.json` is the canonical Official MCP Registry metadata. Validate it
with the current official `mcp-publisher validate` command. Its package entry
must point to the exact versioned GHCR image, whose Dockerfile carries the
matching `io.modelcontextprotocol.server.name` ownership label. Registry
publication is intentionally independent from PyPI, so a PyPI account or
outage cannot block Official Registry, GitHub Registry, or downstream catalog
discovery. The hidden `mcp-name` marker remains in the packaged README so the
PyPI distribution can also prove registry ownership in a future metadata
version.

`packaging/mcpb/manifest.json` is the canonical desktop-bundle manifest. The
release workflow stages the runtime-only project files and icon before packing
the `.mcpb` artifact; generated bundles are release artifacts and are not
committed.

Third-party catalogs should point to the canonical GitHub repository, PyPI
project, Official MCP Registry entry, GitHub release, or GHCR package. A
catalog listing must not imply official LinkedIn affiliation or claim a hosted
remote service.
