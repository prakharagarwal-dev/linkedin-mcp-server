"""Application operations for LinkedIn posts, comments, and reactions."""

from __future__ import annotations

from typing import Protocol

from linkedin_mcp.app.pagination import PaginationLease, select_page
from linkedin_mcp.linkedin.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutput,
    ActionPageResult,
    ActionPayload,
    ActionType,
    CommentCreatePayload,
    PostCreatePayload,
    ReactionSetPayload,
)
from linkedin_mcp.linkedin.common import CapabilityName, StopReason
from linkedin_mcp.linkedin.execution import OperationSupport
from linkedin_mcp.linkedin.posts.evidence import (
    source_from_post,
    source_from_post_comments,
    source_from_post_search,
)
from linkedin_mcp.linkedin.posts.models import (
    CommentThread,
    PostCommentInput,
    PostCommentsCoverage,
    PostCommentsListInput,
    PostCommentsListOutput,
    PostCreateInput,
    PostGetInput,
    PostGetOutput,
    PostObservation,
    PostReactionInput,
    PostSearchCoverage,
    PostSearchInput,
    PostSearchOutput,
    PostSummary,
)


class PostSearchProvider(Protocol):
    async def collect(
        self,
        request: PostSearchInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[PostSummary, ...], PostSearchCoverage, str, str]: ...


class PostDetailProvider(Protocol):
    async def read(self, request: PostGetInput) -> PostObservation: ...


class PostCommentsProvider(Protocol):
    async def collect(
        self,
        request: PostCommentsListInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[CommentThread, ...], PostCommentsCoverage, str, str]: ...


class PostPublishingProvider(Protocol):
    async def inspect_post(self, request: PostCreateInput) -> ActionInspection: ...

    async def perform_post(self, command: ActionCommand) -> ActionPageResult: ...


class PostEngagementProvider(Protocol):
    async def inspect_comment(self, request: PostCommentInput) -> ActionInspection: ...

    async def perform_comment(self, command: ActionCommand) -> ActionPageResult: ...

    async def inspect_reaction(self, request: PostReactionInput) -> ActionInspection: ...

    async def perform_reaction(self, command: ActionCommand) -> ActionPageResult: ...


class PostsOperations(OperationSupport):
    _post_search: PostSearchProvider
    _post_detail: PostDetailProvider
    _post_comments: PostCommentsProvider
    _post_publishing: PostPublishingProvider
    _post_engagement: PostEngagementProvider

    async def search_posts(self, request: PostSearchInput) -> PostSearchOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.POSTS_SEARCH, request)
            posts, coverage, captured_text, source_url = await self._post_search.collect(
                request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
            )
            page = select_page(
                posts,
                key=lambda post: post.post_ref,
                seen_keys=lease.seen_keys,
                page_size=self._pagination.page_capacity(lease, request.page_size),
            )
            provider_has_more = page.has_lookahead or coverage.stop_reason in {
                StopReason.RESULT_LIMIT,
                StopReason.SAFETY_BOUND,
            }
            page_coverage = coverage.model_copy(
                update={
                    "result_count": len(page.items),
                    "max_results": request.page_size,
                    "stop_reason": (
                        StopReason.RESULT_LIMIT if provider_has_more else coverage.stop_reason
                    ),
                }
            )
            source = source_from_post_search(
                source_url=source_url,
                captured_text=captured_text,
                posts=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
            )
            return PostSearchOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                posts=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def get_post(self, request: PostGetInput) -> PostGetOutput:
        post = await self._post_detail.read(request)
        source = source_from_post(post)
        return PostGetOutput(
            context_id=request.context_id,
            request_id=request.request_id,
            post=post,
            sources=(source,),
        )

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
            inspect=lambda: self._post_engagement.inspect_comment(request),
            perform=self._post_engagement.perform_comment,
        )

    async def react_to_post(self, request: PostReactionInput) -> ActionOutput:
        def payload_factory(inspection: ActionInspection) -> ActionPayload:
            if inspection.existing_reaction is None:
                raise RuntimeError("Reaction inspection captured no visible reaction state.")
            return ReactionSetPayload(
                post_ref=request.post_ref,
                existing_reaction=inspection.existing_reaction,
                desired_reaction=request.desired_reaction,
            )

        return await self._run_action(
            capability_name=CapabilityName.POST_REACT,
            request=request,
            action_type=ActionType.REACTION_SET,
            payload_factory=payload_factory,
            inspect=lambda: self._post_engagement.inspect_reaction(request),
            perform=self._post_engagement.perform_reaction,
        )
