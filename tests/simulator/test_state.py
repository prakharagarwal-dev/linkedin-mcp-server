from __future__ import annotations

import pytest

from linkedin_mcp.linkedin.models import MessageDirection, ReactionState
from tests.simulator.state import SimulatorFault, SimulatorState


def test_standard_state_supports_deterministic_cross_domain_searches() -> None:
    state = SimulatorState.standard()

    assert [job.job_id for job in state.search_jobs("python")] == ["4100000001"]
    assert [person.profile_slug for person in state.search_people("engineer")] == [
        "jane-doe",
        "alex-ray",
        "sam-kim",
    ]
    assert [
        person.profile_slug for person in state.search_people("engineer", company_slug="acme-cloud")
    ] == ["jane-doe", "alex-ray"]
    assert [company.company_slug for company in state.search_companies("infrastructure")] == [
        "acme-cloud"
    ]
    assert [post.post_ref for post in state.search_posts("reliability")] == [
        "activity:7312345678901234567"
    ]


def test_network_and_messaging_transitions_are_stateful_and_exact() -> None:
    state = SimulatorState.standard()

    invitation = state.send_invitation("sam-kim", "Would you like to connect?")
    assert invitation.direction == "sent"
    assert state.actions[-1].target_ref == "sam-kim"

    received_ref = "invitation:" + "a" * 24
    state.accept_invitation(received_ref)
    assert "alex-ray" in state.connections
    assert received_ref not in state.invitations

    message = state.send_message("thread-123", "Thanks—happy to discuss.")
    assert message.direction is MessageDirection.OUTGOING
    assert state.conversations["thread-123"].messages[-1] == message
    assert [action.action_type for action in state.actions] == [
        "invitation_send",
        "invitation_accept",
        "message_send",
    ]


def test_ignoring_an_invitation_removes_only_the_pending_request() -> None:
    state = SimulatorState.standard()
    received_ref = "invitation:" + "a" * 24

    state.ignore_invitation(received_ref)

    assert received_ref not in state.invitations
    assert "alex-ray" not in state.connections
    assert state.actions[-1].action_type == "invitation_ignore"
    assert state.actions[-1].target_ref == "alex-ray"


def test_post_comment_and_reaction_transitions_preserve_post_targets() -> None:
    state = SimulatorState.standard()
    post = state.create_post("A synthetic personal post.")
    comment = state.create_comment(post.post_ref, "First comment.")
    state.set_reaction(post.post_ref, ReactionState.CELEBRATE)

    stored = state.posts[post.post_ref]
    assert stored.comments == [comment]
    assert stored.reaction is ReactionState.CELEBRATE
    assert [action.target_ref for action in state.actions] == [
        post.post_ref,
        comment.comment_ref,
        post.post_ref,
    ]


def test_state_fails_closed_for_ambiguous_or_stale_targets() -> None:
    state = SimulatorState.standard()

    with pytest.raises(ValueError, match="already connected"):
        state.send_invitation("jane-doe", None)
    with pytest.raises(ValueError, match="exact received invitation"):
        state.accept_invitation("invitation:" + "f" * 24)
    with pytest.raises(KeyError):
        state.send_message("missing-thread", "Do not send")
    with pytest.raises(KeyError):
        state.create_comment("activity:9999999999999999999", "Do not publish")

    assert state.actions == []


def test_fault_plan_is_ordered_and_consumed_once() -> None:
    state = SimulatorState.standard()
    state.queue_fault("messaging.send", SimulatorFault.EFFECT_INTERRUPTED)
    state.queue_fault("messaging.send", SimulatorFault.VERIFICATION_TIMEOUT)

    assert state.take_fault("messaging.send") is SimulatorFault.EFFECT_INTERRUPTED
    assert state.take_fault("messaging.send") is SimulatorFault.VERIFICATION_TIMEOUT
    assert state.take_fault("messaging.send") is None
