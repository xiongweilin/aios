from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, model_validator
from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
    or_,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column

from .authority import AuthorityRepository
from .domain import Principal, UtcModel, utcnow
from .intake.models import (
    CandidateAdministrativeRequest,
    CandidateCaseUpdate,
    CandidateCaseUpdateStatus,
    CandidateStatus,
)
from .intake.repository import (
    CandidateAdministrativeRequestRow,
    CandidateCaseUpdateRow,
    IntakeRepository,
    PromotionRecordRow,
    _candidate_from_row,
    _case_update_from_row,
    _uuid_tuple,
)
from .persistence import Base, CaseRow, SqlStore


class ConversationRejected(ValueError):
    """The provider message cannot be admitted to the conversation timeline."""


class IdentityResolutionError(ConversationRejected):
    """Provider identity could not be resolved to a current Principal."""


class SenderSpoof(ConversationRejected):
    """A claimed sender identity disagrees with the authenticated provider actor."""


class TenantMismatch(ConversationRejected):
    """The provider tenant is not the tenant bound to the conversation."""


class ParticipantChanged(ConversationRejected):
    """A later message changed the sender or participant set of a conversation."""


class OutOfOrderDelivery(ConversationRejected):
    """A new message would move the durable conversation timeline backwards."""


class CandidateSupersessionConflict(ConversationRejected):
    """A candidate replacement does not preserve the original conversation lineage."""


class ConversationRef(UtcModel):
    """Provider, tenant, and thread are the durable identity of one conversation."""

    provider: str = Field(min_length=1, max_length=255)
    tenant_ref: str = Field(min_length=1, max_length=512)
    thread_ref: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_components(self) -> ConversationRef:
        for name in ("provider", "tenant_ref", "thread_ref"):
            value = getattr(self, name).strip()
            setattr(self, name, value)
            if not value:
                raise ValueError(f"{name} must not be blank")
        if len(self.canonical_ref) > 1000:
            raise ValueError("conversation reference exceeds the durable limit")
        return self

    @property
    def canonical_ref(self) -> str:
        return f"{self.provider}/{self.tenant_ref}/{self.thread_ref}"

    @property
    def value(self) -> str:
        return self.canonical_ref

    @property
    def tenant(self) -> str:
        return self.tenant_ref

    @property
    def thread_id(self) -> str:
        return self.thread_ref

    def __str__(self) -> str:
        return self.canonical_ref


class ConversationMessage(UtcModel):
    """A verified provider message envelope without storing untrusted body text."""

    message_id: UUID = Field(default_factory=uuid4)
    conversation_ref: ConversationRef
    provider_message_id: str = Field(min_length=1, max_length=512)
    source_event_id: str = Field(min_length=1, max_length=512)
    sender_external_subject: str = Field(min_length=1, max_length=1000)
    displayed_sender: str | None = Field(default=None, max_length=1000)
    participant_external_subjects: tuple[str, ...] = ()
    sequence: int = Field(ge=1)
    occurred_at: datetime = Field(default_factory=utcnow)
    provider_tenant_ref: str | None = Field(default=None, max_length=512)
    content_digest: str | None = Field(default=None, min_length=1, max_length=128)
    source_refs: tuple[UUID, ...] = ()
    interpretation_refs: tuple[UUID, ...] = ()
    candidate_fact_refs: tuple[UUID, ...] = ()
    claimed_sender_external_subject: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_message_identity(self) -> ConversationMessage:
        for name in (
            "provider_message_id",
            "source_event_id",
            "sender_external_subject",
        ):
            value = getattr(self, name).strip()
            setattr(self, name, value)
            if not value:
                raise ValueError(f"{name} must not be blank")
        if self.displayed_sender is not None:
            self.displayed_sender = self.displayed_sender.strip()
        if self.claimed_sender_external_subject is not None:
            self.claimed_sender_external_subject = self.claimed_sender_external_subject.strip()
        participants = tuple(
            dict.fromkeys(
                value.strip()
                for value in self.participant_external_subjects
                if value.strip()
            )
        )
        if self.sender_external_subject not in participants:
            participants = (self.sender_external_subject, *participants)
        self.participant_external_subjects = participants
        return self


class ConversationState(UtcModel):
    conversation_ref: ConversationRef
    sender_external_subject: str
    participant_external_subjects: tuple[str, ...]
    last_sequence: int
    last_message_id: UUID | None = None
    bound_case_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ResolvedProviderIdentity:
    provider: str
    tenant_ref: str
    external_subject: str
    principal: Principal

    @property
    def principal_id(self) -> str:
        return self.principal.principal_id


