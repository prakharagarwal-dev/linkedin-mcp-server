"""Pagination and output construction for `linkedin.posts.comments.list`."""

from __future__ import annotations

from linkedin_mcp.mcp.context import current_client_id
from linkedin_mcp.pagination import (
    PaginationManager,
    select_page,
)
from linkedin_mcp.tools._shared.models import CapabilityName
from linkedin_mcp.tools.posts.comments.list.evidence import source_from_post_comments
from linkedin_mcp.tools.posts.comments.list.models.post_comments_list_input import (
    PostCommentsListInput,
)
from linkedin_mcp.tools.posts.comments.list.models.post_comments_list_output import (
    PostCommentsListOutput,
)
from linkedin_mcp.tools.posts.comments.list.page import PostCommentsPage


async def execute(
    request: PostCommentsListInput,
    *,
    page: PostCommentsPage,
    pagination: PaginationManager,
    account_id: str,
) -> PostCommentsListOutput:
    state = await pagination.start(
        account_id=account_id,
        client_id=current_client_id(),
        capability_name=CapabilityName.POST_COMMENTS_LIST,
        request=request,
    )
    threads, coverage, captured_text, source_url = await page.collect(
        request,
        result_limit=pagination.traversal_limit(state, request.page_size),
    )
    selected = select_page(
        threads,
        key=lambda thread: thread.comment.comment_ref,
        seen_keys=state.seen_keys,
        page_size=pagination.page_capacity(state, request.page_size),
    )
    provider_has_more = (
        selected.has_lookahead or coverage.top_level_visible > coverage.top_level_returned
    )
    replies_returned = sum(len(thread.replies) for thread in selected.items)
    page_coverage = coverage.model_copy(
        update={
            "top_level_returned": len(selected.items),
            "replies_returned": replies_returned,
            "max_comments": request.page_size,
            "truncated": coverage.truncated or provider_has_more,
        }
    )
    source = source_from_post_comments(
        source_url=source_url,
        captured_text=captured_text,
        threads=selected.items,
        coverage=page_coverage,
    )
    metadata = await pagination.finish(
        state,
        page_size=request.page_size,
        returned_keys=selected.keys,
        provider_has_more=provider_has_more,
        force_truncated=coverage.truncated and not provider_has_more,
    )
    return PostCommentsListOutput(
        context_id=request.context_id,
        request_id=request.request_id,
        threads=selected.items,
        coverage=page_coverage,
        pagination=metadata,
        sources=(source,),
    )
