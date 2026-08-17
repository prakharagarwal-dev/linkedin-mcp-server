"""Application operation for `linkedin.posts.comments.list`."""

from __future__ import annotations

from typing import Protocol

from linkedin_mcp.app.pagination import (
    PaginationLease,
    select_page,
)
from linkedin_mcp.tools._shared.execution import OperationSupport
from linkedin_mcp.tools._shared.models import CapabilityName
from linkedin_mcp.tools.posts.comments.list.evidence import source_from_post_comments
from linkedin_mcp.tools.posts.comments.list.models import (
    CommentThread,
    PostCommentsCoverage,
    PostCommentsListInput,
    PostCommentsListOutput,
)


class PostCommentsProvider(Protocol):
    async def collect(
        self,
        request: PostCommentsListInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[CommentThread, ...], PostCommentsCoverage, str, str]: ...


class ListPostCommentsOperation(OperationSupport):
    _post_comments: PostCommentsProvider

    async def list_post_comments(
        self,
        request: PostCommentsListInput,
    ) -> PostCommentsListOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.POST_COMMENTS_LIST, request)
            threads, coverage, captured_text, source_url = await self._post_comments.collect(
                request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
            )
            page = select_page(
                threads,
                key=lambda thread: thread.comment.comment_ref,
                seen_keys=lease.seen_keys,
                page_size=self._pagination.page_capacity(lease, request.page_size),
            )
            provider_has_more = (
                page.has_lookahead or coverage.top_level_visible > coverage.top_level_returned
            )
            replies_returned = sum(len(thread.replies) for thread in page.items)
            page_coverage = coverage.model_copy(
                update={
                    "top_level_returned": len(page.items),
                    "replies_returned": replies_returned,
                    "max_comments": request.page_size,
                    "truncated": coverage.truncated or provider_has_more,
                }
            )
            source = source_from_post_comments(
                source_url=source_url,
                captured_text=captured_text,
                threads=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
                force_truncated=coverage.truncated and not provider_has_more,
            )
            return PostCommentsListOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                threads=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)
