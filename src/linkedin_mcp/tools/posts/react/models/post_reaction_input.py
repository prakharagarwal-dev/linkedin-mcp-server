from __future__ import annotations

from linkedin_mcp.tools._shared.models import (
    Identifier,
    PostReference,
    StrictModel,
)
from linkedin_mcp.tools.posts.react.models.reaction_state import ReactionState


class PostReactionInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    post_ref: PostReference
    desired_reaction: ReactionState
