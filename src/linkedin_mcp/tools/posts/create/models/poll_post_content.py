from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from linkedin_mcp.tools.posts.create.models.poll_duration import PollDuration
from linkedin_mcp.tools.posts.create.models.post_create_content_base import PostCreateContentBase
from linkedin_mcp.tools.posts.create.models.post_create_mode import PostCreateMode


class PollPostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.POLL] = PostCreateMode.POLL
    question: Annotated[str, Field(min_length=1, max_length=140)]
    options: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=30)], ...],
        Field(min_length=2, max_length=4),
    ]
    duration: PollDuration = PollDuration.ONE_WEEK

    @model_validator(mode="after")
    def reject_duplicate_options(self) -> PollPostContent:
        if len({option.casefold() for option in self.options}) != len(self.options):
            raise ValueError("Poll options must be unique")
        return self
