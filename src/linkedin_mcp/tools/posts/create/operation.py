"""Application operation for `linkedin.posts.create`."""

from __future__ import annotations

from typing import Protocol

from linkedin_mcp.tools._shared.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutput,
    ActionPageResult,
    ActionType,
    PostCreatePayload,
)
from linkedin_mcp.tools._shared.execution import OperationSupport
from linkedin_mcp.tools._shared.models import CapabilityName
from linkedin_mcp.tools.posts.create.models.post_create_input import PostCreateInput


class PostPublishingProvider(Protocol):
    async def inspect_post(self, request: PostCreateInput) -> ActionInspection: ...

    async def perform_post(self, command: ActionCommand) -> ActionPageResult: ...


class CreatePostOperation(OperationSupport):
    _post_publishing: PostPublishingProvider

    async def create_post(self, request: PostCreateInput) -> ActionOutput:
        return await self._run_action(
            capability_name=CapabilityName.POSTS_CREATE,
            request=request,
            action_type=ActionType.POST_CREATE,
            payload=PostCreatePayload(
                content=request.content,
                audience=request.audience,
                group_target=request.group_target,
                comment_control=request.comment_control,
                brand_partnership=request.brand_partnership,
                collaborators=request.collaborators,
                scheduled_at=request.scheduled_at,
            ),
            inspect=lambda: self._post_publishing.inspect_post(request),
            perform=self._post_publishing.perform_post,
        )