@dataclass(frozen=True, slots=True)
class ConversationMessageResult:
    message: ConversationMessage
    identity: ResolvedProviderIdentity
    candidate_ref: UUID | None
    case_update: CandidateCaseUpdate | None
    created: bool


class ConversationRow(Base):
    __tablename__ = "administrative_conversation"

    conversation_ref: Mapped[str] = mapped_column(String(1000), primary_key=True)
    provider: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    thread_ref: Mapped[str] = mapped_column(String(1000), nullable=False)
    sender_external_subject: Mapped[str] = mapped_column(String(1000), nullable=False)
    participants_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_message_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    bound_case_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConversationMessageRow(Base):
    __tablename__ = "administrative_conversation_message"
    __table_args__ = (
        UniqueConstraint(
            "conversation_ref",
            "provider_message_id",
            name="uq_conversation_provider_message",
        ),
        UniqueConstraint(
            "conversation_ref",
            "source_event_id",
            name="uq_conversation_source_event",
        ),
        UniqueConstraint(
            "conversation_ref",
            "sequence",
            name="uq_conversation_sequence",
        ),
    )

    message_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    conversation_ref: Mapped[str] = mapped_column(
        ForeignKey("administrative_conversation.conversation_ref"), nullable=False
    )
    provider_message_id: Mapped[str] = mapped_column(String(512), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(512), nullable=False)
    sender_external_subject: Mapped[str] = mapped_column(String(1000), nullable=False)
    displayed_sender: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    participants_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    interpretation_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    candidate_fact_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    candidate_ref: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    case_update_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConversationService:
    """Resolve provider identity and persist conversation/message admission semantics."""

    def __init__(
        self,
        store: SqlStore,
        *,
        authority: AuthorityRepository | None = None,
        intake: IntakeRepository | None = None,
    ) -> None:
        self.store = store
        self.authority = authority or AuthorityRepository(store)
        self.intake = intake or IntakeRepository(store)

    def resolve_provider_identity(
        self,
        conversation_ref: ConversationRef,
        *,
        external_subject: str,
        displayed_sender: str | None = None,
        claimed_sender_external_subject: str | None = None,
        provider: str | None = None,
        tenant_ref: str | None = None,
        at: datetime | None = None,
    ) -> ResolvedProviderIdentity:
        del displayed_sender  # Display text is evidence, never an authority key.
        self._validate_provider_context(conversation_ref, provider=provider, tenant_ref=tenant_ref)
        external_subject = external_subject.strip()
        if not external_subject:
            raise IdentityResolutionError("provider sender identity must not be blank")
        claimed = (claimed_sender_external_subject or "").strip()
        if claimed and claimed != external_subject:
            raise SenderSpoof("claimed sender differs from the provider-authenticated actor")
        principal = self.authority.resolve_identity(
            provider=conversation_ref.provider,
            external_subject=external_subject,
            at=at,
        )
        if principal is None:
            raise IdentityResolutionError("provider sender is not bound to an active Principal")
        return ResolvedProviderIdentity(
            provider=conversation_ref.provider,
            tenant_ref=conversation_ref.tenant_ref,
            external_subject=external_subject,
            principal=principal,
        )

    def accept_message(
        self,
        message: ConversationMessage,
        *,
        provider: str | None = None,
        tenant_ref: str | None = None,
        candidate: CandidateAdministrativeRequest | None = None,
    ) -> ConversationMessageResult:
        ref = message.conversation_ref
        self._validate_provider_context(ref, provider=provider, tenant_ref=tenant_ref)
        if message.provider_tenant_ref is not None:
            self._validate_provider_context(
                ref,
                provider=None,
                tenant_ref=message.provider_tenant_ref,
            )
        identity = self.resolve_provider_identity(
            ref,
            external_subject=message.sender_external_subject,
            displayed_sender=message.displayed_sender,
            claimed_sender_external_subject=message.claimed_sender_external_subject,
            at=message.occurred_at,
        )

        with self.store.sessions.begin() as db:
            row = db.get(ConversationRow, ref.canonical_ref)
            existing_message = db.execute(
                select(ConversationMessageRow).where(
                    ConversationMessageRow.conversation_ref == ref.canonical_ref,
                    or_(
                        ConversationMessageRow.provider_message_id
                        == message.provider_message_id,
                        ConversationMessageRow.source_event_id == message.source_event_id,
                    ),
                )
            ).scalar_one_or_none()
            if existing_message is not None:
                if not self._same_delivery(existing_message, message):
                    raise ConversationRejected(
                        "provider message identity was redelivered with different semantics"
                    )
                update = (
                    None
                    if existing_message.case_update_id is None
                    else db.get(CandidateCaseUpdateRow, existing_message.case_update_id)
                )
                return ConversationMessageResult(
                    message=self._message_with_ref(existing_message, ref),
                    identity=identity,
                    candidate_ref=existing_message.candidate_ref,
                    case_update=None if update is None else _case_update_from_row(update),
                    created=False,
                )

            if row is None:
                row = ConversationRow(
                    conversation_ref=ref.canonical_ref,
                    provider=ref.provider,
                    tenant_ref=ref.tenant_ref,
                    thread_ref=ref.thread_ref,
                    sender_external_subject=message.sender_external_subject,
                    participants_json=list(message.participant_external_subjects),
                    last_sequence=message.sequence,
                    last_message_id=message.message_id,
                    bound_case_id=None,
                    created_at=message.occurred_at,
                    updated_at=message.occurred_at,
                )
                db.add(row)
            else:
                if message.sequence <= row.last_sequence:
                    raise OutOfOrderDelivery(
                        "provider delivery would move the conversation timeline backwards"
                    )
                if row.sender_external_subject != message.sender_external_subject:
                    raise ParticipantChanged("conversation sender changed")
                if set(row.participants_json) != set(message.participant_external_subjects):
                    raise ParticipantChanged("conversation participant set changed")

            persisted_candidate = self._validate_candidate(db, ref, candidate)
            candidate_ref, case_id = self._admitted_case(db, ref, persisted_candidate)
            case_update: CandidateCaseUpdate | None = None
            if case_id is not None:
                if not message.source_refs or not message.interpretation_refs:
                    raise ConversationRejected(
                        "post-admission messages require source and interpretation references"
                    )
                case_update = CandidateCaseUpdate(
                    case_id=case_id,
                    conversation_ref=ref.canonical_ref,
                    interpretation_refs=message.interpretation_refs,
                    candidate_fact_refs=message.candidate_fact_refs,
                    source_refs=message.source_refs,
                    status=CandidateCaseUpdateStatus.REQUIRES_HUMAN_REVIEW,
                )
                db.add(
                    CandidateCaseUpdateRow(
                        candidate_update_id=case_update.candidate_update_id,
                        case_id=case_update.case_id,
                        conversation_ref=case_update.conversation_ref,
                        interpretation_refs_json=[str(value) for value in case_update.interpretation_refs],
                        candidate_fact_refs_json=[str(value) for value in case_update.candidate_fact_refs],
                        source_refs_json=[str(value) for value in case_update.source_refs],
                        created_at=case_update.created_at,
                        status=case_update.status.value,
                    )
                )
                row.bound_case_id = case_id

            db.add(
                ConversationMessageRow(
                    message_id=message.message_id,
                    conversation_ref=ref.canonical_ref,
                    provider_message_id=message.provider_message_id,
                    source_event_id=message.source_event_id,
                    sender_external_subject=message.sender_external_subject,
                    displayed_sender=message.displayed_sender,
                    participants_json=list(message.participant_external_subjects),
                    sequence=message.sequence,
                    occurred_at=message.occurred_at,
                    content_digest=message.content_digest,
                    source_refs_json=[str(value) for value in message.source_refs],
                    interpretation_refs_json=[str(value) for value in message.interpretation_refs],
                    candidate_fact_refs_json=[str(value) for value in message.candidate_fact_refs],
                    candidate_ref=candidate_ref,
                    case_update_id=None if case_update is None else case_update.candidate_update_id,
                    created_at=utcnow(),
                )
            )
            row.last_sequence = message.sequence
            row.last_message_id = message.message_id
            row.updated_at = message.occurred_at
            db.flush()

        return ConversationMessageResult(
            message=message,
            identity=identity,
            candidate_ref=candidate_ref,
            case_update=case_update,
            created=True,
        )

    def resolve_identity(
        self, conversation_ref: ConversationRef, **kwargs: Any
    ) -> ResolvedProviderIdentity:
        return self.resolve_provider_identity(conversation_ref, **kwargs)

    def ingest_message(
        self, message: ConversationMessage, **kwargs: Any
    ) -> ConversationMessageResult:
        return self.accept_message(message, **kwargs)

    def supersede_candidate(
        self,
        previous_candidate_ref: UUID,
        replacement: CandidateAdministrativeRequest,
    ) -> CandidateAdministrativeRequest:
        if replacement.supersedes_candidate_ref != previous_candidate_ref:
            raise CandidateSupersessionConflict(
                "replacement must explicitly reference the superseded candidate"
            )
        if replacement.status is not CandidateStatus.ACTIVE:
            raise CandidateSupersessionConflict("replacement candidate must remain active")

        with self.store.sessions.begin() as db:
            previous_row = db.get(CandidateAdministrativeRequestRow, previous_candidate_ref)
            if previous_row is None:
                raise CandidateSupersessionConflict("superseded candidate does not exist")
            previous = _candidate_from_row(previous_row)
            if previous.conversation_ref != replacement.conversation_ref:
                raise CandidateSupersessionConflict(
                    "candidate supersession cannot cross conversation identity"
                )
            existing_row = db.get(CandidateAdministrativeRequestRow, replacement.candidate_id)
            if existing_row is not None:
                existing = _candidate_from_row(existing_row)
                if existing == replacement and previous.status is CandidateStatus.SUPERSEDED:
                    return existing
                raise CandidateSupersessionConflict(
                    "replacement candidate identity already has different semantics"
                )
            if previous.status is not CandidateStatus.ACTIVE:
                raise CandidateSupersessionConflict(
                    "only an active candidate may be superseded"
                )

            previous_row.status = CandidateStatus.SUPERSEDED.value
            db.add(
                CandidateAdministrativeRequestRow(
                    candidate_id=replacement.candidate_id,
                    conversation_ref=replacement.conversation_ref,
                    interpretation_refs_json=[str(value) for value in replacement.interpretation_refs],
                    candidate_requester=replacement.candidate_requester,
                    candidate_intent=replacement.candidate_intent,
                    candidate_fact_refs_json=[str(value) for value in replacement.candidate_fact_refs],
                    source_refs_json=[str(value) for value in replacement.source_refs],
                    created_at=replacement.created_at,
                    supersedes_candidate_ref=replacement.supersedes_candidate_ref,
                    status=replacement.status.value,
                )
            )
            db.flush()
        return replacement

    def append_candidate(
        self, candidate: CandidateAdministrativeRequest
    ) -> CandidateAdministrativeRequest:
        if candidate.supersedes_candidate_ref is not None:
            return self.supersede_candidate(candidate.supersedes_candidate_ref, candidate)
        return self.intake.append_candidate_request(candidate)

    def supersede(
        self,
        previous_candidate_ref: UUID,
        replacement: CandidateAdministrativeRequest,
    ) -> CandidateAdministrativeRequest:
        return self.supersede_candidate(previous_candidate_ref, replacement)

    def get_conversation(self, conversation_ref: ConversationRef) -> ConversationState | None:
        with self.store.sessions() as db:
            row = db.get(ConversationRow, conversation_ref.canonical_ref)
            return None if row is None else self._state_from_row(row)

    def list_messages(self, conversation_ref: ConversationRef) -> list[ConversationMessage]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(ConversationMessageRow)
                    .where(ConversationMessageRow.conversation_ref == conversation_ref.canonical_ref)
                    .order_by(ConversationMessageRow.sequence)
                )
                .scalars()
                .all()
            )
            return [self._message_with_ref(row, conversation_ref) for row in rows]

    def _validate_candidate(
        self,
        db: Any,
        ref: ConversationRef,
        candidate: CandidateAdministrativeRequest | None,
    ) -> CandidateAdministrativeRequest | None:
        if candidate is None:
            return None
        row = db.get(CandidateAdministrativeRequestRow, candidate.candidate_id)
        if row is None or _candidate_from_row(row).model_dump() != candidate.model_dump():
            raise ConversationRejected("message requires the current persisted candidate")
        if candidate.conversation_ref != ref.canonical_ref:
            raise ConversationRejected("candidate conversation does not match provider thread")
        if candidate.status is CandidateStatus.SUPERSEDED:
            raise ConversationRejected("superseded candidate cannot receive a new message")
        return candidate

    @staticmethod
    def _admitted_case(
        db: Any,
        ref: ConversationRef,
        candidate: CandidateAdministrativeRequest | None,
    ) -> tuple[UUID | None, UUID | None]:
        candidates: list[CandidateAdministrativeRequest] = []
        if candidate is not None:
            candidates.append(candidate)
        else:
            rows = (
                db.execute(
                    select(CandidateAdministrativeRequestRow)
                    .where(CandidateAdministrativeRequestRow.conversation_ref == ref.canonical_ref)
                    .order_by(CandidateAdministrativeRequestRow.created_at.desc())
                )
                .scalars()
                .all()
            )
            candidates.extend(_candidate_from_row(row) for row in rows)
        for item in candidates:
            if item.status is not CandidateStatus.ADMITTED:
                continue
            promotion = db.execute(
                select(PromotionRecordRow).where(
                    PromotionRecordRow.candidate_ref == item.candidate_id
                )
            ).scalar_one_or_none()
            if promotion is None:
                raise ConversationRejected("admitted candidate has no promotion lineage")
            case = db.execute(
                select(CaseRow).where(CaseRow.request_id == promotion.request_id)
            ).scalar_one_or_none()
            if case is None:
                raise ConversationRejected("admitted candidate has no bound case")
            return item.candidate_id, case.case_id
        return (
            None if candidate is None else candidate.candidate_id,
            None,
        )

    @staticmethod
    def _same_delivery(row: ConversationMessageRow, message: ConversationMessage) -> bool:
        return (
            row.source_event_id == message.source_event_id
            and row.provider_message_id == message.provider_message_id
            and row.sender_external_subject == message.sender_external_subject
            and row.displayed_sender == message.displayed_sender
            and set(row.participants_json) == set(message.participant_external_subjects)
            and row.sequence == message.sequence
            and row.content_digest == message.content_digest
            and tuple(row.source_refs_json) == tuple(str(value) for value in message.source_refs)
            and tuple(row.interpretation_refs_json)
            == tuple(str(value) for value in message.interpretation_refs)
            and tuple(row.candidate_fact_refs_json)
            == tuple(str(value) for value in message.candidate_fact_refs)
        )

    @staticmethod
    def _validate_provider_context(
        ref: ConversationRef,
        *,
        provider: str | None,
        tenant_ref: str | None,
    ) -> None:
        if provider is not None and provider.strip() != ref.provider:
            raise TenantMismatch("provider identity does not match conversation")
        if tenant_ref is not None and tenant_ref.strip() != ref.tenant_ref:
            raise TenantMismatch("provider tenant does not match conversation")

    @staticmethod
    def _state_from_row(row: ConversationRow) -> ConversationState:
        return ConversationState(
            conversation_ref=ConversationRef(
                provider=row.provider,
                tenant_ref=row.tenant_ref,
                thread_ref=row.thread_ref,
            ),
            sender_external_subject=row.sender_external_subject,
            participant_external_subjects=tuple(row.participants_json),
            last_sequence=row.last_sequence,
            last_message_id=row.last_message_id,
            bound_case_id=row.bound_case_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _message_with_ref(
        row: ConversationMessageRow, ref: ConversationRef
    ) -> ConversationMessage:
        return ConversationMessage(
            message_id=row.message_id,
            conversation_ref=ref,
            provider_message_id=row.provider_message_id,
            source_event_id=row.source_event_id,
            sender_external_subject=row.sender_external_subject,
            displayed_sender=row.displayed_sender,
            participant_external_subjects=tuple(row.participants_json),
            sequence=row.sequence,
            occurred_at=row.occurred_at,
            provider_tenant_ref=ref.tenant_ref,
            content_digest=row.content_digest,
            source_refs=_uuid_tuple(row.source_refs_json),
            interpretation_refs=_uuid_tuple(row.interpretation_refs_json),
            candidate_fact_refs=_uuid_tuple(row.candidate_fact_refs_json),
        )


IdentityConversationService = ConversationService
ConversationError = ConversationRejected
UnboundProviderIdentity = IdentityResolutionError
OutOfOrderMessage = OutOfOrderDelivery
ProviderIdentity = ResolvedProviderIdentity
ConversationEvent = ConversationMessage


__all__ = [
    "CandidateSupersessionConflict",
    "ConversationError",
    "ConversationEvent",
    "ConversationMessage",
    "ConversationMessageResult",
    "ConversationMessageRow",
    "ConversationRef",
    "ConversationRejected",
    "ConversationRow",
    "ConversationService",
    "ConversationState",
    "IdentityConversationService",
    "IdentityResolutionError",
    "OutOfOrderDelivery",
    "OutOfOrderMessage",
    "ParticipantChanged",
    "ProviderIdentity",
    "ResolvedProviderIdentity",
    "SenderSpoof",
    "TenantMismatch",
    "UnboundProviderIdentity",
]
