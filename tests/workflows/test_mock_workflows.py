from __future__ import annotations

from pathlib import Path

from pydantic import TypeAdapter

from tests.simulator.mcp import execute_prepared, simulator_session
from tests.simulator.state import SimulatorJob, SimulatorState


async def test_job_research_and_referral_workflow_uses_public_mcp_tools(tmp_path: Path) -> None:
    state = SimulatorState.standard()
    async with simulator_session(tmp_path, state) as session:
        jobs = await session.call_tool(
            "linkedin.jobs.search",
            {
                "context_id": "mock-workflow",
                "request_id": "jobs-search",
                "query": "python",
                "max_results": 5,
            },
        )
        assert jobs.isError is False and jobs.structuredContent is not None
        job_id = TypeAdapter(str).validate_python(jobs.structuredContent["jobs"][0]["job_id"])

        job = await session.call_tool(
            "linkedin.jobs.get",
            {
                "context_id": "mock-workflow",
                "request_id": "job-get",
                "job_id": job_id,
            },
        )
        companies = await session.call_tool(
            "linkedin.companies.search",
            {
                "context_id": "mock-workflow",
                "request_id": "company-search",
                "query": "Acme",
            },
        )
        employees = await session.call_tool(
            "linkedin.people.search",
            {
                "context_id": "mock-workflow",
                "request_id": "employees-search",
                "query": "engineer",
                "filters": {"current_company_names": ["Acme Cloud"]},
            },
        )
        profile = await session.call_tool(
            "linkedin.people.get",
            {
                "context_id": "mock-workflow",
                "request_id": "profile-get",
                "profile_slug": "jane-doe",
                "sections": ["overview", "about"],
            },
        )
        assert all(
            not result.isError
            for result in (
                job,
                companies,
                employees,
                profile,
            )
        )

        prepared = await session.call_tool(
            "linkedin.invitations.send.prepare",
            {
                "context_id": "mock-workflow",
                "request_id": "invite-prepare",
                "profile_slug": "sam-kim",
                "note": "I would like to discuss the Python role.",
            },
        )
        assert prepared.isError is False and prepared.structuredContent is not None
        await execute_prepared(
            session,
            execute_tool="linkedin.invitations.send.execute",
            prepared_content=TypeAdapter(dict[str, object]).validate_python(
                prepared.structuredContent
            ),
            request_id="invite-execute",
            idempotency_key="mock-referral-invite-1",
        )

    assert any(
        invitation.profile_slug == "sam-kim" and invitation.direction == "sent"
        for invitation in state.invitations.values()
    )
    assert state.actions[-1].action_type == "invitation_send"


async def test_job_search_walks_three_cursor_pages_through_public_mcp(tmp_path: Path) -> None:
    state = SimulatorState.standard()
    state.jobs["4100000002"] = SimulatorJob(
        job_id="4100000002",
        title="Python Platform Engineer",
        company_slug="acme-cloud",
        company_name="Acme Cloud",
        location="Bengaluru, India",
        description="Build Python platform services.",
    )
    state.jobs["4100000003"] = SimulatorJob(
        job_id="4100000003",
        title="Python Reliability Engineer",
        company_slug="acme-cloud",
        company_name="Acme Cloud",
        location="Remote",
        description="Improve Python service reliability.",
    )

    async with simulator_session(tmp_path, state) as session:
        first = await session.call_tool(
            "linkedin.jobs.search",
            {
                "context_id": "pagination-workflow",
                "request_id": "jobs-page-1",
                "query": "python",
                "page_size": 1,
            },
        )
        assert first.isError is False and first.structuredContent is not None
        first_pagination = TypeAdapter(dict[str, object]).validate_python(
            first.structuredContent["pagination"]
        )
        first_cursor = TypeAdapter(str).validate_python(first_pagination["next_cursor"])

        second = await session.call_tool(
            "linkedin.jobs.search",
            {
                "context_id": "pagination-workflow",
                "request_id": "jobs-page-2",
                "query": "python",
                "page_size": 1,
                "cursor": first_cursor,
            },
        )
        assert second.isError is False and second.structuredContent is not None
        second_pagination = TypeAdapter(dict[str, object]).validate_python(
            second.structuredContent["pagination"]
        )
        second_cursor = TypeAdapter(str).validate_python(second_pagination["next_cursor"])

        stale = await session.call_tool(
            "linkedin.jobs.search",
            {
                "context_id": "pagination-workflow",
                "request_id": "jobs-stale-cursor",
                "query": "python",
                "page_size": 1,
                "cursor": first_cursor,
            },
        )
        assert stale.isError is True

        third = await session.call_tool(
            "linkedin.jobs.search",
            {
                "context_id": "pagination-workflow",
                "request_id": "jobs-page-3",
                "query": "python",
                "page_size": 1,
                "cursor": second_cursor,
            },
        )
        assert third.isError is False and third.structuredContent is not None

    pages = (first, second, third)
    job_ids = [
        TypeAdapter(str).validate_python(page.structuredContent["jobs"][0]["job_id"])
        for page in pages
        if page.structuredContent is not None
    ]
    assert job_ids == ["4100000001", "4100000002", "4100000003"]
    assert len(set(job_ids)) == 3
    assert first_pagination["has_more"] is True
    assert second_pagination["has_more"] is True
    assert third.structuredContent["pagination"]["has_more"] is False
    assert third.structuredContent["pagination"]["next_cursor"] is None


