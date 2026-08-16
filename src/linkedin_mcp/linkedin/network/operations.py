"""Application operations for LinkedIn connections and invitations."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from linkedin_mcp.app.pagination import PaginationLease, select_page
from linkedin_mcp.errors import ParserDriftError
from linkedin_mcp.linkedin.actions import (
    ActionCommand,
    ActionInspection,
    ActionOutput,
    ActionPageResult,
    ActionType,
    InvitationAcceptPayload,
    InvitationIgnorePayload,
    InvitationSendPayload,
)
from linkedin_mcp.linkedin.common import CapabilityName, StopReason
from linkedin_mcp.linkedin.execution import OperationSupport
from linkedin_mcp.linkedin.network.evidence import (
    source_from_connections,
    source_from_invitation_list,
)
from linkedin_mcp.linkedin.network.models import (
    ConnectionsListCoverage,
    ConnectionsListInput,
    ConnectionsListOutput,
    ConnectionsSearchInput,
    ConnectionsSearchOutput,
    ConnectionSummary,
    InvitationAcceptInput,
    InvitationIgnoreInput,
    InvitationListCoverage,
    InvitationListInput,
    InvitationListOutput,
    InvitationSendInput,
    InvitationSummary,
)
from linkedin_mcp.linkedin.people.evidence import source_from_people_search
from linkedin_mcp.linkedin.people.models import PersonConnectionDegree
from linkedin_mcp.linkedin.people.operations import PeopleSearchProvider

ProgressReporter = Callable[[int, int, str], Awaitable[None]]


class InvitationListProvider(Protocol):
    async def collect(
        self,
        request: InvitationListInput,
        *,
        result_limit: int | None = None,
        progress: ProgressReporter | None = None,
    ) -> tuple[tuple[InvitationSummary, ...], InvitationListCoverage, str, str]: ...


class ConnectionsListProvider(Protocol):
    async def collect(
        self,
        request: ConnectionsListInput,
        *,
        result_limit: int | None = None,
    ) -> tuple[tuple[ConnectionSummary, ...], ConnectionsListCoverage, str, str]: ...


class InvitationActionProvider(Protocol):
    async def inspect_send(self, request: InvitationSendInput) -> ActionInspection: ...

    async def inspect_accept(self, request: InvitationAcceptInput) -> ActionInspection: ...

    async def inspect_ignore(self, request: InvitationIgnoreInput) -> ActionInspection: ...

    async def perform_send(self, command: ActionCommand) -> ActionPageResult: ...

    async def perform_accept(self, command: ActionCommand) -> ActionPageResult: ...

    async def perform_ignore(self, command: ActionCommand) -> ActionPageResult: ...


class NetworkOperations(OperationSupport):
    _people_search: PeopleSearchProvider
    _invitation_list: InvitationListProvider
    _connections_list: ConnectionsListProvider
    _invitation_actions: InvitationActionProvider

    async def search_connections(
        self,
        request: ConnectionsSearchInput,
    ) -> ConnectionsSearchOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.CONNECTIONS_SEARCH, request)
            people_request = request.as_people_search_input()
            people, coverage, captured_text, source_url = await self._people_search.collect(
                people_request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
            )
            if any(
                person.connection_degree is not PersonConnectionDegree.FIRST for person in people
            ):
                raise ParserDriftError(
                    "LinkedIn Connections search returned a result that was not visibly "
                    "first-degree."
                )
            page = select_page(
                people,
                key=lambda person: person.profile_slug,
                seen_keys=lease.seen_keys,
                page_size=self._pagination.page_capacity(lease, request.page_size),
            )
            provider_has_more = page.has_lookahead or coverage.stop_reason in {
                StopReason.RESULT_LIMIT,
                StopReason.SAFETY_BOUND,
            }
            page_coverage = coverage.model_copy(
                update={
                    "result_count": len(page.items),
                    "max_results": request.page_size,
                    "stop_reason": (
                        StopReason.RESULT_LIMIT if provider_has_more else coverage.stop_reason
                    ),
                }
            )
            source = source_from_people_search(
                source_url=source_url,
                captured_text=captured_text,
                people=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
            )
            return ConnectionsSearchOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                people=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def list_invitations(
        self,
        request: InvitationListInput,
        progress: ProgressReporter | None = None,
    ) -> InvitationListOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.INVITATIONS_LIST, request)
            invitations, coverage, captured_text, source_url = await self._invitation_list.collect(
                request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
                progress=progress,
            )
            page = select_page(
                invitations,
                key=lambda invitation: invitation.invitation_ref,
                seen_keys=lease.seen_keys,
                page_size=self._pagination.page_capacity(lease, request.page_size),
            )
            provider_has_more = page.has_lookahead or coverage.stop_reason in {
                StopReason.RESULT_LIMIT,
                StopReason.SAFETY_BOUND,
            }
            page_stop_reason = (
                StopReason.RESULT_LIMIT
                if page.has_lookahead or coverage.stop_reason is StopReason.RESULT_LIMIT
                else coverage.stop_reason
            )
            page_coverage = coverage.model_copy(
                update={
                    "result_count": len(page.items),
                    "max_results": request.page_size,
                    "stop_reason": page_stop_reason,
                }
            )
            advertised_label = captured_text.split("\n\n", maxsplit=1)[0].strip()
            page_text = "\n\n".join((advertised_label, *(item.visible_text for item in page.items)))
            source = source_from_invitation_list(
                source_url=source_url,
                captured_text=page_text,
                invitations=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
            )
            return InvitationListOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                invitations=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def list_connections(self, request: ConnectionsListInput) -> ConnectionsListOutput:
        lease: PaginationLease | None = None
        try:
            lease = await self._pagination_lease(CapabilityName.CONNECTIONS_LIST, request)
            connections, coverage, captured_text, source_url = await self._connections_list.collect(
                request,
                result_limit=self._pagination.traversal_limit(lease, request.page_size),
            )
            page = select_page(
                connections,
                key=lambda connection: connection.profile_slug,
                seen_keys=lease.seen_keys,
                page_size=self._pagination.page_capacity(lease, request.page_size),
            )
            provider_has_more = page.has_lookahead or coverage.stop_reason in {
                StopReason.RESULT_LIMIT,
                StopReason.SAFETY_BOUND,
            }
            page_coverage = coverage.model_copy(
                update={
                    "result_count": len(page.items),
                    "max_results": request.page_size,
                    "stop_reason": (
                        StopReason.RESULT_LIMIT if provider_has_more else coverage.stop_reason
                    ),
                }
            )
            source = source_from_connections(
                source_url=source_url,
                captured_text=captured_text,
                connections=page.items,
                coverage=page_coverage,
            )
            pagination = await self._pagination.advance(
                lease,
                page_size=request.page_size,
                returned_keys=page.keys,
                provider_has_more=provider_has_more,
            )
            return ConnectionsListOutput(
                context_id=request.context_id,
                request_id=request.request_id,
                connections=page.items,
                coverage=page_coverage,
                pagination=pagination,
                sources=(source,),
            )
        finally:
            if lease is not None:
                await self._pagination.abort(lease)

    async def send_invitation(self, request: InvitationSendInput) -> ActionOutput:
        return await self._run_action(
            capability_name=CapabilityName.INVITATION_SEND,
            request=request,
            action_type=ActionType.INVITATION_SEND,
            payload=InvitationSendPayload(note=request.note),
            inspect=lambda: self._invitation_actions.inspect_send(request),
            perform=self._invitation_actions.perform_send,
        )

    async def accept_invitation(self, request: InvitationAcceptInput) -> ActionOutput:
        return await self._run_action(
            capability_name=CapabilityName.INVITATION_ACCEPT,
            request=request,
            action_type=ActionType.INVITATION_ACCEPT,
            payload_factory=lambda inspection: InvitationAcceptPayload(
                invitation_ref=(
                    inspection.target.invitation_ref or self._missing_invitation_reference()
                )
            ),
            inspect=lambda: self._invitation_actions.inspect_accept(request),
            perform=self._invitation_actions.perform_accept,
        )

    async def ignore_invitation(self, request: InvitationIgnoreInput) -> ActionOutput:
        return await self._run_action(
            capability_name=CapabilityName.INVITATION_IGNORE,
            request=request,
            action_type=ActionType.INVITATION_IGNORE,
            payload_factory=lambda inspection: InvitationIgnorePayload(
                invitation_ref=(
                    inspection.target.invitation_ref or self._missing_invitation_reference()
                )
            ),
            inspect=lambda: self._invitation_actions.inspect_ignore(request),
            perform=self._invitation_actions.perform_ignore,
        )

    @staticmethod
    def _missing_invitation_reference() -> str:
        raise RuntimeError("Invitation inspection did not return an invitation reference.")
