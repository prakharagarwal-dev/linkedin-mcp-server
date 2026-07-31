"""State-mutating provider adapter for full MCP workflow tests."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import HttpUrl

from linkedin_mcp.domain.models import (
    ActionDraft,
    ActionPageResult,
    CommentCreatePayload,
    InvitationAcceptPayload,
    InvitationIgnorePayload,
    InvitationSendPayload,
    JobSearchCoverage,
    JobSearchInput,
    JobSummary,
    MessageSendPayload,
    PostCreatePayload,
    ReactionSetPayload,
    StopReason,
)
from tests.contract.test_mcp_protocol import ProtocolNetwork
from tests.simulator.state import SimulatorState


class StatefulProtocolJobSearch:
    """Project simulator jobs through the real paginated provider contract."""

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
    """Reuse contract observations while applying writes to typed simulator state."""

    def __init__(self, state: SimulatorState) -> None:
        self.state = state

    async def execute_send(self, draft: ActionDraft) -> ActionPageResult:
        payload = draft.payload
        if not isinstance(payload, InvitationSendPayload):
            raise TypeError("The simulator received a non-invitation draft.")
        profile_slug = draft.target.profile_slug
        self.state.send_invitation(profile_slug, payload.note)
        return self._result("pending_sent")

    async def execute_accept(self, draft: ActionDraft) -> ActionPageResult:
        payload = draft.payload
        if not isinstance(payload, InvitationAcceptPayload):
            raise TypeError("The simulator received a non-acceptance draft.")
        self.state.accept_invitation(payload.invitation_ref)
        return self._result("connected")

    async def execute_ignore(self, draft: ActionDraft) -> ActionPageResult:
        payload = draft.payload
        if not isinstance(payload, InvitationIgnorePayload):
            raise TypeError("The simulator received a non-ignore draft.")
        self.state.ignore_invitation(payload.invitation_ref)
        return self._result("invitation_ignored")

    async def execute_message(self, draft: ActionDraft) -> ActionPageResult:
        payload = draft.payload
        if not isinstance(payload, MessageSendPayload):
            raise TypeError("The simulator received a non-message draft.")
        conversation_id = draft.target.conversation_id
        if conversation_id is None:
            raise ValueError("The simulated message target has no conversation identity.")
        visible_content = payload.message
        if visible_content is None and payload.gif is not None:
            visible_content = payload.gif.result_title
        if visible_content is None:
            visible_content = ", ".join(payload.attachment_refs)
        self.state.send_message(conversation_id, visible_content)
        return self._result("message_sent")

    async def execute_post(self, draft: ActionDraft) -> ActionPageResult:
        payload = draft.payload
        if not isinstance(payload, PostCreatePayload):
            raise TypeError("The simulator received a non-post draft.")
        text = payload.content.text
        if text is None:
            text = f"Structured {payload.content.mode.value} post"
        post = self.state.create_post(text)
        return self._result(f"post_published:{post.post_ref}")

    async def execute_comment(self, draft: ActionDraft) -> ActionPageResult:
        payload = draft.payload
        if not isinstance(payload, CommentCreatePayload):
            raise TypeError("The simulator received a non-comment draft.")
        text = payload.text
        if text is None and payload.attachment is not None:
            text = payload.attachment.attachment_type.value
        if text is None:
            raise ValueError("The simulated comment has no visible content.")
        comment = self.state.create_comment(
            payload.post_ref,
            text,
            parent_comment_ref=payload.parent_comment_ref,
        )
        prefix = "reply_published" if payload.parent_comment_ref else "comment_published"
        return self._result(f"{prefix}:{comment.comment_ref}")

    async def execute_reaction(self, draft: ActionDraft) -> ActionPageResult:
        payload = draft.payload
        if not isinstance(payload, ReactionSetPayload):
            raise TypeError("The simulator received a non-reaction draft.")
        self.state.set_reaction(
            payload.post_ref,
            payload.desired_reaction,
            comment_ref=payload.comment_ref,
        )
        return self._result(f"reaction_set:{payload.desired_reaction.value}")