async def test_accept_and_bidirectional_message_workflow_is_stateful(tmp_path: Path) -> None:
    state = SimulatorState.standard()
    async with simulator_session(tmp_path, state) as session:
        invitations = await session.call_tool(
            "linkedin.invitations.list",
            {
                "context_id": "mock-workflow",
                "request_id": "invitations-list",
                "direction": "received",
            },
        )
        connections = await session.call_tool(
            "linkedin.connections.list",
            {
                "context_id": "mock-workflow",
                "request_id": "connections-list",
            },
        )
        network_search = await session.call_tool(
            "linkedin.connections.search",
            {
                "context_id": "mock-workflow",
                "request_id": "connections-search",
                "filters": {
                    "title": "Staff Engineer",
                },
            },
        )
        assert invitations.isError is False
        assert connections.isError is False
        assert network_search.isError is False
        assert network_search.structuredContent is not None
        assert network_search.structuredContent["people"][0]["profile_slug"] == "jane-doe"

        accept = await session.call_tool(
            "linkedin.invitations.accept.prepare",
            {
                "context_id": "mock-workflow",
                "request_id": "accept-prepare",
                "profile_slug": "alex-ray",
            },
        )
        assert accept.isError is False and accept.structuredContent is not None
        await execute_prepared(
            session,
            execute_tool="linkedin.invitations.accept.execute",
            prepared_content=TypeAdapter(dict[str, object]).validate_python(
                accept.structuredContent
            ),
            request_id="accept-execute",
            idempotency_key="mock-accept-1",
        )

        inbox = await session.call_tool(
            "linkedin.messaging.search",
            {
                "context_id": "mock-workflow",
                "request_id": "inbox-list",
                "query": "Jane",
            },
        )
        conversation = await session.call_tool(
            "linkedin.messaging.conversation.get",
            {
                "context_id": "mock-workflow",
                "request_id": "conversation-get",
                "conversation_id": "thread-123",
            },
        )
        assert inbox.isError is False
        assert conversation.isError is False

        message = await session.call_tool(
            "linkedin.messaging.message.prepare",
            {
                "context_id": "mock-workflow",
                "request_id": "message-prepare",
                "conversation_id": "thread-123",
                "message": "Thanks—happy to discuss the role.",
            },
        )
        assert message.isError is False and message.structuredContent is not None
        await execute_prepared(
            session,
            execute_tool="linkedin.messaging.message.execute",
            prepared_content=TypeAdapter(dict[str, object]).validate_python(
                message.structuredContent
            ),
            request_id="message-execute",
            idempotency_key="mock-message-1",
        )

    assert "alex-ray" in state.connections
    assert all(invitation.profile_slug != "alex-ray" for invitation in state.invitations.values())
    assert state.conversations["thread-123"].messages[-1].text == (
        "Thanks—happy to discuss the role."
    )


