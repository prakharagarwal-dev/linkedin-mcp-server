from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, model_validator

from linkedin_mcp.tools._shared.models import (
    AssetReference,
)
from linkedin_mcp.tools.posts.create.models.event_format import EventFormat
from linkedin_mcp.tools.posts.create.models.event_speaker_input import EventSpeakerInput
from linkedin_mcp.tools.posts.create.models.event_type import EventType
from linkedin_mcp.tools.posts.create.models.post_create_content_base import PostCreateContentBase
from linkedin_mcp.tools.posts.create.models.post_create_mode import PostCreateMode


class EventPostContent(PostCreateContentBase):
    mode: Literal[PostCreateMode.EVENT] = PostCreateMode.EVENT
    event_type: EventType
    event_format: EventFormat | None = None
    event_name: Annotated[str, Field(min_length=1, max_length=75)]
    timezone_label: Annotated[str, Field(min_length=1, max_length=200)]
    start_at: datetime
    end_at: datetime | None = None
    external_url: HttpUrl | None = None
    venue_location: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    venue_details: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    description: Annotated[str, Field(min_length=1, max_length=5_000)]
    speakers: Annotated[tuple[EventSpeakerInput, ...], Field(max_length=20)] = ()
    cover_asset_ref: AssetReference | None = None
    cover_alt_text: Annotated[str, Field(min_length=1, max_length=1_000)] | None = None

    @model_validator(mode="after")
    def validate_event_shape(self) -> EventPostContent:
        if self.text is None:
            raise ValueError("An event post requires text")
        if self.start_at.utcoffset() is None:
            raise ValueError("Event start_at must include a timezone offset")
        if self.end_at is not None:
            if self.end_at.utcoffset() is None:
                raise ValueError("Event end_at must include a timezone offset")
            if self.end_at <= self.start_at:
                raise ValueError("Event end_at must be after start_at")
        if self.event_type is EventType.ONLINE:
            if self.event_format is None:
                raise ValueError("An online event requires an event format")
            if self.event_format is EventFormat.EXTERNAL_LINK and self.external_url is None:
                raise ValueError("An external online event requires external_url")
            if self.event_format is EventFormat.LINKEDIN_LIVE and self.external_url is not None:
                raise ValueError("A LinkedIn Live event cannot include external_url")
            if self.venue_location is not None or self.venue_details is not None:
                raise ValueError("Online events cannot include an in-person venue")
        else:
            if self.event_format is not None:
                raise ValueError("An in-person event does not use an online event format")
            if self.venue_location is None:
                raise ValueError("An in-person event requires venue_location")
        if self.cover_alt_text is not None and self.cover_asset_ref is None:
            raise ValueError("Event cover alt text requires a cover image")
        slugs = tuple(speaker.profile_slug for speaker in self.speakers)
        if len(set(slugs)) != len(slugs):
            raise ValueError("Event speakers must be unique")
        return self
