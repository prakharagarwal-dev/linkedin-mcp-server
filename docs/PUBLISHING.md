# Publishing

## Release identities

| Surface | Identifier |
| --- | --- |
| GitHub repository | `prakharagarwal-dev/linkedin-mcp-server` |
| MCP Registry server | `io.github.prakharagarwal-dev/linkedin-mcp-server` |
| PyPI distribution | `linkedin-mcp-local` |
| Python import | `linkedin_mcp` |
| Executable | `linkedin-mcp` |
| Container | `ghcr.io/prakharagarwal-dev/linkedin-mcp-server` |

The PyPI name differs because `linkedin-mcp-server` belongs to an unrelated
project. Do not rename the executable, import package, MCP identity, or GitHub
repository to match it.

Use this exact public description where the field permits it:

> A LinkedIn MCP server to find jobs, search people, research companies, manage
> your network, publish and engage with posts, and read or send messages.

`server.json` uses a tested compact description because the Official MCP
Registry limits that field to 100 characters.

## Release checklist

1. Update the version in `pyproject.toml`, `server.json`, `Dockerfile`,
   `CITATION.cff`, and `src/linkedin_mcp/__init__.py`, then regenerate `uv.lock`.
2. Move the notes under `Unreleased` to the matching version in `CHANGELOG.md`.
3. Run the full verification gate from [TESTING.md](TESTING.md).
4. Merge the focused release pull request into `main`.
5. Publish a GitHub release from an annotated `vX.Y.Z` tag.

Publishing a release triggers two workflows:

- `.github/workflows/publish.yml` builds and attests the wheel and source
  distribution, attaches them and checksums to the GitHub release, publishes
  PyPI through Trusted Publishing, and publishes an attested multi-platform
  container with an SBOM to GHCR.
- `.github/workflows/publish-registries.yml` waits for the immutable OCI image,
  validates `server.json`, publishes it to the Official MCP Registry with
  GitHub OIDC, and verifies the published version.

The project no longer builds or publishes MCPB or stdio packages.

## PyPI trust

The `pypi` GitHub environment and PyPI Trusted Publisher must remain scoped to:

- owner: `prakharagarwal-dev`
- repository: `linkedin-mcp-server`
- workflow: `publish.yml`
- environment: `pypi`
- PyPI project: `linkedin-mcp-local`

No long-lived PyPI token belongs in GitHub secrets.

## Registry metadata

`server.json` is the canonical Official MCP Registry record. Its one package
points to the exact versioned GHCR image and declares:

- Docker as the runtime;
- host-loopback publication of container port 8000;
- `serve` as the image argument; and
- `http://127.0.0.1:8000/mcp` as the Streamable HTTP endpoint.

Validate the file with the pinned `mcp-publisher validate` command used by the
workflow. The Dockerfile carries the matching
`io.modelcontextprotocol.server.name` ownership label. The hidden `mcp-name`
marker remains in the packaged README so the PyPI distribution can support
registry ownership checks.

`assets/icon.png` is used by the registry record through its canonical HTTPS
URL. There is no bundle manifest.

Registry publication is independent from PyPI, so a PyPI outage cannot block
the Official Registry, GHCR, or downstream catalog discovery. Third-party
catalogs should point to the canonical repository, PyPI project, Official MCP
Registry entry, GitHub release, or GHCR package and must not imply official
LinkedIn affiliation or a maintainer-operated hosted service.

See [DISTRIBUTION.md](DISTRIBUTION.md) for the maintained catalog ledger.
