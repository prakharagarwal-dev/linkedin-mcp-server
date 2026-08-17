"""Application operation for `linkedin.posts.comment`."""

from __future__ import annotations

from typing import Protocol

from linkedin_mcp.tools._shared.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutput,
    ActionPageResult,
    ActionType,
    CommentCreatePayload,
)
from linkedin_mcp.tools._shared.execution import OperationSupport
from linkedin_mcp.tools._shared.models import CapabilityName
from linkedin_mcp.tools.posts.comment.models.post_comment_input import PostCommentInput


class PostCommentProvider(Protocol):
    async def inspect_comment(self, request: PostCommentInput) -> ActionInspection: ...

    async def perform_comment(self, command: ActionCommand) -> ActionPageResult: ...


class CommentPostOperation(OperationSupport):
    _post_comment: PostCommentProvider

    async def comment_on_post(self, request: PostCommentInput) -> ActionOutput:
        return await self._run_action(
            capability_name=CapabilityName.POST_COMMENT,
            request=request,
            action_type=ActionType.COMMENT_CREATE,
            payload=CommentCreatePayload(
                post_ref=request.post_ref,
                text=request.text,
                mentions=request.mentions,
                attachment=request.attachment,
            ),
            inspect=lambda: self._post_comment.inspect_comment(request),
            perform=self._post_comment.perform_comment,
        )
