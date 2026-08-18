from __future__ import annotations

from linkedin_mcp.tools._shared.models import (
    Identifier,
    PostReference,
    StrictModel,
)


class PostGetInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    post_ref: PostReference
