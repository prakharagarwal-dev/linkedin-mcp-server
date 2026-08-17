from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    Identifier,
    StrictModel,
)
from linkedin_mcp.tools.posts.create.models.event_post_content import EventPostContent
from linkedin_mcp.tools.posts.create.models.expert_request_post_content import (
    ExpertRequestPostContent,
)
from linkedin_mcp.tools.posts.create.models.hiring_post_content import HiringPostContent
from linkedin_mcp.tools.posts.create.models.post_audience import PostAudience
from linkedin_mcp.tools.posts.create.models.post_collaborator_input import PostCollaboratorInput
from linkedin_mcp.tools.posts.create.models.post_comment_control import PostCommentControl
from linkedin_mcp.tools.posts.create.models.post_create_content import PostCreateContent
from linkedin_mcp.tools.posts.create.models.post_group_target import PostGroupTarget


class PostCreateInput(StrictModel):
    context_id: Identifier
    request_id: Identifier
    content: PostCreateContent
    audience: PostAudience = PostAudience.ANYONE
    group_target: PostGroupTarget | None = None
    comment_control: PostCommentControl = PostCommentControl.ANYONE
    brand_partnership: bool = False
    collaborators: Annotated[tuple[PostCollaboratorInput, ...], Field(max_length=5)] = ()
    scheduled_at: datetime | None = None

    @model_validator(mode="after")
    def validate_schedule_shape(self) -> PostCreateInput:
        if self.scheduled_at is not None and self.scheduled_at.utcoffset() is None:
            raise ValueError("scheduled_at must include a timezone offset")
        if (self.audience is PostAudience.GROUP) != (self.group_target is not None):
            raise ValueError("Group audience requires exactly one group_target")
        if self.brand_partnership and self.audience is not PostAudience.ANYONE:
            raise ValueError("Brand partnership posts must use the Anyone audience")
        if self.collaborators and self.audience is not PostAudience.ANYONE:
            raise ValueError("Collaborative posts must use the Anyone audience")
        collaborator_identities = tuple(
            ("member", collaborator.profile_slug)
            if collaborator.profile_slug is not None
            else ("company", collaborator.company_slug)
            for collaborator in self.collaborators
        )
        if len(set(collaborator_identities)) != len(collaborator_identities):
            raise ValueError("Post collaborators must be unique")
        if self.scheduled_at is not None and isinstance(
            self.content,
            EventPostContent | HiringPostContent | ExpertRequestPostContent,
        ):
            raise ValueError("LinkedIn does not schedule event, hiring, or expert-request posts")
        return self
