from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from linkedin_mcp.tools._shared.models import (
    Identifier,
    PaginatedInput,
)
from linkedin_mcp.tools.messaging.search.models.conversation_category import ConversationCategory
from linkedin_mcp.tools.messaging.search.models.conversation_filter import ConversationFilter


class ConversationSearchInput(PaginatedInput):
    context_id: Identifier
    request_id: Identifier
    query: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=500,
                description=(
                    "LinkedIn's visible Search messages value. The same field searches "
                    "recipient names and message keywords."
                ),
            ),
        ]
        | None
    ) = None
    category: ConversationCategory | None = Field(
        default=None,
        description=(
            "Optional current desktop inbox category. When omitted, LinkedIn's Focused "
            "category is selected deterministically."
        ),
    )
    filter: ConversationFilter | None = Field(
        default=None,
        description=(
            "Optional current desktop message filter. LinkedIn exposes these as mutually "
            "exclusive pills, so exactly zero or one filter can be selected."
        ),
    )

    @model_validator(mode="after")
    def require_search_criterion(self) -> ConversationSearchInput:
        if self.query is None and self.category is None and self.filter is None:
            raise ValueError(
                "Message search requires query, category, or one visible message filter"
            )
        return self

    @property
    def resolved_category(self) -> ConversationCategory:
        return self.category or ConversationCategory.FOCUSED
