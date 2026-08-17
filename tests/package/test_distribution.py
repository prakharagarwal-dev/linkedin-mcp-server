from __future__ import annotations

import ast
import email
import json
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
PUBLIC_DESCRIPTION = (
    "A LinkedIn MCP server to find jobs, search people, research companies, "
    "manage your network, publish and engage with posts, and read or send messages."
)
REGISTRY_DESCRIPTION = (
    "Find LinkedIn jobs and people, research companies, manage network, posts, "
    "and messages with MCP."
)
FORBIDDEN_RUNTIME_DEPENDENCIES = {
    "alembic",
    "psycopg",
    "sqlalchemy",
    "testcontainers",
    "keyring",
}
PUBLIC_REPOSITORY_FILES = {
    ".github/CODEOWNERS",
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/dependabot.yml",
    ".github/pull_request_template.md",
    ".github/workflows/ci.yml",
    ".github/workflows/codeql.yml",
    ".github/workflows/publish-registries.yml",
    ".github/workflows/publish.yml",
    "assets/icon.png",
    "CHANGELOG.md",
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "PRIVACY.md",
    "README.md",
    "SECURITY.md",
    "docs/DISTRIBUTION.md",
    "docs/PUBLISHING.md",
    "packaging/mcpb/manifest.json",
    "server.json",
}


def test_build_configuration_packages_only_the_standalone_server() -> None:
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = configuration["project"]
    wheel = configuration["tool"]["hatch"]["build"]["targets"]["wheel"]
    dependencies = {
        requirement.split("[", 1)[0].split(">", 1)[0].split("<", 1)[0].casefold()
        for requirement in project["dependencies"]
    }

    assert project["name"] == "linkedin-mcp-local"
    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE"]
    assert project["authors"] == [
        {"name": "Prakhar Agarwal", "email": "prakharagarwal3031@gmail.com"}
    ]
    assert project["urls"]["Repository"] == (
        "https://github.com/prakharagarwal-dev/linkedin-mcp-server"
    )
    assert wheel["packages"] == ["src/linkedin_mcp"]
    assert dependencies.isdisjoint(FORBIDDEN_RUNTIME_DEPENDENCIES)
    assert project["scripts"] == {"linkedin-mcp": "linkedin_mcp.cli.main:main"}

    production_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "src" / "linkedin_mcp").rglob("*.py"))
    )
    assert "tests.simulator" not in production_sources
    assert "startup_scanner" not in production_sources
    assert "startup-scanner" not in production_sources


