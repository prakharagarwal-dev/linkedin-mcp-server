"""Compact conformance coverage for every current account-changing tool."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from tests.simulator.mcp import simulator_session
from tests.simulator.state import SimulatorState


@dataclass(frozen=True, slots=True)
class ActionCase:
    tool: str
    arguments: dict[str, object]
    expected_state: str


CASES = (
    ActionCase(
        "linkedin.posts.create",
        {"content": {"mode": "text", "text": "Conformance post"}},
        "post_published:",
    ),
    ActionCase(
        "linkedin.posts.comment",
        {"post_ref": "activity:7312345678901234567", "text": "Conformance comment"},
        "comment_published:",
    ),
    ActionCase(
        "linkedin.posts.react",
        {"post_ref": "activity:7312345678901234567", "desired_reaction": "support"},
        "reaction_set:support",
    ),
    ActionCase(
        "linkedin.invitations.send",
        {"profile_slug": "sam-kim", "note": "Conformance invitation"},
        "pending_sent",
    ),
    ActionCase(
        "linkedin.invitations.accept",
        {"profile_slug": "alex-ray"},
        "connected",
    ),
    ActionCase(
        "linkedin.invitations.ignore",
        {"profile_slug": "alex-ray"},
        "invitation_ignored",
    ),
    ActionCase(
        "linkedin.messaging.send",
        {"conversation_id": "thread-123", "message": "Conformance message"},
        "message_sent",
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.tool)
async def test_action_tool_is_atomic_and_returns_a_terminal_result(
    tmp_path: Path,
    case: ActionCase,
) -> None:
    state = SimulatorState.standard()
    async with simulator_session(tmp_path, state) as session:
        result = await session.call_tool(
            case.tool,
            {
                "context_id": "write-conformance",
                "request_id": case.tool.replace(".", "-"),
                **case.arguments,
            },
        )
        assert result.isError is False
        assert result.structuredContent is not None
        content = TypeAdapter(dict[str, object]).validate_python(result.structuredContent)
        action_result = TypeAdapter(dict[str, object]).validate_python(content["result"])
        assert action_result["outcome"] == "verified"
        assert action_result["performed"] is True
        assert str(action_result["final_state"]).startswith(case.expected_state)
        assert content["sources"]
