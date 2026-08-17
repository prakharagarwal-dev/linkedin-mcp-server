from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)
from linkedin_mcp.tools.posts.models.post_mention_input import PostMentionInput


class PostCreateContentBase(StrictModel):
    text: Annotated[str, Field(min_length=1, max_length=3_000)] | None = None
    mentions: Annotated[tuple[PostMentionInput, ...], Field(max_length=20)] = ()

    @model_validator(mode="after")
    def validate_mentions(self) -> PostCreateContentBase:
        if self.mentions and self.text is None:
            raise ValueError("Post mentions require post text")
        tokens = tuple(mention.token for mention in self.mentions)
        if len({token.casefold() for token in tokens}) != len(tokens):
            raise ValueError("Post mention tokens must be unique")
        if self.text is not None:
            for token in tokens:
                if self.text.count(token) != 1:
                    raise ValueError(
                        "Each post mention token must occur exactly once in the post text"
                    )
        return self