def test_source_layout_keeps_infrastructure_and_linkedin_features_separate() -> None:
    package = ROOT / "src" / "linkedin_mcp"
    retired_layers = ("application", "auth", "automation", "domain", "linkedin", "policy")
    for layer in retired_layers:
        assert not tuple((package / layer).glob("*.py"))

    tools = package / "tools"
    capability_paths = {
        "linkedin.server.status": "server/status",
        "linkedin.session.status": "session/status",
        "linkedin.jobs.search": "jobs/search",
        "linkedin.jobs.get": "jobs/get",
        "linkedin.people.search": "people/search",
        "linkedin.people.get": "people/get",
        "linkedin.companies.search": "companies/search",
        "linkedin.companies.get": "companies/get",
        "linkedin.posts.search": "posts/search",
        "linkedin.posts.get": "posts/get",
        "linkedin.posts.comments.list": "posts/comments/list",
        "linkedin.posts.create": "posts/create",
        "linkedin.posts.comment": "posts/comment",
        "linkedin.posts.react": "posts/react",
        "linkedin.invitations.list": "invitations/list",
        "linkedin.invitations.send": "invitations/send",
        "linkedin.invitations.accept": "invitations/accept",
        "linkedin.invitations.ignore": "invitations/ignore",
        "linkedin.connections.list": "connections/list",
        "linkedin.connections.search": "connections/search",
        "linkedin.messaging.search": "messaging/search",
        "linkedin.messaging.conversation.get": "messaging/conversation/get",
        "linkedin.messaging.send": "messaging/send",
    }
    status_tools = {"linkedin.server.status", "linkedin.session.status"}
    for tool_name, relative_path in capability_paths.items():
        capability = tools / relative_path
        required_files = {"__init__.py", "tool.py"}
        if tool_name not in status_tools:
            required_files.update({"evidence.py", "operation.py", "page.py"})
        assert required_files <= {path.name for path in capability.glob("*.py")}
        model_package = capability / "models"
        assert (model_package / "__init__.py").is_file()
        assert not (capability / "models.py").exists()
        assert any(path.name != "__init__.py" for path in model_package.glob("*.py"))
        assert f'name="{tool_name}"' in (capability / "tool.py").read_text(encoding="utf-8")
        if tool_name not in status_tools:
            page_source = (capability / "page.py").read_text(encoding="utf-8")
            assert "class " in page_source
            assert "Capability-owned exports from" not in page_source
            assert "._shared.pages" not in page_source

    server_source = (package / "mcp" / "server.py").read_text(encoding="utf-8")
    assert "attach_tools(mcp, container)" in server_source
    assert "@mcp.tool" not in server_source

    domain_modules = {
        "jobs": {"__init__.py", "surface.py"},
        "people": {"__init__.py", "surface.py"},
        "companies": {"__init__.py", "surface.py"},
        "posts": {"__init__.py", "engagement_surface.py", "surface.py"},
        "invitations": {"__init__.py", "action_surface.py"},
        "connections": {"__init__.py"},
        "messaging": {"__init__.py", "conversation_surface.py"},
    }
    for domain, expected_modules in domain_modules.items():
        assert {path.name for path in (tools / domain).glob("*.py")} == expected_modules
        assert not (tools / domain / "_shared").exists()
    production_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in package.rglob("*.py")
    )
    assert not (tools / "_shared" / "network_models.py").exists()
    assert not (tools / "_shared" / "status.py").exists()
    assert "linkedin_mcp.tools._shared.model_exports" not in production_sources
    assert "linkedin_mcp.tools._shared.network_operations" not in production_sources
    for source_path in package.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        aggregate_model_imports = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.endswith(".models")
            and node.module != "linkedin_mcp.tools._shared.models"
        ]
        assert aggregate_model_imports == [], source_path

    browser = package / "browser"
    assert {path.name for path in browser.glob("*.py")} == {
        "__init__.py",
        "bootstrap.py",
        "profile.py",
        "runtime.py",
    }
    browser_sources = "\n".join(path.read_text(encoding="utf-8") for path in browser.glob("*.py"))
    assert "linkedin_mcp.linkedin" not in browser_sources

    cli = package / "cli"
    commands = cli / "commands"
    for command in (
        "serve",
        "setup",
        "login",
        "logout",
        "doctor",
        "status",
        "stop",
    ):
        assert (commands / f"{command}.py").is_file()
    for profile_command in ("create", "status", "reset"):
        assert (commands / "profile" / f"{profile_command}.py").is_file()
    for retired_cli_module in ("common.py", "types.py", "internal_runtime.py"):
        assert not (cli / retired_cli_module).exists()

    runtime = package / "runtime"
    for runtime_module in ("__main__.py", "owned_operation.py", "runner.py"):
        assert (runtime / runtime_module).is_file()

    main_source = (cli / "main.py").read_text(encoding="utf-8")
    assert "BrowserProfileManager" not in main_source
    assert "run_shared_runtime" not in main_source
    assert "_runtime" not in main_source


