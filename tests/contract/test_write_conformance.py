from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from tests.simulator.mcp import execute_prepared, simulator_session
from tests.simulator.state import SimulatorState


@dataclass(frozen=True, slots=True)
class WriteCase:
    case_id: str
    prepare_tool: str
    execute_tool: str
    prepare_args: dict[str, object]
    expected_action_type: str


WRITE_CASES = (
    WriteCase(
        case_id="post-create",
        prepare_tool="linkedin.posts.create.prepare",
        execute_tool="linkedin.posts.create.execute",
        prepare_args={
            "content": {
                "mode": "text",
                "text": "Hash-locked synthetic post.",
                "mentions": [],
                "link_url": None,
                "show_link_preview": True,
            }
        },
        expected_action_type="post_create",
    ),
    WriteCase(
        case_id="comment-reply",
        prepare_tool="linkedin.posts.comment.prepare",
        execute_tool="linkedin.posts.comment.execute",
        prepare_args={
            "post_ref": "activity:7312345678901234567",
            "parent_comment_ref": "comment:activity:7312345678901234567:111",
            "text": "Hash-locked synthetic reply.",
        },
        expected_action_type="comment_create",
    ),
    WriteCase(
        case_id="comment-reaction",
        prepare_tool="linkedin.posts.reaction.prepare",
        execute_tool="linkedin.posts.reaction.execute",
        prepare_args={
            "post_ref": "activity:7312345678901234567",
            "comment_ref": "comment:activity:7312345678901234567:111",
            "desired_reaction": "funny",
        },
        expected_action_type="reaction_set",
    ),
    WriteCase(
        case_id="connection-invite",
        prepare_tool="linkedin.invitations.send.prepare",
        execute_tool="linkedin.invitations.send.execute",
        prepare_args={
            "profile_slug": "sam-kim",
            "note": "Hash-locked synthetic invitation.",
        },
        expected_action_type="invitation_send",
    ),
    WriteCase(
        case_id="connection-accept",
        prepare_tool="linkedin.invitations.accept.prepare",
        execute_tool="linkedin.invitations.accept.execute",
        prepare_args={"profile_slug": "alex-ray"},
        expected_action_type="invitation_accept",
    ),
    WriteCase(
        case_id="connection-ignore",
        prepare_tool="linkedin.invitations.ignore.prepare",
        execute_tool="linkedin.invitations.ignore.execute",
        prepare_args={"profile_slug": "alex-ray"},
        expected_action_type="invitation_ignore",
    ),
    WriteCase(
        case_id="message-send",
        prepare_tool="linkedin.messaging.message.prepare",
        execute_tool="linkedin.messaging.message.execute",
        prepare_args={
            "conversation_id": "thread-123",
            "message": "Hash-locked synthetic message.",
        },
        expected_action_type="message_send",
    ),
)


@pytest.mark.parametrize("case", WRITE_CASES, ids=lambda case: case.case_id)
async def test_every_write_rejects_tampering_and_replays_one_verified_effect(
    case: WriteCase,
    tmp_path: Path,
) -> None:
    state = SimulatorState.standard()
    async with simulator_session(tmp_path, state) as session:
        prepared = await session.call_tool(
            case.prepare_tool,
            {
                "context_id": "write-conformance",
                "request_id": f"{case.case_id}-prepare",
                **case.prepare_args,
            },
        )
        assert prepared.isError is False
        assert prepared.structuredContent is not None
        content = TypeAdapter(dict[str, object]).validate_python(prepared.structuredContent)
        draft = TypeAdapter(dict[str, object]).validate_python(content["draft"])
        preview = TypeAdapter(dict[str, object]).validate_python(content["approval_preview"])
        action_id = TypeAdapter(str).validate_python(draft["action_id"])
        payload_hash = TypeAdapter(str).validate_python(draft["payload_hash"])
        assert draft["action_type"] == case.expected_action_type

        altered_hash_preview = dict(preview)
        altered_hash_preview["payload_hash"] = "b" * 64
        wrong_hash = await session.call_tool(
            case.execute_tool,
            {
                "context_id": "write-conformance",
                "request_id": f"{case.case_id}-wrong-hash",
                "action_id": action_id,
                "payload_hash": "b" * 64,
                "approval_preview": altered_hash_preview,
                "idempotency_key": f"{case.case_id}-wrong-hash",
            },
        )
        assert wrong_hash.isError is True

        altered_summary_preview = dict(preview)
        altered_summary_preview["summary"] = "Perform a different external action."
        wrong_preview = await session.call_tool(
            case.execute_tool,
            {
                "context_id": "write-conformance",
                "request_id": f"{case.case_id}-wrong-preview",
                "action_id": action_id,
                "payload_hash": payload_hash,
                "approval_preview": altered_summary_preview,
                "idempotency_key": f"{case.case_id}-wrong-preview",
            },
        )
        assert wrong_preview.isError is True
        assert state.actions == []

        first = await execute_prepared(
            session,
            execute_tool=case.execute_tool,
            prepared_content=content,
            request_id=f"{case.case_id}-execute",
            idempotency_key=f"{case.case_id}-idempotent-effect",
        )
        replay = await execute_prepared(
            session,
            execute_tool=case.execute_tool,
            prepared_content=content,
            request_id=f"{case.case_id}-replay",
            idempotency_key=f"{case.case_id}-idempotent-effect",
        )

    first_result = TypeAdapter(dict[str, object]).validate_python(first["result"])
    replay_result = TypeAdapter(dict[str, object]).validate_python(replay["result"])
    assert first_result["outcome"] == "verified"
    assert replay_result["attempt_id"] == first_result["attempt_id"]
    assert len(state.actions) == 1
