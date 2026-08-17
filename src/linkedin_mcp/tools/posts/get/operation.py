"""Application operation for `linkedin.posts.get`."""

from __future__ import annotations

from typing import Protocol

from linkedin_mcp.tools._shared.execution import OperationSupport
from linkedin_mcp.tools.posts.get.evidence import source_from_post
from linkedin_mcp.tools.posts.get.models.post_get_input import PostGetInput
from linkedin_mcp.tools.posts.get.models.post_get_output import PostGetOutput
from linkedin_mcp.tools.posts.get.models.post_observation import PostObservation


class PostDetailProvider(Protocol):
    async def read(self, request: PostGetInput) -> PostObservation: ...


class GetPostOperation(OperationSupport):
    _post_detail: PostDetailProvider

    async def get_post(self, request: PostGetInput) -> PostGetOutput:
        post = await self._post_detail.read(request)
        source = source_from_post(post)
        return PostGetOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            post=post,
            sources=(source,),
        )