def test_public_repository_metadata_is_complete() -> None:
    missing = sorted(path for path in PUBLIC_REPOSITORY_FILES if not (ROOT / path).is_file())

    assert missing == []
    assert "Apache License" in (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Report a vulnerability privately" in (ROOT / "SECURITY.md").read_text(encoding="utf-8")


def test_supported_runtime_versions_and_platforms_are_consistent() -> None:
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = configuration["project"]
    bundle = json.loads((ROOT / "packaging" / "mcpb" / "manifest.json").read_text(encoding="utf-8"))
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert project["requires-python"] == ">=3.12,<3.15"
    assert bundle["compatibility"]["runtimes"]["python"] == ">=3.12 <3.15"
    assert {
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Programming Language :: Python :: 3.14",
    } <= set(project["classifiers"])
    assert {
        "Operating System :: MacOS",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX :: Linux",
    } <= set(project["classifiers"])
    assert 'python-version: ["3.12", "3.13", "3.14"]' in workflow
    assert "macos-latest" in workflow
    assert "windows-latest" in workflow
    assert "ubuntu-24.04-arm" in workflow
    assert "UV_PYTHON: ${{ matrix.python-version }}" in workflow
    assert 'UV_PYTHON: "3.13"' in workflow


def test_release_workflow_has_a_non_mutating_pypi_retry_target() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    all_surfaces_gate = "if: ${{ github.event_name == 'release' || inputs.target == 'all' }}"
    pypi_job = workflow.split("\n  pypi:\n", 1)[1].split("\n  container:\n", 1)[0]

    assert "      target:\n" in workflow
    assert "        default: all\n" in workflow
    assert "          - all\n          - pypi\n" in workflow
    assert workflow.count(all_surfaces_gate) == 2
    assert all_surfaces_gate not in pypi_job


def test_registry_workflow_publishes_immutable_oci_and_mcpb_packages() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish-registries.yml").read_text(
        encoding="utf-8"
    )

    assert 'MCPB_FILENAME="linkedin-mcp-server-$VERSION.mcpb"' in workflow
    assert 'RELEASE_TAG="v$VERSION"' in workflow
    assert "gh release download" in workflow
    assert 'registryType: "mcpb"' in workflow
    assert "fileSha256: $sha256" in workflow
    assert '.registryType == "oci" and .identifier == $image' in workflow
    assert '.registryType == "mcpb" and' in workflow
    assert ".fileSha256 == $mcpb_sha256" in workflow


