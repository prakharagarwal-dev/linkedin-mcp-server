"""Typed mutable state for deterministic cross-capability simulator workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from linkedin_mcp.domain.models import MessageDirection, ReactionState


def _empty_comments() -> list[SimulatorComment]:
    return []


def _empty_messages() -> list[SimulatorMessage]:
    return []


def _empty_jobs() -> dict[str, SimulatorJob]:
    return {}


def _empty_people() -> dict[str, SimulatorPerson]:
    return {}


def _empty_companies() -> dict[str, SimulatorCompany]:
    return {}


def _empty_posts() -> dict[str, SimulatorPost]:
    return {}


def _empty_conversations() -> dict[str, SimulatorConversation]:
    return {}


def _empty_connections() -> set[str]:
    return set()


def _empty_invitations() -> dict[str, SimulatorInvitation]:
    return {}


def _empty_actions() -> list[SimulatorAction]:
    return []


def _empty_faults() -> dict[str, list[SimulatorFault]]:
    return {}


class SimulatorFault(StrEnum):
    NAVIGATION_TIMEOUT = "navigation_timeout"
    AUTHENTICATION_EXPIRED = "authentication_expired"
    RESTRICTION = "restriction"
    CONTROL_MISSING = "control_missing"
    EFFECT_INTERRUPTED = "effect_interrupted"
    VERIFICATION_TIMEOUT = "verification_timeout"


@dataclass(frozen=True, slots=True)
class SimulatorJob:
    job_id: str
    title: str
    company_slug: str
    company_name: str
    location: str
    description: str
    easy_apply: bool = False


@dataclass(frozen=True, slots=True)
class SimulatorPerson:
    profile_slug: str
    name: str
    headline: str
    location: str
    current_company_slug: str | None = None
    connection_degree: str | None = None
    about: str | None = None


@dataclass(frozen=True, slots=True)
class SimulatorCompany:
    company_slug: str
    name: str
    tagline: str
    location: str
    industry: str


@dataclass(frozen=True, slots=True)
class SimulatorComment:
    comment_ref: str
    author_slug: str
    text: str
    parent_comment_ref: str | None = None
    reaction: ReactionState = ReactionState.NONE


@dataclass(slots=True)
class SimulatorPost:
    post_ref: str
    author_slug: str
    author_name: str
    text: str
    company_slug: str | None = None
    reaction: ReactionState = ReactionState.NONE
    comments: list[SimulatorComment] = field(default_factory=_empty_comments)


@dataclass(frozen=True, slots=True)
class SimulatorMessage:
    message_ref: str
    sender_slug: str
    sender_name: str
    direction: MessageDirection
    text: str | None = None


@dataclass(slots=True)
class SimulatorConversation:
    conversation_id: str
    participant_slug: str
    participant_name: str
    messages: list[SimulatorMessage] = field(default_factory=_empty_messages)
    unread: bool = False


@dataclass(frozen=True, slots=True)
class SimulatorInvitation:
    invitation_ref: str
    profile_slug: str
    direction: str
    note: str | None = None


@dataclass(frozen=True, slots=True)
class SimulatorAction:
    sequence: int
    action_type: str
    target_ref: str
    detail: str


@dataclass(slots=True)
class SimulatorState:
    """One synthetic LinkedIn account and all observable state around it."""

    actor_slug: str
    actor_name: str
    authenticated: bool = True
    jobs: dict[str, SimulatorJob] = field(default_factory=_empty_jobs)
    people: dict[str, SimulatorPerson] = field(default_factory=_empty_people)
    companies: dict[str, SimulatorCompany] = field(default_factory=_empty_companies)
    posts: dict[str, SimulatorPost] = field(default_factory=_empty_posts)
    conversations: dict[str, SimulatorConversation] = field(default_factory=_empty_conversations)
    connections: set[str] = field(default_factory=_empty_connections)
    invitations: dict[str, SimulatorInvitation] = field(default_factory=_empty_invitations)
    actions: list[SimulatorAction] = field(default_factory=_empty_actions)
    faults: dict[str, list[SimulatorFault]] = field(default_factory=_empty_faults)
    _next_comment_id: int = 900
    _next_message_id: int = 900
    _next_post_id: int = 7312345678901234990

    @classmethod
    def standard(cls) -> SimulatorState:
        state = cls(actor_slug="current-member", actor_name="Asha Rao")
        state.companies["acme-cloud"] = SimulatorCompany(
            company_slug="acme-cloud",
            name="Acme Cloud",
            tagline="Reliable cloud infrastructure",
            location="Bengaluru, Karnataka, India",
            industry="Software Development",
        )
        state.people["jane-doe"] = SimulatorPerson(
            profile_slug="jane-doe",
            name="Jane Doe",
            headline="Staff Engineer at Acme Cloud",
            location="Bengaluru, Karnataka, India",
            current_company_slug="acme-cloud",
            connection_degree="first",
            about="Builds reliable distributed systems.",
        )
        state.people["alex-ray"] = SimulatorPerson(
            profile_slug="alex-ray",
            name="Alex Ray",
            headline="Engineering Manager at Acme Cloud",
            location="Bengaluru, Karnataka, India",
            current_company_slug="acme-cloud",
            connection_degree="second",
        )
        state.people["sam-kim"] = SimulatorPerson(
            profile_slug="sam-kim",
            name="Sam Kim",
            headline="Product Engineer at Example Labs",
            location="Pune, Maharashtra, India",
            current_company_slug=None,
            connection_degree="second",
        )
        state.jobs["4100000001"] = SimulatorJob(
            job_id="4100000001",
            title="Senior Python Engineer",
            company_slug="acme-cloud",
            company_name="Acme Cloud",
            location="India (Remote)",
            description="Build reliable Python services.",
            easy_apply=True,
        )
        post = SimulatorPost(
            post_ref="activity:7312345678901234567",
            author_slug="jane-doe",
            author_name="Jane Doe",
            text="A practical Python reliability post.",
        )
        post.comments.append(
            SimulatorComment(
                comment_ref="comment:activity:7312345678901234567:111",
                author_slug="alex-ray",
                text="Helpful breakdown.",
                reaction=ReactionState.LIKE,
            )
        )
        state.posts[post.post_ref] = post
        state.connections.add("jane-doe")
        state.invitations["invitation:" + "a" * 24] = SimulatorInvitation(
            invitation_ref="invitation:" + "a" * 24,
            profile_slug="alex-ray",
            direction="received",
            note="I would like to connect.",
        )
        state.conversations["thread-123"] = SimulatorConversation(
            conversation_id="thread-123",
            participant_slug="jane-doe",
            participant_name="Jane Doe",
            messages=[
                SimulatorMessage(
                    message_ref="message:" + "a" * 24,
                    sender_slug="jane-doe",
                    sender_name="Jane Doe",
                    direction=MessageDirection.INCOMING,
                    text="Can we discuss the role?",
                )
            ],
            unread=True,
        )
        return state

    def queue_fault(self, operation: str, fault: SimulatorFault) -> None:
        self.faults.setdefault(operation, []).append(fault)

    def take_fault(self, operation: str) -> SimulatorFault | None:
        queued = self.faults.get(operation)
        if not queued:
            return None
        fault = queued.pop(0)
        if not queued:
            self.faults.pop(operation, None)
        return fault

    def search_jobs(self, query: str | None) -> tuple[SimulatorJob, ...]:
        needle = (query or "").casefold()
        return tuple(
            job
            for job in self.jobs.values()
            if needle in f"{job.title} {job.company_name} {job.description}".casefold()
        )

    def search_people(
        self, query: str, *, company_slug: str | None = None
    ) -> tuple[SimulatorPerson, ...]:
        needle = query.casefold()
        return tuple(
            person
            for person in self.people.values()
            if needle in f"{person.name} {person.headline}".casefold()
            and (company_slug is None or person.current_company_slug == company_slug)
        )

    def search_companies(self, query: str) -> tuple[SimulatorCompany, ...]:
        needle = query.casefold()
        return tuple(
            company
            for company in self.companies.values()
            if needle in f"{company.name} {company.tagline} {company.industry}".casefold()
        )

    def search_posts(self, query: str) -> tuple[SimulatorPost, ...]:
        needle = query.casefold()
        return tuple(post for post in self.posts.values() if needle in post.text.casefold())

    def send_invitation(self, profile_slug: str, note: str | None) -> SimulatorInvitation:
        if profile_slug not in self.people:
            raise KeyError(profile_slug)
        if profile_slug in self.connections:
            raise ValueError("The target is already connected.")
        if any(item.profile_slug == profile_slug for item in self.invitations.values()):
            raise ValueError("An invitation for the target already exists.")
        invitation = SimulatorInvitation(
            invitation_ref=f"invitation:sent-{len(self.invitations) + 1:020d}",
            profile_slug=profile_slug,
            direction="sent",
            note=note,
        )
        self.invitations[invitation.invitation_ref] = invitation
        self._record("invitation_send", profile_slug, note or "")
        return invitation

    def accept_invitation(self, invitation_ref: str) -> None:
        invitation = self.invitations.get(invitation_ref)
        if invitation is None or invitation.direction != "received":
            raise ValueError("The exact received invitation is unavailable.")
        self.invitations.pop(invitation_ref)
        self.connections.add(invitation.profile_slug)
        self._record("invitation_accept", invitation.profile_slug, invitation_ref)

    def ignore_invitation(self, invitation_ref: str) -> None:
        invitation = self.invitations.get(invitation_ref)
        if invitation is None or invitation.direction != "received":
            raise ValueError("The exact received invitation is unavailable.")
        self.invitations.pop(invitation_ref)
        self._record("invitation_ignore", invitation.profile_slug, invitation_ref)

    def send_message(self, conversation_id: str, text: str) -> SimulatorMessage:
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            raise KeyError(conversation_id)
        message = SimulatorMessage(
            message_ref=f"message:sim-{self._next_message_id:020d}",
            sender_slug=self.actor_slug,
            sender_name=self.actor_name,
            direction=MessageDirection.OUTGOING,
            text=text,
        )
        self._next_message_id += 1
        conversation.messages.append(message)
        conversation.unread = False
        self._record("message_send", conversation_id, text)
        return message

    def create_post(self, text: str) -> SimulatorPost:
        self._next_post_id += 1
        post = SimulatorPost(
            post_ref=f"activity:{self._next_post_id}",
            author_slug=self.actor_slug,
            author_name=self.actor_name,
            text=text,
        )
        self.posts[post.post_ref] = post
        self._record("post_create", post.post_ref, text)
        return post

    def create_comment(
        self,
        post_ref: str,
        text: str,
        *,
        parent_comment_ref: str | None = None,
    ) -> SimulatorComment:
        post = self.posts.get(post_ref)
        if post is None:
            raise KeyError(post_ref)
        if parent_comment_ref is not None and not any(
            comment.comment_ref == parent_comment_ref for comment in post.comments
        ):
            raise ValueError("The exact parent comment is unavailable.")
        comment = SimulatorComment(
            comment_ref=f"comment:{post_ref}:{self._next_comment_id}",
            author_slug=self.actor_slug,
            text=text,
            parent_comment_ref=parent_comment_ref,
        )
        self._next_comment_id += 1
        post.comments.append(comment)
        self._record("comment_create", comment.comment_ref, text)
        return comment

    def set_reaction(
        self,
        post_ref: str,
        reaction: ReactionState,
        *,
        comment_ref: str | None = None,
    ) -> None:
        post = self.posts.get(post_ref)
        if post is None:
            raise KeyError(post_ref)
        target_ref = post_ref
        if comment_ref is None:
            post.reaction = reaction
        else:
            matching = [comment for comment in post.comments if comment.comment_ref == comment_ref]
            if len(matching) != 1:
                raise ValueError("The exact comment is unavailable or ambiguous.")
            comment = matching[0]
            index = post.comments.index(comment)
            post.comments[index] = SimulatorComment(
                comment_ref=comment.comment_ref,
                author_slug=comment.author_slug,
                text=comment.text,
                parent_comment_ref=comment.parent_comment_ref,
                reaction=reaction,
            )
            target_ref = comment_ref
        self._record("reaction_set", target_ref, reaction.value)

    def _record(self, action_type: str, target_ref: str, detail: str) -> None:
        self.actions.append(
            SimulatorAction(
                sequence=len(self.actions) + 1,
                action_type=action_type,
                target_ref=target_ref,
                detail=detail,
            )
        )
