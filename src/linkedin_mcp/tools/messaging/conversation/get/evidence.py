"""Evidence validation for `linkedin.messaging.conversation.get`."""

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools._shared.models import SourceReference, SourceType
from linkedin_mcp.tools._shared.source import source_reference
from linkedin_mcp.tools.messaging.conversation.get.models.conversation_observation import (
    ConversationObservation,
)


def source_from_conversation(observation: ConversationObservation) -> SourceReference:
    for message in observation.messages:
        text_missing = message.text is not None and message.text not in message.visible_text
        attachment_missing = any(
            attachment.visible_text not in message.visible_text
            for attachment in message.attachments
        )
        if (
            text_missing
            or attachment_missing
            or message.visible_text not in observation.visible_text
        ):
            raise ParserDriftError(
                f"Message {message.message_ref!r} is not an exact visible conversation substring."
            )
    return source_reference(
        source_type=SourceType.MESSAGING_CONVERSATION,
        source_url=_conversation_source_url(observation),
        captured_at=observation.captured_at,
        captured_text=observation.visible_text,
    )


def _conversation_source_url(observation: ConversationObservation) -> str:
    if observation.conversation_id:
        return f"https://www.linkedin.com/messaging/thread/{observation.conversation_id}/"
    if observation.participant_profile_slug:
        return f"https://www.linkedin.com/in/{observation.participant_profile_slug}/"
    raise ParserDriftError("A conversation source requires a conversation or participant target.")