def test_registry_and_bundle_metadata_share_the_release_identity() -> None:
    registry = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    bundle = json.loads((ROOT / "packaging" / "mcpb" / "manifest.json").read_text(encoding="utf-8"))
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = configuration["project"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert registry["name"] == "io.github.prakharagarwal-dev/linkedin-mcp-server"
    assert registry["version"] == project["version"] == bundle["version"]
    assert project["description"] == PUBLIC_DESCRIPTION
    assert registry["description"] == REGISTRY_DESCRIPTION
    assert len(registry["description"]) <= 100
    assert bundle["description"] == PUBLIC_DESCRIPTION
    assert bundle["long_description"] == PUBLIC_DESCRIPTION
    assert PUBLIC_DESCRIPTION in readme.replace("\n", " ")
    assert f'org.opencontainers.image.description="{PUBLIC_DESCRIPTION}"' in dockerfile
    assert registry["packages"] == [
        {
            "registryType": "oci",
            "identifier": (f"ghcr.io/prakharagarwal-dev/linkedin-mcp-server:{project['version']}"),
            "transport": {"type": "stdio"},
            "packageArguments": [
                {"type": "positional", "value": "serve"},
                {"type": "positional", "value": "--transport"},
                {"type": "positional", "value": "stdio"},
            ],
        }
    ]
    assert bundle["manifest_version"] == "0.4"
    assert bundle["name"] == "linkedin-mcp-server"
    assert bundle["server"]["type"] == "uv"
    assert "live_enabled" not in bundle["user_config"]
    assert "LINKEDIN_MCP_LIVE_ENABLED" not in json.dumps(registry)
    assert "LINKEDIN_MCP_LIVE_ENABLED" not in json.dumps(bundle)
    assert bundle["privacy_policies"] == [
        "https://github.com/prakharagarwal-dev/linkedin-mcp-server/blob/main/PRIVACY.md",
        "https://www.linkedin.com/legal/privacy-policy",
    ]
    privacy = (ROOT / "PRIVACY.md").read_text(encoding="utf-8")
    assert re.search(r"^## (?:\S+\s+)?Privacy Policy\s*$", readme, re.MULTILINE)
    assert all(
        heading in privacy
        for heading in (
            "## Data the server processes",
            "## How data is used and stored",
            "## Third-party sharing",
            "## Retention and deletion",
            "## Contact",
        )
    )
    assert "<!-- mcp-name: io.github.prakharagarwal-dev/linkedin-mcp-server -->" in readme


def test_synthetic_fixtures_contain_no_session_or_trace_artifacts() -> None:
    fixture_root = ROOT / "tests" / "fixtures"
    forbidden_names = {
        ".env",
        "cookies.json",
        "storage-state.json",
        "storage_state.json",
    }
    forbidden_suffixes = {".har", ".trace", ".zip"}
    forbidden_text = {
        '"source": "live"',
        "@gmail.com",
        "@outlook.com",
        "@yahoo.com",
        "authorization: bearer",
        "cookie: li_at",
        "dms.licdn.com",
        '"li_at"',
        "media.licdn.com",
        "password=",
        "source: live",
        "voyager/api",
    }

    for path in fixture_root.rglob("*"):
        if not path.is_file():
            continue
        assert path.name.casefold() not in forbidden_names
        assert path.suffix.casefold() not in forbidden_suffixes
        content = path.read_text(encoding="utf-8", errors="ignore").casefold()
        assert all(token not in content for token in forbidden_text), path


@pytest.mark.timeout(90)
def test_wheel_excludes_tests_profiles_secrets_and_other_repositories(tmp_path: Path) -> None:
    output = tmp_path / "dist"
    completed = subprocess.run(
        [
            "uv",
            "build",
            "--offline",
            "--wheel",
            "--out-dir",
            str(output),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=80,
    )
    assert completed.returncode == 0, completed.stderr
    wheels = tuple(output.glob("*.whl"))
    assert len(wheels) == 1

    with zipfile.ZipFile(wheels[0]) as archive:
        names = tuple(archive.namelist())
        lowered = tuple(name.casefold() for name in names)
        assert "linkedin_mcp/mcp/server.py" in names
        assert "linkedin_mcp/tools/jobs/search/tool.py" in names
        assert "linkedin_mcp/tools/jobs/search/operation.py" in names
        assert any(name.endswith(".dist-info/entry_points.txt") for name in names)
        assert not any(name.startswith("tests/") for name in names)
        assert not any("simulator" in name for name in lowered)
        assert not any("startup-scanner" in name for name in lowered)
        assert not any(
            name.endswith((".env", "cookies.json", "storage-state.json")) for name in lowered
        )
        assert not any(
            ("/profile/" in name and not name.startswith("linkedin_mcp/cli/commands/profile/"))
            or "browser_profile" in name
            for name in lowered
        )

        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = email.message_from_bytes(archive.read(metadata_name))
        requirements = tuple(metadata.get_all("Requires-Dist", []))
        assert metadata["License-Expression"] == "Apache-2.0"
        assert metadata["Author-email"] == ("Prakhar Agarwal <prakharagarwal3031@gmail.com>")
        assert any(
            value.endswith("Repository, https://github.com/prakharagarwal-dev/linkedin-mcp-server")
            for value in metadata.get_all("Project-URL", [])
        )
        assert not any(
            requirement.split("[", 1)[0].split(" ", 1)[0].casefold()
            in FORBIDDEN_RUNTIME_DEPENDENCIES
            for requirement in requirements
        )
        assert any(name.endswith(".dist-info/licenses/LICENSE") for name in names)

        entry_points_name = next(
            name for name in names if name.endswith(".dist-info/entry_points.txt")
        )
        entry_points = archive.read(entry_points_name).decode()
        assert "linkedin-mcp = linkedin_mcp.cli.main:main" in entry_points

    imported = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                f"sys.path.insert(0, {str(wheels[0])!r}); "
                "import linkedin_mcp; "
                "print(linkedin_mcp.__version__)"
            ),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert imported.returncode == 0, imported.stderr
    assert imported.stdout.strip()
