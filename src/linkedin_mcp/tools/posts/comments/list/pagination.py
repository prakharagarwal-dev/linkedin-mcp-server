"""Pagination and output construction for `linkedin.posts.comments.list`."""

from __future__ import annotations

from dataclasses import asdict

from linkedin_mcp.infra.cursor import (
    CursorStore,
    cursor_binding,
    select_page,
)
from linkedin_mcp.tools.posts.comments.list.evidence import source_from_post_comments
from linkedin_mcp.tools.posts.comments.list.models import (
    PaginationMetadata,
    PostCommentsListInput,
    PostCommentsListOutput,
)
from linkedin_mcp.tools.posts.comments.list.page import PostCommentsPage


async def execute(
    request: PostCommentsListInput,
    *,
    page: PostCommentsPage,
    cursor_store: CursorStore,
    account_id: str,
) -> PostCommentsListOutput:
    arguments = request.model_dump(
        mode="json",
        exclude={"context_id", "request_id", "cursor", "page_size"},
    )
    operation = "linkedin.posts.comments.list"
    state = await cursor_store.start(
        account_id=account_id,
        operation=operation,
        binding=cursor_binding(operation, arguments),
        cursor=request.cursor,
    )
    threads, coverage, captured_text, source_url = await page.collect(
        request,
        result_limit=cursor_store.traversal_limit(state, request.page_size),
    )
    selected = select_page(
        threads,
        key=lambda thread: thread.comment.comment_ref,
        seen_keys=state.seen_keys,
        page_size=cursor_store.page_capacity(state, request.page_size),
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
    cursor_page = await cursor_store.finish(
        state,
        page_size=request.page_size,
        returned_keys=selected.keys,
        provider_has_more=provider_has_more,
        force_truncated=coverage.truncated and not provider_has_more,
    )
    metadata = PaginationMetadata.model_validate(asdict(cursor_page))
    return PostCommentsListOutput(
        context_id=request.context_id,
        request_id=request.request_id,
        threads=selected.items,
        coverage=page_coverage,
        pagination=metadata,
        sources=(source,),
    )
