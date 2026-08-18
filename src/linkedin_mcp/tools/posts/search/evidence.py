"""Evidence validation for `linkedin.posts.search`."""

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools._shared.models import SourceReference, SourceType
from linkedin_mcp.tools._shared.source import source_reference, verify_visible_items
from linkedin_mcp.tools.posts.search.models.post_search_coverage import PostSearchCoverage
from linkedin_mcp.tools.posts.search.models.post_summary import PostSummary


def source_from_post_search(
    *,
    source_url: str,
    captured_text: str,
    posts: tuple[PostSummary, ...],
    coverage: PostSearchCoverage,
) -> SourceReference:
    if coverage.result_count != len(posts):
        raise ParserDriftError("Post-search coverage conflicts with the captured result count.")
    verify_visible_items(
        captured_text,
        ((post.post_ref, post.visible_text) for post in posts),
        item_kind="post",
    )
    return source_reference(
        source_type=SourceType.POST_SEARCH,
        source_url=source_url,
        captured_at=coverage.captured_at,
        captured_text=captured_text,
    )
