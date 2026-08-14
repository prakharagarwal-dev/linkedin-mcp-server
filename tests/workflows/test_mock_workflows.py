"""Core cross-capability workflows through the real MCP protocol."""

from __future__ import annotations

from pathlib import Path

from tests.simulator.mcp import simulator_session
from tests.simulator.state import SimulatorJob, SimulatorState


async def test_find_job_then_message_a_connection(tmp_path: Path) -> None:
    state = SimulatorState.standard()
    state.jobs["4100000099"] = SimulatorJob(
        job_id="4100000099",
        title="Python Platform Engineer",
        company_slug="acme-cloud",
        company_name="Acme Cloud",
        location="Remote",
        description="Build Python platforms.",
        easy_apply=True,
    )
    async with simulator_session(tmp_path, state) as session:
        jobs = await session.call_tool(
            "linkedin.jobs.search",
            {
                "context_id": "job-outreach",
                "request_id": "find-job",
                "query": "Python",
                "page_size": 10,
            },
        )
        assert jobs.isError is False
        assert jobs.structuredContent is not None
        assert jobs.structuredContent["jobs"]

        message = await session.call_tool(
            "linkedin.messaging.send",
            {
                "context_id": "job-outreach",
                "request_id": "send-message",
                "conversation_id": "thread-123",
                "message": "I found the role and would value your perspective.",
            },
        )
        assert message.isError is False
        assert (
            state.conversations["thread-123"].messages[-1].text
            == "I found the role and would value your perspective."
        )


async def test_publish_engage_and_manage_invitations(tmp_path: Path) -> None:
    state = SimulatorState.standard()
    async with simulator_session(tmp_path, state) as session:
        post = await session.call_tool(
            "linkedin.posts.create",
            {
                "context_id": "network-workflow",
                "request_id": "create-post",
                "content": {"mode": "text", "text": "A reliable atomic workflow."},
            },
        )
        assert post.isError is False
        created = max(state.posts.values(), key=lambda item: item.post_ref)

        comment = await session.call_tool(
            "linkedin.posts.comment",
            {
                "context_id": "network-workflow",
                "request_id": "comment",
                "post_ref": created.post_ref,
                "text": "Thanks for reading.",
            },
        )
        reaction = await session.call_tool(
            "linkedin.posts.react",
            {
                "context_id": "network-workflow",
                "request_id": "react",
                "post_ref": created.post_ref,
                "desired_reaction": "like",
            },
        )
        invitation = await session.call_tool(
            "linkedin.invitations.send",
            {
                "context_id": "network-workflow",
                "request_id": "invite",
                "profile_slug": "sam-kim",
            },
        )
        assert comment.isError is False
        assert reaction.isError is False
        assert invitation.isError is False
        assert created.comments[-1].text == "Thanks for reading."
        assert created.reaction.value == "like"
        assert any(
            item.profile_slug == "sam-kim" and item.direction == "sent"
            for item in state.invitations.values()
        )
