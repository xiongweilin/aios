from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import httpx

from .commitment_common import M9_NAMESPACE, CommitmentIntakeError
from .commitment_models import (
    CommitmentRecord,
    CommunicationDeliveryState,
    CommunicationDraftRecord,
    CommunicationEffectRecord,
)
from .commitment_repository import CommitmentRepository
from .config import Settings
from .domain import AuthorityClass, EffectReversibility, utcnow
from .execution_repository import ExecutionConflict, ExecutionRepository
from .intake.artifacts import ArtifactStore
from .integrations.world_runtime import WorldRuntimeBridge, WorldRuntimeEffectProvider
from .obligations import (
    AdministrativeObligation,
    AdministrativeObligationSet,
    ObligationFulfillmentKind,
    ObligationRepository,
)
from .service import mint_execution_authorization_from_approval, plan_effect
from .unit_of_work import AdministrativeUnitOfWork


class _NoCommunicationFallback:
    """Keep Kernel cutover fail-closed if a non-Kernel path is ever selected."""

    def execute(self, effect, payload):  # type: ignore[no-untyped-def]
        del effect, payload
        raise CommitmentIntakeError("World Runtime-owned communication cannot use a fallback provider")

    def observe(self, effect):  # type: ignore[no-untyped-def]
        del effect
        raise CommitmentIntakeError("World Runtime-owned communication cannot use a fallback verifier")


