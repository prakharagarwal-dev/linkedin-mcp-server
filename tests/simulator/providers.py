"""State-mutating providers for offline MCP workflow tests."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import HttpUrl

from linkedin_mcp.tools._shared.actions import (
    ActionCommand,
    ActionPageResult,
    CommentCreatePayload,
    InvitationAcceptPayload,
    InvitationIgnorePayload,
    InvitationSendPayload,
    MessageSendPayload,
    PostCreatePayload,
    ReactionSetPayload,
)
from linkedin_mcp.tools._shared.models import StopReason
from linkedin_mcp.tools.jobs.search.models import (
    JobSearchCoverage,
    JobSearchInput,
    JobSummary,
)
from tests.contract.test_mcp_protocol import ProtocolNetwork
from tests.simulator.state import SimulatorState


class StatefulProtocolJobSearch:
    def __init__(self, state: SimulatorState) -> None:
        self.state = state

    async def collect(
        self,
        request: JobSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[JobSummary, ...], JobSearchCoverage, str, str]:
        matches = self.state.search_jobs(request.query)
        limit = request.page_size if result_limit is None else result_limit
        visible = matches[:limit]
        jobs = tuple(
            JobSummary(
                job_id=job.job_id,
                job_url=HttpUrl(f"https://www.linkedin.com/jobs/view/{job.job_id}/"),
                title=job.title,
                company_name=job.company_name,
                location=job.location,
                easy_apply=job.easy_apply,
                visible_text=f"{job.title}\n{job.company_name}\n{job.location}",
            )
            for job in visible
        )
        return (
            jobs,
            JobSearchCoverage(
                query=request.query,
                location=request.location,
                freshness_hours=request.freshness_hours,
                filters=request.filters,
                pages_visited=1,
                result_count=len(jobs),
                max_results=limit,
                stop_reason=(
                    StopReason.RESULT_LIMIT
                    if len(visible) < len(matches)
                    else StopReason.VISIBLE_PAGE_COMPLETE
                ),
                captured_at=datetime.now(UTC),
            ),
            "\n\n".join(job.visible_text for job in jobs) or "No visible matching jobs.",
            "https://www.linkedin.com/jobs/search/?keywords=python",
        )


class StatefulProtocolNetwork(ProtocolNetwork):
    def __init__(self, state: SimulatorState) -> None:
        self.state = state

    async def perform_send(self, command: ActionCommand) -> ActionPageResult:
        payload = command.payload
        if not isinstance(payload, InvitationSendPayload):
            raise TypeError("Expected an invitation-send command.")
        self.state.send_invitation(command.target.profile_slug, payload.note)
        return self._result("pending_sent")

    async def perform_accept(self, command: ActionCommand) -> ActionPageResult:
        payload = command.payload
        if not isinstance(payload, InvitationAcceptPayload):
            raise TypeError("Expected an invitation-accept command.")
        self.state.accept_invitation(payload.invitation_ref)
        return self._result("connected")

    async def perform_ignore(self, command: ActionCommand) -> ActionPageResult:
        payload = command.payload
        if not isinstance(payload, InvitationIgnorePayload):
            raise TypeError("Expected an invitation-ignore command.")
        self.state.ignore_invitation(payload.invitation_ref)
        return self._result("invitation_ignored")

    async def perform_message(self, command: ActionCommand) -> ActionPageResult:
        payload = command.payload
        if not isinstance(payload, MessageSendPayload):
            raise TypeError("Expected a message-send command.")
        conversation_id = command.target.conversation_id
        if conversation_id is None:
            raise ValueError("The simulated target has no conversation identity.")
        content = payload.message
        if content is None and payload.gif is not None:
            content = payload.gif.result_title
        if content is None:
            content = ", ".join(payload.attachment_refs)
        self.state.send_message(conversation_id, content)
        return self._result("message_sent")

    async def perform_post(self, command: ActionCommand) -> ActionPageResult:
        payload = command.payload
        if not isinstance(payload, PostCreatePayload):
            raise TypeError("Expected a post-create command.")
        text = payload.content.text or f"Structured {payload.content.mode.value} post"
        post = self.state.create_post(text)
        return self._result(f"post_published:{post.post_ref}")

    async def perform_comment(self, command: ActionCommand) -> ActionPageResult:
        payload = command.payload
        if not isinstance(payload, CommentCreatePayload):
            raise TypeError("Expected a comment-create command.")
        text = payload.text
        if text is None and payload.attachment is not None:
            text = payload.attachment.attachment_type.value
        if text is None:
            raise ValueError("The simulated comment has no content.")
        comment = self.state.create_comment(payload.post_ref, text)
        return self._result(f"comment_published:{comment.comment_ref}")

    async def perform_reaction(self, command: ActionCommand) -> ActionPageResult:
        payload = command.payload
        if not isinstance(payload, ReactionSetPayload):
            raise TypeError("Expected a reaction-set command.")
        self.state.set_reaction(payload.post_ref, payload.desired_reaction)
        return self._result(f"reaction_set:{payload.desired_reaction.value}")
