"""The explicit public-tool contract for scheduled live validation."""

from __future__ import annotations

from tests.verification_manifest import MOCK_VERIFICATION

INVITATION_MUTATION_TOOLS: frozenset[str] = frozenset(
    {
        "linkedin.invitations.send.prepare",
        "linkedin.invitations.send.execute",
        "linkedin.invitations.accept.prepare",
        "linkedin.invitations.accept.execute",
        "linkedin.invitations.ignore.prepare",
        "linkedin.invitations.ignore.execute",
    }
)

LIVE_REQUIRED_TOOLS: frozenset[str] = frozenset(MOCK_VERIFICATION) - INVITATION_MUTATION_TOOLS

LIVE_EXECUTE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "linkedin.posts.create.execute",
        "linkedin.posts.comment.execute",
        "linkedin.posts.reaction.execute",
        "linkedin.messaging.message.execute",
    }
)

LIVE_ALLOWED_SCOPES: tuple[str, ...] = (
    "linkedin.jobs.search",
    "linkedin.jobs.read",
    "linkedin.people.search",
    "linkedin.people.read",
    "linkedin.companies.search",
    "linkedin.companies.read",
    "linkedin.posts.search",
    "linkedin.posts.read",
    "linkedin.posts.comments.read",
    "linkedin.posts.create",
    "linkedin.posts.comments.create",
    "linkedin.posts.reactions.set",
    "linkedin.invitations.read",
    "linkedin.connections.read",
    "linkedin.messaging.read",
    "linkedin.messaging.send",
)

LIVE_STATUS_ORDER: dict[str, int] = {
    "passed": 0,
    "simulator_only": 1,
    "skipped": 2,
    "blocked": 3,
    "failed": 4,
}


def all_public_tools() -> frozenset[str]:
    """Return the complete public tool inventory owned by offline verification."""

    return frozenset(MOCK_VERIFICATION)
