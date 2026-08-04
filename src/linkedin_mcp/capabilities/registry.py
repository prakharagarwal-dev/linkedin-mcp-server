"""Single source of truth for installed LinkedIn capabilities."""

from __future__ import annotations

from dataclasses import dataclass

from linkedin_mcp.config import Settings
from linkedin_mcp.domain.models import (
    CapabilityEffect,
    CapabilityInfo,
    CapabilityName,
    LinkedInSurface,
    StrictModel,
)


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    name: CapabilityName
    version: str
    effect: CapabilityEffect
    input_model: type[StrictModel]
    output_model: type[StrictModel]
    required_surfaces: frozenset[LinkedInSurface]
    required_scopes: frozenset[str]

    def status(self, settings: Settings) -> CapabilityInfo:
        reasons: list[str] = []
        missing_surfaces = self.required_surfaces.difference(settings.allowed_surfaces)
        if missing_surfaces:
            values = ", ".join(sorted(surface.value for surface in missing_surfaces))
            reasons.append(f"missing surfaces: {values}")
        missing_scopes = self.required_scopes.difference(settings.allowed_scopes)
        if missing_scopes:
            values = ", ".join(sorted(missing_scopes))
            reasons.append(f"missing scopes: {values}")
        if self.effect not in settings.allowed_effects:
            reasons.append(f"effect {self.effect.value} is not allowed")
        return CapabilityInfo(
            name=self.name,
            version=self.version,
            effect=self.effect,
            required_surfaces=tuple(sorted(self.required_surfaces, key=lambda item: item.value)),
            required_scopes=tuple(sorted(self.required_scopes)),
            enabled=not reasons,
            disabled_reason="; ".join(reasons) if reasons else None,
        )


class CapabilityRegistry:
    def __init__(self, descriptors: tuple[CapabilityDescriptor, ...]) -> None:
        by_name = {descriptor.name: descriptor for descriptor in descriptors}
        if len(by_name) != len(descriptors):
            raise ValueError("Capability names must be unique")
        self._by_name = by_name

    def get(self, name: CapabilityName) -> CapabilityDescriptor:
        return self._by_name[name]

    def list(self) -> tuple[CapabilityDescriptor, ...]:
        return tuple(sorted(self._by_name.values(), key=lambda descriptor: descriptor.name.value))


