"""Evidence validation for `linkedin.messaging.conversation.get`."""

import hashlib
from collections.abc import Iterable
from datetime import datetime

from pydantic import HttpUrl

from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.tools.messaging.conversation.get.models import (
    ConversationObservation,
    SourceReference,
    SourceType,
)


def stable_source_id(
    source_type: SourceType,
    source_url: str,
    captured_at: datetime,
    captured_text: str,
    *,
    identity: str | None = None,
) -> str:
    fields = [source_type.value, source_url, captured_at.isoformat(), captured_text]
    if identity is not None:
        fields.append(identity)
    payload = "\x1f".join(fields).encode()
    digest = hashlib.sha256(payload).hexdigest()[:24]
    return f"{source_type.value}:{digest}"


def source_reference(
    *,
    source_type: SourceType,
    source_url: str,
    captured_at: datetime,
    captured_text: str,
    identity: str | None = None,
) -> SourceReference:
    return SourceReference(
        source_id=stable_source_id(
            source_type,
            source_url,
            captured_at,
            captured_text,
            identity=identity,
        ),
        source_type=source_type,
        source_url=HttpUrl(source_url),
        captured_at=captured_at,
    )


def verify_visible_items(
    captured_text: str,
    items: Iterable[tuple[str, str]],
    *,
    item_kind: str,
) -> None:
    for reference, visible_text in items:
        if visible_text not in captured_text:
            raise ParserDriftError(
                f"Captured {item_kind} {reference!r} is not an exact source substring."
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
