"""Explicit offline-verification ownership for every public MCP tool."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ToolVerification:
    domain: str
    effect: str
    layers: frozenset[str]
    test_files: tuple[str, ...]


_OPERATIONAL = frozenset({"contract", "runtime"})
_READ = frozenset({"contract", "page", "runtime"})
_WRITE = frozenset({"contract", "page", "action", "runtime", "workflow"})


def _entry(
    domain: str,
    effect: str,
    layers: frozenset[str],
    *test_files: str,
) -> ToolVerification:
    return ToolVerification(domain, effect, layers, test_files)


MOCK_VERIFICATION: dict[str, ToolVerification] = {
    "linkedin.server.status": _entry(
        "operational", "read", _OPERATIONAL, "tests/contract/test_mcp_protocol.py"
    ),
    "linkedin.session.status": _entry(
        "operational",
        "read",
        _OPERATIONAL,
        "tests/contract/test_mcp_protocol.py",
        "tests/unit/test_auth_coordinator.py",
    ),
    "linkedin.jobs.search": _entry(
        "jobs",
        "read",
        _READ,
        "tests/unit/test_job_pages.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.jobs.get": _entry(
        "jobs",
        "read",
        _READ,
        "tests/contract/test_mcp_protocol.py",
        "tests/unit/test_job_pages.py",
        "tests/unit/test_executor.py",
    ),
    "linkedin.people.search": _entry(
        "people",
        "read",
        _READ,
        "tests/contract/test_mcp_protocol.py",
        "tests/unit/test_people_pages.py",
        "tests/unit/test_executor.py",
    ),
    "linkedin.people.get": _entry(
        "people",
        "read",
        _READ,
        "tests/contract/test_mcp_protocol.py",
        "tests/unit/test_people_pages.py",
        "tests/unit/test_executor.py",
    ),
    "linkedin.companies.search": _entry(
        "companies",
        "read",
        _READ,
        "tests/contract/test_mcp_protocol.py",
        "tests/unit/test_company_pages.py",
        "tests/unit/test_executor.py",
    ),
    "linkedin.companies.get": _entry(
        "companies",
        "read",
        _READ,
        "tests/contract/test_mcp_protocol.py",
        "tests/unit/test_company_pages.py",
        "tests/unit/test_executor.py",
    ),
    "linkedin.posts.search": _entry(
        "posts",
        "read",
        _READ,
        "tests/contract/test_mcp_protocol.py",
        "tests/unit/test_post_pages.py",
        "tests/unit/test_executor.py",
    ),
    "linkedin.posts.get": _entry(
        "posts",
        "read",
        _READ,
        "tests/contract/test_mcp_protocol.py",
        "tests/unit/test_post_pages.py",
        "tests/unit/test_executor.py",
    ),
    "linkedin.posts.comments.list": _entry(
        "posts",
        "read",
        _READ,
        "tests/contract/test_mcp_protocol.py",
        "tests/unit/test_post_pages.py",
        "tests/unit/test_executor.py",
    ),
    "linkedin.posts.create": _entry(
        "posts",
        "write",
        _WRITE,
        "tests/unit/test_publishing_pages.py",
        "tests/contract/test_write_conformance.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.posts.comment": _entry(
        "posts",
        "write",
        _WRITE,
        "tests/unit/test_engagement_pages.py",
        "tests/contract/test_write_conformance.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.posts.react": _entry(
        "posts",
        "write",
        _WRITE,
        "tests/unit/test_engagement_pages.py",
        "tests/contract/test_write_conformance.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.invitations.list": _entry(
        "invitations",
        "read",
        _READ,
        "tests/contract/test_mcp_protocol.py",
        "tests/unit/test_invitation_pages.py",
        "tests/unit/test_pagination.py",
    ),
    "linkedin.connections.list": _entry(
        "connections",
        "read",
        _READ,
        "tests/contract/test_mcp_protocol.py",
        "tests/unit/test_connection_pages.py",
    ),
    "linkedin.connections.search": _entry(
        "connections",
        "read",
        _READ,
        "tests/contract/test_mcp_protocol.py",
        "tests/unit/test_people_pages.py",
        "tests/unit/test_executor.py",
    ),
    "linkedin.invitations.send": _entry(
        "invitations",
        "write",
        _WRITE,
        "tests/unit/test_connection_pages.py",
        "tests/contract/test_write_conformance.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.invitations.accept": _entry(
        "invitations",
        "write",
        _WRITE,
        "tests/unit/test_connection_pages.py",
        "tests/contract/test_write_conformance.py",
    ),
    "linkedin.invitations.ignore": _entry(
        "invitations",
        "write",
        _WRITE,
        "tests/unit/test_connection_pages.py",
        "tests/contract/test_write_conformance.py",
    ),
    "linkedin.messaging.search": _entry(
        "messaging",
        "read",
        _READ,
        "tests/contract/test_mcp_protocol.py",
        "tests/unit/test_messaging_pages.py",
        "tests/unit/test_executor.py",
    ),
    "linkedin.messaging.conversation.get": _entry(
        "messaging",
        "read",
        _READ,
        "tests/contract/test_mcp_protocol.py",
        "tests/unit/test_messaging_pages.py",
        "tests/unit/test_executor.py",
    ),
    "linkedin.messaging.send": _entry(
        "messaging",
        "write",
        _WRITE,
        "tests/unit/test_messaging_pages.py",
        "tests/contract/test_write_conformance.py",
        "tests/workflows/test_mock_workflows.py",
    ),
}


def missing_test_files(root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                test_file
                for verification in MOCK_VERIFICATION.values()
                for test_file in verification.test_files
                if not (root / test_file).is_file()
            }
        )
    )