def create_default_registry() -> CapabilityRegistry:
    from linkedin_mcp.domain.models import (
        ActionExecuteInput,
        ActionExecuteOutput,
        ActionPrepareOutput,
        CompanyGetInput,
        CompanyGetOutput,
        CompanySearchInput,
        CompanySearchOutput,
        ConnectionsListInput,
        ConnectionsListOutput,
        ConnectionsSearchInput,
        ConnectionsSearchOutput,
        ConversationGetInput,
        ConversationGetOutput,
        ConversationSearchInput,
        ConversationSearchOutput,
        InvitationAcceptPrepareInput,
        InvitationIgnorePrepareInput,
        InvitationListInput,
        InvitationListOutput,
        InvitationSendPrepareInput,
        JobDetailInput,
        JobDetailOutput,
        JobSearchInput,
        JobSearchOutput,
        MessagePrepareInput,
        PeopleGetInput,
        PeopleGetOutput,
        PeopleSearchInput,
        PeopleSearchOutput,
        PostCommentPrepareInput,
        PostCommentsListInput,
        PostCommentsListOutput,
        PostCreatePrepareInput,
        PostGetInput,
        PostGetOutput,
        PostReactionPrepareInput,
        PostSearchInput,
        PostSearchOutput,
    )

    return CapabilityRegistry(
        (
            CapabilityDescriptor(
                name=CapabilityName.JOBS_SEARCH,
                version="2.1.0",
                effect=CapabilityEffect.READ,
                input_model=JobSearchInput,
                output_model=JobSearchOutput,
                required_surfaces=frozenset({LinkedInSurface.JOB_SEARCH}),
                required_scopes=frozenset({"linkedin.jobs.search"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.JOBS_GET,
                version="2.0.0",
                effect=CapabilityEffect.READ,
                input_model=JobDetailInput,
                output_model=JobDetailOutput,
                required_surfaces=frozenset({LinkedInSurface.JOB_DETAIL}),
                required_scopes=frozenset({"linkedin.jobs.read"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.PEOPLE_SEARCH,
                version="2.1.0",
                effect=CapabilityEffect.READ,
                input_model=PeopleSearchInput,
                output_model=PeopleSearchOutput,
                required_surfaces=frozenset({LinkedInSurface.PEOPLE_SEARCH}),
                required_scopes=frozenset({"linkedin.people.search"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.PEOPLE_GET,
                version="1.1.1",
                effect=CapabilityEffect.READ,
                input_model=PeopleGetInput,
                output_model=PeopleGetOutput,
                required_surfaces=frozenset({LinkedInSurface.MEMBER_PROFILE}),
                required_scopes=frozenset({"linkedin.people.read"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.COMPANIES_SEARCH,
                version="2.0.0",
                effect=CapabilityEffect.READ,
                input_model=CompanySearchInput,
                output_model=CompanySearchOutput,
                required_surfaces=frozenset({LinkedInSurface.COMPANY_SEARCH}),
                required_scopes=frozenset({"linkedin.companies.search"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.COMPANIES_GET,
                version="2.0.0",
                effect=CapabilityEffect.READ,
                input_model=CompanyGetInput,
                output_model=CompanyGetOutput,
                required_surfaces=frozenset(
                    {
                        LinkedInSurface.COMPANY_PROFILE,
                        LinkedInSurface.COMPANY_ABOUT,
                    }
                ),
                required_scopes=frozenset({"linkedin.companies.read"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.POSTS_SEARCH,
                version="2.0.0",
                effect=CapabilityEffect.READ,
                input_model=PostSearchInput,
                output_model=PostSearchOutput,
                required_surfaces=frozenset({LinkedInSurface.CONTENT_SEARCH}),
                required_scopes=frozenset({"linkedin.posts.search"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.POSTS_GET,
                version="2.0.0",
                effect=CapabilityEffect.READ,
                input_model=PostGetInput,
                output_model=PostGetOutput,
                required_surfaces=frozenset({LinkedInSurface.POST_DETAIL}),
                required_scopes=frozenset({"linkedin.posts.read"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.POST_COMMENTS_LIST,
                version="1.1.1",
                effect=CapabilityEffect.READ,
                input_model=PostCommentsListInput,
                output_model=PostCommentsListOutput,
                required_surfaces=frozenset(
                    {LinkedInSurface.POST_DETAIL, LinkedInSurface.POST_DISCUSSION}
                ),
                required_scopes=frozenset({"linkedin.posts.comments.read"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.POSTS_CREATE_PREPARE,
                version="2.0.0",
                effect=CapabilityEffect.PREPARE,
                input_model=PostCreatePrepareInput,
                output_model=ActionPrepareOutput,
                required_surfaces=frozenset({LinkedInSurface.POST_COMPOSER}),
                required_scopes=frozenset({"linkedin.posts.create"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.POSTS_CREATE_EXECUTE,
                version="2.0.0",
                effect=CapabilityEffect.WRITE,
                input_model=ActionExecuteInput,
                output_model=ActionExecuteOutput,
                required_surfaces=frozenset({LinkedInSurface.POST_COMPOSER}),
                required_scopes=frozenset({"linkedin.posts.create"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.POST_COMMENT_PREPARE,
                version="3.0.0",
                effect=CapabilityEffect.PREPARE,
                input_model=PostCommentPrepareInput,
                output_model=ActionPrepareOutput,
                required_surfaces=frozenset(
                    {LinkedInSurface.POST_DETAIL, LinkedInSurface.POST_DISCUSSION}
                ),
                required_scopes=frozenset({"linkedin.posts.comments.create"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.POST_COMMENT_EXECUTE,
                version="3.0.0",
                effect=CapabilityEffect.WRITE,
                input_model=ActionExecuteInput,
                output_model=ActionExecuteOutput,
                required_surfaces=frozenset(
                    {LinkedInSurface.POST_DETAIL, LinkedInSurface.POST_DISCUSSION}
                ),
                required_scopes=frozenset({"linkedin.posts.comments.create"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.POST_REACTION_PREPARE,
                version="3.0.0",
                effect=CapabilityEffect.PREPARE,
                input_model=PostReactionPrepareInput,
                output_model=ActionPrepareOutput,
                required_surfaces=frozenset(
                    {LinkedInSurface.POST_DETAIL, LinkedInSurface.POST_DISCUSSION}
                ),
                required_scopes=frozenset({"linkedin.posts.reactions.set"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.POST_REACTION_EXECUTE,
                version="3.0.0",
                effect=CapabilityEffect.WRITE,
                input_model=ActionExecuteInput,
                output_model=ActionExecuteOutput,
                required_surfaces=frozenset(
                    {LinkedInSurface.POST_DETAIL, LinkedInSurface.POST_DISCUSSION}
                ),
                required_scopes=frozenset({"linkedin.posts.reactions.set"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.INVITATIONS_LIST,
                version="4.0.0",
                effect=CapabilityEffect.READ,
                input_model=InvitationListInput,
                output_model=InvitationListOutput,
                required_surfaces=frozenset({LinkedInSurface.CONNECTIONS}),
                required_scopes=frozenset({"linkedin.invitations.read"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.CONNECTIONS_LIST,
                version="2.0.0",
                effect=CapabilityEffect.READ,
                input_model=ConnectionsListInput,
                output_model=ConnectionsListOutput,
                required_surfaces=frozenset({LinkedInSurface.CONNECTIONS}),
                required_scopes=frozenset({"linkedin.connections.read"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.CONNECTIONS_SEARCH,
                version="2.0.0",
                effect=CapabilityEffect.READ,
                input_model=ConnectionsSearchInput,
                output_model=ConnectionsSearchOutput,
                required_surfaces=frozenset({LinkedInSurface.PEOPLE_SEARCH}),
                required_scopes=frozenset({"linkedin.connections.read"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.INVITATION_SEND_PREPARE,
                version="1.1.0",
                effect=CapabilityEffect.PREPARE,
                input_model=InvitationSendPrepareInput,
                output_model=ActionPrepareOutput,
                required_surfaces=frozenset({LinkedInSurface.MEMBER_PROFILE}),
                required_scopes=frozenset({"linkedin.invitations.send"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.INVITATION_SEND_EXECUTE,
                version="2.0.0",
                effect=CapabilityEffect.WRITE,
                input_model=ActionExecuteInput,
                output_model=ActionExecuteOutput,
                required_surfaces=frozenset({LinkedInSurface.MEMBER_PROFILE}),
                required_scopes=frozenset({"linkedin.invitations.send"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.INVITATION_ACCEPT_PREPARE,
                version="1.0.0",
                effect=CapabilityEffect.PREPARE,
                input_model=InvitationAcceptPrepareInput,
                output_model=ActionPrepareOutput,
                required_surfaces=frozenset({LinkedInSurface.MEMBER_PROFILE}),
                required_scopes=frozenset({"linkedin.invitations.accept"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.INVITATION_ACCEPT_EXECUTE,
                version="1.0.0",
                effect=CapabilityEffect.WRITE,
                input_model=ActionExecuteInput,
                output_model=ActionExecuteOutput,
                required_surfaces=frozenset({LinkedInSurface.MEMBER_PROFILE}),
                required_scopes=frozenset({"linkedin.invitations.accept"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.INVITATION_IGNORE_PREPARE,
                version="1.0.0",
                effect=CapabilityEffect.PREPARE,
                input_model=InvitationIgnorePrepareInput,
                output_model=ActionPrepareOutput,
                required_surfaces=frozenset({LinkedInSurface.MEMBER_PROFILE}),
                required_scopes=frozenset({"linkedin.invitations.ignore"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.INVITATION_IGNORE_EXECUTE,
                version="1.0.0",
                effect=CapabilityEffect.WRITE,
                input_model=ActionExecuteInput,
                output_model=ActionExecuteOutput,
                required_surfaces=frozenset({LinkedInSurface.MEMBER_PROFILE}),
                required_scopes=frozenset({"linkedin.invitations.ignore"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.MESSAGING_SEARCH,
                version="2.0.0",
                effect=CapabilityEffect.READ,
                input_model=ConversationSearchInput,
                output_model=ConversationSearchOutput,
                required_surfaces=frozenset({LinkedInSurface.MESSAGING}),
                required_scopes=frozenset({"linkedin.messaging.read"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.MESSAGING_CONVERSATION_GET,
                version="2.0.0",
                effect=CapabilityEffect.READ,
                input_model=ConversationGetInput,
                output_model=ConversationGetOutput,
                required_surfaces=frozenset(
                    {LinkedInSurface.MESSAGING, LinkedInSurface.MEMBER_PROFILE}
                ),
                required_scopes=frozenset({"linkedin.messaging.read"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.MESSAGING_MESSAGE_PREPARE,
                version="2.0.0",
                effect=CapabilityEffect.PREPARE,
                input_model=MessagePrepareInput,
                output_model=ActionPrepareOutput,
                required_surfaces=frozenset(
                    {LinkedInSurface.MESSAGING, LinkedInSurface.MEMBER_PROFILE}
                ),
                required_scopes=frozenset({"linkedin.messaging.send"}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.MESSAGING_MESSAGE_EXECUTE,
                version="2.0.0",
                effect=CapabilityEffect.WRITE,
                input_model=ActionExecuteInput,
                output_model=ActionExecuteOutput,
                required_surfaces=frozenset(
                    {LinkedInSurface.MESSAGING, LinkedInSurface.MEMBER_PROFILE}
                ),
                required_scopes=frozenset({"linkedin.messaging.send"}),
            ),
        )
    )