async def test_ignore_received_connection_request_workflow_is_stateful(
    tmp_path: Path,
) -> None:
    state = SimulatorState.standard()
    received_ref = "invitation:" + "a" * 24
    async with simulator_session(tmp_path, state) as session:
        prepared = await session.call_tool(
            "linkedin.invitations.ignore.prepare",
            {
                "context_id": "mock-ignore-workflow",
                "request_id": "ignore-prepare",
                "profile_slug": "alex-ray",
            },
        )
        assert prepared.isError is False and prepared.structuredContent is not None
        result = await execute_prepared(
            session,
            execute_tool="linkedin.invitations.ignore.execute",
            prepared_content=TypeAdapter(dict[str, object]).validate_python(
                prepared.structuredContent
            ),
            request_id="ignore-execute",
            idempotency_key="mock-ignore-1",
        )

    result_payload = TypeAdapter(dict[str, object]).validate_python(result["result"])
    assert result_payload["final_state"] == "invitation_ignored"
    assert received_ref not in state.invitations
    assert "alex-ray" not in state.connections
    assert state.actions[-1].action_type == "invitation_ignore"


async def test_post_create_reply_and_comment_reaction_workflow_is_stateful(
    tmp_path: Path,
) -> None:
    state = SimulatorState.standard()
    post_ref = "activity:7312345678901234567"
    parent_ref = "comment:activity:7312345678901234567:111"
    async with simulator_session(tmp_path, state) as session:
        post_search = await session.call_tool(
            "linkedin.posts.search",
            {
                "context_id": "mock-workflow",
                "request_id": "posts-search",
                "query": "python",
            },
        )
        post = await session.call_tool(
            "linkedin.posts.get",
            {
                "context_id": "mock-workflow",
                "request_id": "post-get",
                "post_ref": post_ref,
            },
        )
        comments = await session.call_tool(
            "linkedin.posts.comments.list",
            {
                "context_id": "mock-workflow",
                "request_id": "comments-list",
                "post_ref": post_ref,
            },
        )
        company_posts = await session.call_tool(
            "linkedin.posts.search",
            {
                "context_id": "mock-workflow",
                "request_id": "company-posts",
                "filters": {"author_company_names": ["Acme Cloud"]},
            },
        )
        assert all(
            not result.isError
            for result in (
                post_search,
                post,
                comments,
                company_posts,
            )
        )

        create = await session.call_tool(
            "linkedin.posts.create.prepare",
            {
                "context_id": "mock-workflow",
                "request_id": "post-create-prepare",
                "content": {
                    "mode": "text",
                    "text": "A synthetic personal post.",
                    "mentions": [],
                    "link_url": None,
                    "show_link_preview": True,
                },
            },
        )
        assert create.isError is False and create.structuredContent is not None
        await execute_prepared(
            session,
            execute_tool="linkedin.posts.create.execute",
            prepared_content=TypeAdapter(dict[str, object]).validate_python(
                create.structuredContent
            ),
            request_id="post-create-execute",
            idempotency_key="mock-post-create-1",
        )

        reply = await session.call_tool(
            "linkedin.posts.comment.prepare",
            {
                "context_id": "mock-workflow",
                "request_id": "reply-prepare",
                "post_ref": post_ref,
                "parent_comment_ref": parent_ref,
                "text": "Thanks for sharing this.",
            },
        )
        assert reply.isError is False and reply.structuredContent is not None
        await execute_prepared(
            session,
            execute_tool="linkedin.posts.comment.execute",
            prepared_content=TypeAdapter(dict[str, object]).validate_python(
                reply.structuredContent
            ),
            request_id="reply-execute",
            idempotency_key="mock-reply-1",
        )

        reaction = await session.call_tool(
            "linkedin.posts.reaction.prepare",
            {
                "context_id": "mock-workflow",
                "request_id": "reaction-prepare",
                "post_ref": post_ref,
                "comment_ref": parent_ref,
                "desired_reaction": "funny",
            },
        )
        assert reaction.isError is False and reaction.structuredContent is not None
        await execute_prepared(
            session,
            execute_tool="linkedin.posts.reaction.execute",
            prepared_content=TypeAdapter(dict[str, object]).validate_python(
                reaction.structuredContent
            ),
            request_id="reaction-execute",
            idempotency_key="mock-reaction-1",
        )

    created_posts = [
        candidate for candidate in state.posts.values() if candidate.author_slug == state.actor_slug
    ]
    assert [candidate.text for candidate in created_posts] == ["A synthetic personal post."]
    assert state.posts[post_ref].comments[-1].parent_comment_ref == parent_ref
    parent = next(
        comment for comment in state.posts[post_ref].comments if comment.comment_ref == parent_ref
    )
    assert parent.reaction.value == "funny"
