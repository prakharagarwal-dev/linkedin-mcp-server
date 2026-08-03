"""Explicit mock-verification ownership for every public MCP tool."""

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
_PREPARE = frozenset({"contract", "page", "action", "runtime"})
_WRITE = frozenset({"contract", "page", "action", "runtime", "workflow"})


def _entry(
    domain: str,
    effect: str,
    layers: frozenset[str],
    *test_files: str,
) -> ToolVerification:
    return ToolVerification(
        domain=domain,
        effect=effect,
        layers=layers,
        test_files=test_files,
    )


MOCK_VERIFICATION: dict[str, ToolVerification] = {
    "linkedin.server.status": _entry(
        "operational",
        "read",
        _OPERATIONAL,
        "tests/contract/test_mcp_protocol.py",
        "tests/unit/test_cli.py",
    ),
    "linkedin.capabilities.list": _entry(
        "operational",
        "read",
        _OPERATIONAL,
        "tests/contract/test_mcp_protocol.py",
        "tests/unit/test_registry.py",
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
        "tests/unit/test_job_pages.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.people.search": _entry(
        "people",
        "read",
        _READ,
        "tests/unit/test_people_pages.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.people.get": _entry(
        "people",
        "read",
        _READ,
        "tests/unit/test_people_pages.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.companies.search": _entry(
        "companies",
        "read",
        _READ,
        "tests/unit/test_company_pages.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.companies.get": _entry(
        "companies",
        "read",
        _READ,
        "tests/unit/test_company_pages.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.posts.search": _entry(
        "posts",
        "read",
        _READ,
        "tests/unit/test_post_pages.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.posts.get": _entry(
        "posts",
        "read",
        _READ,
        "tests/unit/test_post_pages.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.posts.comments.list": _entry(
        "posts",
        "read",
        _READ,
        "tests/unit/test_post_pages.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.posts.create.prepare": _entry(
        "posts",
        "prepare",
        _PREPARE,
        "tests/unit/test_publishing_pages.py",
        "tests/unit/test_executor.py",
        "tests/contract/test_mcp_protocol.py",
    ),
    "linkedin.posts.create.execute": _entry(
        "posts",
        "write",
        _WRITE,
        "tests/unit/test_publishing_pages.py",
        "tests/unit/test_executor.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.posts.comment.prepare": _entry(
        "posts",
        "prepare",
        _PREPARE,
        "tests/unit/test_engagement_pages.py",
        "tests/unit/test_executor.py",
        "tests/contract/test_mcp_protocol.py",
    ),
    "linkedin.posts.comment.execute": _entry(
        "posts",
        "write",
        _WRITE,
        "tests/unit/test_engagement_pages.py",
        "tests/unit/test_executor.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.posts.reaction.prepare": _entry(
        "posts",
        "prepare",
        _PREPARE,
        "tests/unit/test_engagement_pages.py",
        "tests/unit/test_executor.py",
        "tests/contract/test_mcp_protocol.py",
    ),
    "linkedin.posts.reaction.execute": _entry(
        "posts",
        "write",
        _WRITE,
        "tests/unit/test_engagement_pages.py",
        "tests/unit/test_executor.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.invitations.list": _entry(
        "invitations",
        "read",
        _READ,
        "tests/unit/test_invitation_pages.py",
        "tests/unit/test_pagination.py",
        "tests/unit/test_executor.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.connections.list": _entry(
        "connections",
        "read",
        _READ,
        "tests/unit/test_connection_pages.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.connections.search": _entry(
        "connections",
        "read",
        _READ,
        "tests/unit/test_people_pages.py",
        "tests/unit/test_executor.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.invitations.send.prepare": _entry(
        "invitations",
        "prepare",
        _PREPARE,
        "tests/unit/test_connection_pages.py",
        "tests/unit/test_executor.py",
        "tests/contract/test_mcp_protocol.py",
    ),
    "linkedin.invitations.send.execute": _entry(
        "invitations",
        "write",
        _WRITE,
        "tests/unit/test_connection_pages.py",
        "tests/unit/test_executor.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.invitations.accept.prepare": _entry(
        "invitations",
        "prepare",
        _PREPARE,
        "tests/unit/test_connection_pages.py",
        "tests/unit/test_executor.py",
        "tests/contract/test_mcp_protocol.py",
    ),
    "linkedin.invitations.accept.execute": _entry(
        "invitations",
        "write",
        _WRITE,
        "tests/unit/test_connection_pages.py",
        "tests/unit/test_executor.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.invitations.ignore.prepare": _entry(
        "invitations",
        "prepare",
        _PREPARE,
        "tests/unit/test_connection_pages.py",
        "tests/unit/test_executor.py",
        "tests/contract/test_mcp_protocol.py",
    ),
    "linkedin.invitations.ignore.execute": _entry(
        "invitations",
        "write",
        _WRITE,
        "tests/unit/test_connection_pages.py",
        "tests/unit/test_executor.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.messaging.search": _entry(
        "messaging",
        "read",
        _READ,
        "tests/unit/test_messaging_pages.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.messaging.conversation.get": _entry(
        "messaging",
        "read",
        _READ,
        "tests/unit/test_messaging_pages.py",
        "tests/contract/test_mcp_protocol.py",
        "tests/workflows/test_mock_workflows.py",
    ),
    "linkedin.messaging.message.prepare": _entry(
        "messaging",
        "prepare",
        _PREPARE,
        "tests/unit/test_messaging_pages.py",
        "tests/unit/test_executor.py",
        "tests/contract/test_mcp_protocol.py",
    ),
    "linkedin.messaging.message.execute": _entry(
        "messaging",
        "write",
        _WRITE,
        "tests/unit/test_messaging_pages.py",
        "tests/unit/test_executor.py",
        "tests/contract/test_mcp_protocol.py",
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
