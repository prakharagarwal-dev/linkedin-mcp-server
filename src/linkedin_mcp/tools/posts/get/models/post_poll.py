from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    StrictModel,
)
from linkedin_mcp.tools.posts.get.models.post_poll_option import PostPollOption
from linkedin_mcp.tools.posts.get.models.post_poll_state import PostPollState


class PostPoll(StrictModel):
    question: Annotated[str, Field(min_length=1, max_length=500)]
    options: Annotated[tuple[PostPollOption, ...], Field(min_length=2, max_length=5)]
    total_votes_text: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    state: PostPollState = PostPollState.UNKNOWN
    state_text: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    viewer_has_voted: bool | None = None
    visible_text: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def reject_duplicate_options(self) -> PostPoll:
        normalized = tuple(option.text.casefold() for option in self.options)
        if len(set(normalized)) != len(normalized):
            raise ValueError("Visible poll options must be unique")
        return self