class CommitmentCommunicationCoordinator:
    def __init__(
        self,
        store,
        *,
        repository: CommitmentRepository,
        uow: AdministrativeUnitOfWork,
        artifact_store: ArtifactStore,
        settings: Settings,
        execution: ExecutionRepository,
        obligations: ObligationRepository,
        bridge_factory: Callable[..., WorldRuntimeBridge] = WorldRuntimeBridge,
        http_post: Callable[..., Any] = httpx.post,
    ) -> None:
        self.store = store
        self.repository = repository
        self.uow = uow
        self.artifact_store = artifact_store
        self.settings = settings
        self.execution = execution
        self.obligations = obligations
        self.bridge_factory = bridge_factory
        self.http_post = http_post

    def ensure(
        self,
        commitment: CommitmentRecord,
        *,
        draft_kind: str,
    ) -> CommunicationEffectRecord:
        case = self.store.get_case(commitment.case_id)
        if case is None or case.policy_ref is None:
            raise CommitmentIntakeError("communication requires a current governed case")
        if case.authority_epoch != commitment.authority_epoch:
            raise CommitmentIntakeError(
                "communication requires commitment revalidation after an authority epoch change"
            )
        if draft_kind not in {"confirmation", "reminder"}:
            raise CommitmentIntakeError("unsupported communication draft kind")
        text = self.communication_text(commitment, draft_kind)
        stored = self.artifact_store.put(text.encode("utf-8"))
        draft_id = uuid5(
            M9_NAMESPACE, f"draft:{commitment.commitment_id}:{commitment.version}:{draft_kind}"
        )
        draft = CommunicationDraftRecord(
            draft_id=draft_id,
            case_id=commitment.case_id,
            authority_epoch=commitment.authority_epoch,
            channel="feishu-one-to-one",
            recipient_principal_id=commitment.committer_principal_id,
            recipient_external_subject=commitment.committer_external_subject,
            content_storage_ref=stored.storage_ref,
            content_digest=stored.digest,
            content_size=stored.size,
            draft_kind=draft_kind,
            generator_ref=f"administrative-orchestrator:m9-template:{draft_kind}:v1",
            created_at=commitment.updated_at,
        )
        self.repository.put_draft(draft)
        approval = self.uow.authority.get_approval_satisfaction(
            commitment.case_id, commitment.authority_epoch
        )
        if approval is None:
            raise CommitmentIntakeError("communication requires current approval satisfaction")
        governance = self.uow.governance.get_current_for_case(
            commitment.case_id, commitment.authority_epoch
        )
        if governance is None:
            raise CommitmentIntakeError("communication requires current governance basis")
        authorization = mint_execution_authorization_from_approval(
            case,
            approval,
            issuer_principal_id="service:administrative-orchestrator",
            target_system="communication",
            allowed_operations=("message.send",),
            authority_class=AuthorityClass.NORMAL,
        ).model_copy(
            update={
                "authorization_id": uuid5(
                    M9_NAMESPACE,
                    f"authorization:{commitment.case_id}:{commitment.authority_epoch}",
                ),
                "issued_at": commitment.updated_at,
            }
        )
        existing_authorization = self.execution.get_authorization(authorization.authorization_id)
        if existing_authorization is None:
            authorization = self.execution.put_authorization(authorization)
        else:
            if (
                existing_authorization.model_copy(update={"issued_at": authorization.issued_at})
                != authorization
            ):
                raise ExecutionConflict("communication authorization semantics drifted")
            authorization = existing_authorization
        effect_ids = {
            kind: uuid5(
                M9_NAMESPACE,
                f"effect:{commitment.commitment_id}:{commitment.version}:{kind}",
            )
            for kind in ("confirmation", "reminder")
        }
        obligation_ids = {
            kind: uuid5(M9_NAMESPACE, f"obligation:{effect_ids[kind]}")
            for kind in effect_ids
        }

        def build_obligation(kind: str) -> AdministrativeObligation:
            return AdministrativeObligation(
                obligation_id=obligation_ids[kind],
                case_id=commitment.case_id,
                authority_epoch=commitment.authority_epoch,
                governance_basis_id=governance.basis_id,
                kind=f"meeting-commitment-communication:{kind}",
                subject_ref=case.subject_ref,
                target_system="communication",
                required_operation="message.send",
                expected_postcondition={
                    "communication_event_id": str(uuid5(M9_NAMESPACE, f"event:{effect_ids[kind]}")),
                    "recipient_external_subject": commitment.committer_external_subject,
                    "content_digest": (
                        stored.digest
                        if kind == draft_kind
                        else hashlib.sha256(
                            self.communication_text(commitment, kind).encode("utf-8")
                        ).hexdigest()
                    ),
                    "transport_accepted": True,
                    "delivery_confirmed": True,
                    "read_state": "unknown",
                },
                authority_class=AuthorityClass.NORMAL,
                fulfillment_kind=ObligationFulfillmentKind.EXTERNAL_EFFECT_VERIFIED,
            )

        obligation_set = AdministrativeObligationSet(
            requirement_id=uuid5(
                M9_NAMESPACE,
                f"obligation-set:{commitment.case_id}:{commitment.authority_epoch}",
            ),
            case_id=commitment.case_id,
            authority_epoch=commitment.authority_epoch,
            governance_basis_id=governance.basis_id,
            obligations=(build_obligation("confirmation"), build_obligation("reminder")),
        )
        existing_obligation_set = self.obligations.get_current(
            commitment.case_id,
            commitment.authority_epoch,
        )
        if existing_obligation_set is None:
            self.obligations.put(obligation_set)
            obligation = next(
                item
                for item in obligation_set.obligations
                if item.obligation_id == obligation_ids[draft_kind]
            )
            effect_id = effect_ids[draft_kind]
        else:
            if existing_obligation_set.governance_basis_id != governance.basis_id:
                raise CommitmentIntakeError("communication obligation governance basis drifted")
            obligation = next(
                (
                    item
                    for item in existing_obligation_set.obligations
                    if item.kind == f"meeting-commitment-communication:{draft_kind}"
                ),
                None,
            )
            if obligation is None:
                raise CommitmentIntakeError("communication obligation kind is unavailable")
            links = self.obligations.list_links(
                commitment.case_id,
                commitment.authority_epoch,
            )
            linked_effect = next(
                (item.effect_id for item in links if item.obligation_id == obligation.obligation_id),
                None,
            )
            effect_id = linked_effect or uuid5(
                M9_NAMESPACE,
                f"effect:{obligation.obligation_id}",
            )

        communication_event_id = uuid5(M9_NAMESPACE, f"event:{effect_id}")
        if existing_obligation_set is not None:
            expected_postcondition = obligation.expected_postcondition
            expected_event_id = expected_postcondition.get("communication_event_id")
            expected_recipient = expected_postcondition.get("recipient_external_subject")
            expected_content_digest = expected_postcondition.get("content_digest")
            if not isinstance(expected_event_id, str):
                raise CommitmentIntakeError(
                    "communication obligation event identity is unavailable"
                )
            try:
                communication_event_id = UUID(expected_event_id)
            except ValueError as exc:
                raise CommitmentIntakeError(
                    "communication obligation event identity is invalid"
                ) from exc
            if (
                expected_recipient != draft.recipient_external_subject
                or expected_content_digest != draft.content_digest
            ):
                raise CommitmentIntakeError(
                    "communication obligation postcondition drifted"
                )

        effect = plan_effect(
            case,
            authorization,
            operation="message.send",
            reversibility=EffectReversibility.IRREVERSIBLE,
        ).model_copy(
            update={
                "effect_id": effect_id,
                "obligation_id": obligation.obligation_id,
                "governance_basis_id": obligation_set.governance_basis_id,
                "created_at": commitment.updated_at,
                "updated_at": commitment.updated_at,
            }
        )
        self.execution.put_effect(effect)
        self.obligations.link_effect(effect, obligation)
        event = CommunicationEffectRecord(
            communication_event_id=communication_event_id,
            case_id=commitment.case_id,
            authority_epoch=commitment.authority_epoch,
            draft_id=draft_id,
            effect_id=effect_id,
            delivery_state=CommunicationDeliveryState.PREPARED,
            created_at=commitment.updated_at,
            updated_at=commitment.updated_at,
        )
        return self.repository.put_communication(event)

    def dispatch(self, communication_event_id: UUID) -> CommunicationEffectRecord:
        """Transport one prepared draft; body content never enters the ledger."""

        communication = self.repository.get_communication_event(communication_event_id)
        if communication is None:
            raise CommitmentIntakeError("communication event not found")
        if communication.delivery_state is not CommunicationDeliveryState.PREPARED:
            return communication
        draft = self.repository.get_draft(communication.draft_id)
        case = self.store.get_case(communication.case_id)
        commitment = self.repository.get_commitment(communication.case_id)
        if draft is None or case is None or commitment is None:
            raise CommitmentIntakeError("communication lineage is incomplete")
        if communication.authority_epoch != commitment.authority_epoch:
            stale = communication.model_copy(
                update={
                    "delivery_state": CommunicationDeliveryState.PERMANENT_FAILED,
                    "last_error_code": "STALE_AUTHORITY_EPOCH",
                    "updated_at": utcnow(),
                }
            )
            return self.repository.update_communication(stale)

        if self.settings.world_runtime_mode == "cutover":
            return self.dispatch_via_world_runtime(
                communication=communication,
                draft=draft,
            )

        gateway = self.settings.communication_gateway_base_url.strip().rstrip("/")
        secret = self.communication_secret()
        if not gateway or not secret:
            retrying = communication.model_copy(
                update={
                    "delivery_state": CommunicationDeliveryState.RETRYING,
                    "last_error_code": "COMMUNICATION_TRANSPORT_NOT_CONFIGURED",
                    "updated_at": utcnow(),
                }
            )
            return self.repository.update_communication(retrying)
        body = json.dumps(
            {
                "eventId": str(communication.communication_event_id),
                "recipientOpenId": draft.recipient_external_subject,
                "text": self.artifact_store.get(
                    draft.content_storage_ref, expected_digest=draft.content_digest
                ).decode("utf-8"),
                "draftKind": draft.draft_kind,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        timestamp = str(int(time.time()))
        digest = hashlib.sha256(body).hexdigest()
        signature = hmac.new(
            secret.encode("utf-8"),
            f"{timestamp}\n{communication.communication_event_id}\n{digest}".encode(),
            hashlib.sha256,
        ).hexdigest()
        try:
            response = self.http_post(
                f"{gateway}/v1/administrative/communications",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Event-ID": str(communication.communication_event_id),
                    "X-Timestamp": timestamp,
                    "X-Signature": signature,
                },
                timeout=self.settings.communication_gateway_timeout_seconds,
            )
            if response.status_code >= 400:
                next_state = (
                    CommunicationDeliveryState.OUTCOME_UNKNOWN
                    if response.status_code in {408, 425, 429, 500, 502, 503, 504}
                    else CommunicationDeliveryState.PERMANENT_FAILED
                )
                failed = communication.model_copy(
                    update={
                        "delivery_state": next_state,
                        "last_error_code": f"GATEWAY_HTTP_{response.status_code}",
                        "attempts": communication.attempts + 1,
                        "updated_at": utcnow(),
                    }
                )
                return self.repository.update_communication(failed)
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("communication gateway returned a non-object response")
            confirmed = bool(payload.get("deliveryConfirmed", False))
            sent = communication.model_copy(
                update={
                    "delivery_state": (
                        CommunicationDeliveryState.DELIVERY_CONFIRMED
                        if confirmed
                        else CommunicationDeliveryState.TRANSPORT_ACCEPTED
                    ),
                    "provider_message_ref": payload.get("providerMessageRef"),
                    "attempts": communication.attempts + 1,
                    "last_error_code": None,
                    "updated_at": utcnow(),
                }
            )
            return self.repository.update_communication(sent)
        except (httpx.HTTPError, ValueError, UnicodeError) as exc:
            unknown = communication.model_copy(
                update={
                    "delivery_state": CommunicationDeliveryState.OUTCOME_UNKNOWN,
                    "last_error_code": type(exc).__name__,
                    "attempts": communication.attempts + 1,
                    "updated_at": utcnow(),
                }
            )
            return self.repository.update_communication(unknown)

    def dispatch_via_world_runtime(
        self,
        *,
        communication: CommunicationEffectRecord,
        draft: CommunicationDraftRecord,
    ) -> CommunicationEffectRecord:
        effect = self.execution.get_effect(communication.effect_id)
        if effect is None:
            raise CommitmentIntakeError("communication effect lineage is incomplete")
        bridge = self.bridge_factory(self.store, self.settings)
        try:
            provider = WorldRuntimeEffectProvider(_NoCommunicationFallback(), bridge)
            result = provider.execute(
                effect,
                {
                    "communication_event_id": str(communication.communication_event_id),
                    "recipient_open_id": draft.recipient_external_subject,
                    "content_storage_ref": draft.content_storage_ref,
                    "content_digest": draft.content_digest,
                    "draft_kind": draft.draft_kind,
                },
            )
        finally:
            bridge.close()
        state = CommunicationDeliveryState.OUTCOME_UNKNOWN
        error_code = "WORLD_RUNTIME_EXECUTION_OUTCOME_UNKNOWN"
        provider_message_ref: str | None = None
        if result.status.value == "failed":
            state = CommunicationDeliveryState.PERMANENT_FAILED
            error_code = "WORLD_RUNTIME_EXECUTION_FAILED"
        elif result.status.value == "succeeded":
            # Runtime provider success proves execution acceptance, not human delivery.
            # An independent Administrative read-back may promote this later.
            state = CommunicationDeliveryState.TRANSPORT_ACCEPTED
            error_code = None
            provider_message_ref = result.provider_ref
        updated = communication.model_copy(
            update={
                "delivery_state": state,
                "provider_message_ref": provider_message_ref,
                "attempts": communication.attempts + 1,
                "last_error_code": error_code,
                "updated_at": utcnow(),
            }
        )
        return self.repository.update_communication(updated)

    def communication_secret(self) -> str:
        value = self.settings.communication_transport_secret
        if value is not None:
            secret = value.get_secret_value().strip()
            if secret:
                return secret
        path = self.settings.communication_transport_secret_file.strip()
        if not path:
            return ""
        secret_path = Path(path)
        if not secret_path.is_file() or secret_path.is_symlink():
            return ""
        return secret_path.read_text(encoding="utf-8").strip()

    @staticmethod
    def communication_text(commitment: CommitmentRecord, draft_kind: str) -> str:
        label = "确认" if draft_kind == "confirmation" else "提醒"
        return (
            f"行政承诺{label}：请确认你承诺在 {commitment.due_at.isoformat()} 前完成："
            f"{commitment.commitment_action}。回复仅用于记录，不代表承诺已完成。"
        )


__all__ = ["CommitmentCommunicationCoordinator"]
