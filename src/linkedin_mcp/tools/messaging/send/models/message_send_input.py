from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from linkedin_mcp.tools._shared.models import (
    Identifier,
)
from linkedin_mcp.tools.messaging.conversation.get.models.conversation_target_input import (
    ConversationTargetInput,
)
from linkedin_mcp.tools.messaging.send.models.message_file_input import MessageFileInput
from linkedin_mcp.tools.messaging.send.models.message_gif_input import MessageGifInput


class MessageSendInput(ConversationTargetInput):
    context_id: Identifier
    request_id: Identifier
    message: (
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=8_000,
                description="Exact message text; emoji characters are retained verbatim.",
            ),
        ]
        | None
    ) = None
    attachments: Annotated[tuple[MessageFileInput, ...], Field(max_length=20)] = ()
    gif: MessageGifInput | None = None
    reply_to_message_ref: (
        Annotated[
            str,
            StringConstraints(pattern=r"^message:[0-9a-f]{24}$"),
        ]
        | None
    ) = Field(
        default=None,
        description=(
            "Optional exact message_ref from conversation.get. LinkedIn's visible reply "
            "control is bound to this message before the requested content is sent."
        ),
    )

    @model_validator(mode="after")
    def validate_message_content(self) -> MessageSendInput:
        if self.message is None and not self.attachments and self.gif is None:
            raise ValueError("A message requires text, one or more attachments, or a GIF")
        if self.gif is not None and (self.message is not None or self.attachments):
            raise ValueError(
                "A GIF is an immediate-send LinkedIn action and cannot be combined "
                "with text or file attachments"
            )
        refs = tuple(attachment.asset_ref for attachment in self.attachments)
        if len(set(refs)) != len(refs):
            raise ValueError("Message attachment references must be unique")
        return self
