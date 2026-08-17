from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints, model_validator

from linkedin_mcp.tools._shared.models import (
    ConversationId,
    ProfileSlug,
    StrictModel,
)


class ConversationTargetInput(StrictModel):
    profile_slug: ProfileSlug | None = None
    conversation_id: ConversationId | None = None
    conversation_ref: (
        Annotated[str, StringConstraints(pattern=r"^conversation:[0-9a-f]{24}$")] | None
    ) = None

    @model_validator(mode="after")
    def require_one_target(self) -> ConversationTargetInput:
        targets = (self.profile_slug, self.conversation_id, self.conversation_ref)
        if sum(value is not None for value in targets) != 1:
            raise ValueError(
                "Exactly one of profile_slug, conversation_id, or conversation_ref is required"
            )
        return self
