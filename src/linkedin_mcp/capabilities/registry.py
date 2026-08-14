"""Single source of truth for installed LinkedIn capabilities."""

from __future__ import annotations

from dataclasses import dataclass

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

    def info(self) -> CapabilityInfo:
        return CapabilityInfo(
            name=self.name,
            version=self.version,
            effect=self.effect,
            required_surfaces=tuple(sorted(self.required_surfaces, key=lambda item: item.value)),
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
        ActionOutput,
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
        InvitationAcceptInput,
        InvitationIgnoreInput,
        InvitationListInput,
        InvitationListOutput,
        InvitationSendInput,
        JobDetailInput,
        JobDetailOutput,
        JobSearchInput,
        JobSearchOutput,
        MessageSendInput,
        PeopleGetInput,
        PeopleGetOutput,
        PeopleSearchInput,
        PeopleSearchOutput,
        PostCommentInput,
        PostCommentsListInput,
        PostCommentsListOutput,
        PostCreateInput,
        PostGetInput,
        PostGetOutput,
        PostReactionInput,
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
            ),
            CapabilityDescriptor(
                name=CapabilityName.JOBS_GET,
                version="2.0.0",
                effect=CapabilityEffect.READ,
                input_model=JobDetailInput,
                output_model=JobDetailOutput,
                required_surfaces=frozenset({LinkedInSurface.JOB_DETAIL}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.PEOPLE_SEARCH,
                version="2.1.0",
                effect=CapabilityEffect.READ,
                input_model=PeopleSearchInput,
                output_model=PeopleSearchOutput,
                required_surfaces=frozenset({LinkedInSurface.PEOPLE_SEARCH}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.PEOPLE_GET,
                version="1.1.1",
                effect=CapabilityEffect.READ,
                input_model=PeopleGetInput,
                output_model=PeopleGetOutput,
                required_surfaces=frozenset({LinkedInSurface.MEMBER_PROFILE}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.COMPANIES_SEARCH,
                version="2.0.0",
                effect=CapabilityEffect.READ,
                input_model=CompanySearchInput,
                output_model=CompanySearchOutput,
                required_surfaces=frozenset({LinkedInSurface.COMPANY_SEARCH}),
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
            ),
            CapabilityDescriptor(
                name=CapabilityName.POSTS_SEARCH,
                version="2.0.0",
                effect=CapabilityEffect.READ,
                input_model=PostSearchInput,
                output_model=PostSearchOutput,
                required_surfaces=frozenset({LinkedInSurface.CONTENT_SEARCH}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.POSTS_GET,
                version="2.0.0",
                effect=CapabilityEffect.READ,
                input_model=PostGetInput,
                output_model=PostGetOutput,
                required_surfaces=frozenset({LinkedInSurface.POST_DETAIL}),
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
            ),
            CapabilityDescriptor(
                name=CapabilityName.POSTS_CREATE,
                version="3.0.0",
                effect=CapabilityEffect.WRITE,
                input_model=PostCreateInput,
                output_model=ActionOutput,
                required_surfaces=frozenset({LinkedInSurface.POST_COMPOSER}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.POST_COMMENT,
                version="4.0.0",
                effect=CapabilityEffect.WRITE,
                input_model=PostCommentInput,
                output_model=ActionOutput,
                required_surfaces=frozenset(
                    {LinkedInSurface.POST_DETAIL, LinkedInSurface.POST_DISCUSSION}
                ),
            ),
            CapabilityDescriptor(
                name=CapabilityName.POST_REACT,
                version="4.0.0",
                effect=CapabilityEffect.WRITE,
                input_model=PostReactionInput,
                output_model=ActionOutput,
                required_surfaces=frozenset(
                    {LinkedInSurface.POST_DETAIL, LinkedInSurface.POST_DISCUSSION}
                ),
            ),
            CapabilityDescriptor(
                name=CapabilityName.INVITATIONS_LIST,
                version="4.0.0",
                effect=CapabilityEffect.READ,
                input_model=InvitationListInput,
                output_model=InvitationListOutput,
                required_surfaces=frozenset({LinkedInSurface.CONNECTIONS}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.CONNECTIONS_LIST,
                version="2.0.0",
                effect=CapabilityEffect.READ,
                input_model=ConnectionsListInput,
                output_model=ConnectionsListOutput,
                required_surfaces=frozenset({LinkedInSurface.CONNECTIONS}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.CONNECTIONS_SEARCH,
                version="2.0.0",
                effect=CapabilityEffect.READ,
                input_model=ConnectionsSearchInput,
                output_model=ConnectionsSearchOutput,
                required_surfaces=frozenset({LinkedInSurface.PEOPLE_SEARCH}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.INVITATION_SEND,
                version="3.0.0",
                effect=CapabilityEffect.WRITE,
                input_model=InvitationSendInput,
                output_model=ActionOutput,
                required_surfaces=frozenset({LinkedInSurface.MEMBER_PROFILE}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.INVITATION_ACCEPT,
                version="2.0.0",
                effect=CapabilityEffect.WRITE,
                input_model=InvitationAcceptInput,
                output_model=ActionOutput,
                required_surfaces=frozenset({LinkedInSurface.MEMBER_PROFILE}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.INVITATION_IGNORE,
                version="2.0.0",
                effect=CapabilityEffect.WRITE,
                input_model=InvitationIgnoreInput,
                output_model=ActionOutput,
                required_surfaces=frozenset({LinkedInSurface.MEMBER_PROFILE}),
            ),
            CapabilityDescriptor(
                name=CapabilityName.MESSAGING_SEARCH,
                version="2.0.0",
                effect=CapabilityEffect.READ,
                input_model=ConversationSearchInput,
                output_model=ConversationSearchOutput,
                required_surfaces=frozenset({LinkedInSurface.MESSAGING}),
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
            ),
            CapabilityDescriptor(
                name=CapabilityName.MESSAGING_SEND,
                version="3.0.0",
                effect=CapabilityEffect.WRITE,
                input_model=MessageSendInput,
                output_model=ActionOutput,
                required_surfaces=frozenset(
                    {LinkedInSurface.MESSAGING, LinkedInSurface.MEMBER_PROFILE}
                ),
            ),
        )
    )
