"""Application operation for `linkedin.posts.react`."""

from __future__ import annotations

from typing import Protocol

from linkedin_mcp.tools._shared.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutput,
    ActionPageResult,
    ActionPayload,
    ActionType,
    ReactionSetPayload,
)
from linkedin_mcp.tools._shared.execution import OperationSupport
from linkedin_mcp.tools._shared.models import CapabilityName
from linkedin_mcp.tools.posts.react.models import PostReactionInput


class PostReactionProvider(Protocol):
    async def inspect_reaction(self, request: PostReactionInput) -> ActionInspection: ...

    async def perform_reaction(self, command: ActionCommand) -> ActionPageResult: ...


class ReactPostOperation(OperationSupport):
    _post_reaction: PostReactionProvider

    async def react_to_post(self, request: PostReactionInput) -> ActionOutput:
        def payload_factory(inspection: ActionInspection) -> ActionPayload:
            if inspection.existing_reaction is None:
                raise RuntimeError("Reaction inspection captured no visible reaction state.")
            return ReactionSetPayload(
                post_ref=request.post_ref,
                existing_reaction=inspection.existing_reaction,
                desired_reaction=request.desired_reaction,
            )

        return await self._run_action(
            capability_name=CapabilityName.POST_REACT,
            request=request,
            action_type=ActionType.REACTION_SET,
            payload_factory=payload_factory,
            inspect=lambda: self._post_reaction.inspect_reaction(request),
            perform=self._post_reaction.perform_reaction,
        )
