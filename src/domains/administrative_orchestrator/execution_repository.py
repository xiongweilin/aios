from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import (
    ConfirmedOutcome,
    Decision,
    EffectRealizationAssessment,
    EffectRecord,
    EffectStatus,
    ExecutionAuthorization,
)
from .obligations import EffectObligationLinkRow
from .persistence import (
    AuthorizationRow,
    DecisionRow,
    EffectRow,
    OutcomeRow,
    RealizationRow,
    SqlStore,
    utcnow,
)


class ExecutionConflict(RuntimeError):
    pass


class ExecutionRepository:
    """Idempotent persistence surface for replayable durable execution steps."""

    def __init__(self, store: SqlStore) -> None:
        self.store = store

    def get_latest_decision(self, case_id: UUID) -> Decision | None:
        with self.store.sessions() as db:
            row = (
                db.execute(
                    select(DecisionRow)
                    .where(DecisionRow.case_id == case_id)
                    .order_by(DecisionRow.decided_at.desc(), DecisionRow.decision_id.desc())
                    .limit(1)
                )
                .scalars()
                .first()
            )
            return None if row is None else self._decision_from_row(row)

    def get_authorization(self, authorization_id: UUID) -> ExecutionAuthorization | None:
        with self.store.sessions() as db:
            row = db.get(AuthorizationRow, authorization_id)
            return None if row is None else self._authorization_from_row(row)

    def put_authorization(
        self,
        authorization: ExecutionAuthorization,
    ) -> ExecutionAuthorization:
        with self.store.sessions.begin() as db:
            row = db.get(AuthorizationRow, authorization.authorization_id)
            if row is not None:
                restored = self._authorization_from_row(row)
                if restored != authorization:
                    raise ExecutionConflict("authorization id already exists with different semantics")
                return restored
            db.add(
                AuthorizationRow(
                    authorization_id=authorization.authorization_id,
                    case_id=authorization.case_id,
                    case_version=authorization.case_version,
                    authority_epoch=authorization.authority_epoch,
                    decision_id=authorization.decision_id,
                    approval_satisfaction_id=authorization.approval_satisfaction_id,
                    issuer_principal_id=authorization.issuer_principal_id,
                    target_system=authorization.target_system,
                    subject_ref=authorization.subject_ref,
                    allowed_operations=list(authorization.allowed_operations),
                    authority_class=authorization.authority_class.value,
                    policy_json=authorization.policy_ref.model_dump(mode="json"),
                    issued_at=authorization.issued_at,
                    expires_at=authorization.expires_at,
                    revoked_at=authorization.revoked_at,
                )
            )
            self.store._append_audit(
                db,
                authorization.case_id,
                "authorization.issued",
                {
                    "authorization_id": str(authorization.authorization_id),
                    "decision_id": (
                        str(authorization.decision_id) if authorization.decision_id else None
                    ),
                    "approval_satisfaction_id": (
                        str(authorization.approval_satisfaction_id)
                        if authorization.approval_satisfaction_id
                        else None
                    ),
                    "authority_epoch": authorization.authority_epoch,
                    "target_system": authorization.target_system,
                    "allowed_operations": list(authorization.allowed_operations),
                },
            )
            return authorization

    def put_effect(self, effect: EffectRecord) -> EffectRecord:
        with self.store.sessions.begin() as db:
            row = db.get(EffectRow, effect.effect_id)
            if row is not None:
                restored = self._effect_from_row(
                    row, self._effect_lineage(db, row.effect_id)
                )
                if self._effect_identity(restored) != self._effect_identity(effect):
                    raise ExecutionConflict("effect id already exists with different semantics")
                return restored
            db.add(
                EffectRow(
                    effect_id=effect.effect_id,
                    case_id=effect.case_id,
                    case_version=effect.case_version,
                    authority_epoch=effect.authority_epoch,
                    authorization_id=effect.authorization_id,
                    target_system=effect.target_system,
                    operation=effect.operation,
                    subject_ref=effect.subject_ref,
                    reversibility=effect.reversibility.value,
                    authority_class=effect.authority_class.value,
                    status=effect.status.value,
                    provider_ref=effect.provider_ref,
                    created_at=effect.created_at,
                    updated_at=effect.updated_at,
                )
            )
            self.store._append_audit(
                db,
                effect.case_id,
                "effect.planned",
                {
                    "effect_id": str(effect.effect_id),
                    "authorization_id": str(effect.authorization_id),
                    "authority_epoch": effect.authority_epoch,
                    "target_system": effect.target_system,
                    "operation": effect.operation,
                },
            )
            return effect

    def get_effect(self, effect_id: UUID) -> EffectRecord | None:
        with self.store.sessions() as db:
            row = db.get(EffectRow, effect_id)
            return (
                None
                if row is None
                else self._effect_from_row(row, self._effect_lineage(db, row.effect_id))
            )

    def list_effects(self, case_id: UUID, authority_epoch: int) -> list[EffectRecord]:
        with self.store.sessions() as db:
            rows = (
                db.execute(
                    select(EffectRow)
                    .where(
                        EffectRow.case_id == case_id,
                        EffectRow.authority_epoch == authority_epoch,
                    )
                    .order_by(EffectRow.target_system, EffectRow.operation, EffectRow.effect_id)
                )
                .scalars()
                .all()
            )
            return [
                self._effect_from_row(row, self._effect_lineage(db, row.effect_id))
                for row in rows
            ]

    def set_effect_status(
        self,
        effect_id: UUID,
        *,
        status: EffectStatus,
        provider_ref: str | None = None,
    ) -> EffectRecord:
        with self.store.sessions.begin() as db:
            row = db.get(EffectRow, effect_id)
            if row is None:
                raise KeyError(f"effect {effect_id} not found")
            if row.status == status.value and (provider_ref is None or row.provider_ref == provider_ref):
                return self._effect_from_row(row, self._effect_lineage(db, row.effect_id))
            row.status = status.value
            if provider_ref is not None:
                row.provider_ref = provider_ref
            row.updated_at = utcnow()
            self.store._append_audit(
                db,
                row.case_id,
                "effect.status_changed",
                {
                    "effect_id": str(effect_id),
                    "status": status.value,
                    "provider_ref": row.provider_ref,
                },
            )
            db.flush()
            return self._effect_from_row(
                row, self._effect_lineage(db, row.effect_id)
            )

    def put_realization(
        self,
        assessment: EffectRealizationAssessment,
        *,
        case_id: UUID,
    ) -> EffectRealizationAssessment:
        with self.store.sessions.begin() as db:
            effect = db.get(EffectRow, assessment.effect_id)
            if effect is None:
                raise ExecutionConflict("realization requires a persisted effect")
            if effect.case_id != case_id:
                raise ExecutionConflict("realization case does not match its effect")
            row = db.get(RealizationRow, assessment.assessment_id)
            if row is not None:
                restored = self._realization_from_row(row)
                if restored != assessment:
                    raise ExecutionConflict("realization id already exists with different semantics")
                return restored
            db.add(
                RealizationRow(
                    assessment_id=assessment.assessment_id,
                    effect_id=assessment.effect_id,
                    disposition=assessment.disposition.value,
                    evidence_json=[item.model_dump(mode="json") for item in assessment.evidence],
                    assessed_at=assessment.assessed_at,
                )
            )
            self.store._append_audit(
                db,
                case_id,
                "effect.realization_assessed",
                {
                    "assessment_id": str(assessment.assessment_id),
                    "effect_id": str(assessment.effect_id),
                    "disposition": assessment.disposition.value,
                },
            )
            return assessment

    def get_realization(self, assessment_id: UUID) -> EffectRealizationAssessment | None:
        with self.store.sessions() as db:
            row = db.get(RealizationRow, assessment_id)
            return None if row is None else self._realization_from_row(row)

    def list_realizations(
        self,
        case_id: UUID,
        authority_epoch: int | None = None,
    ) -> list[EffectRealizationAssessment]:
        with self.store.sessions() as db:
            statement = (
                select(RealizationRow)
                .join(EffectRow, EffectRow.effect_id == RealizationRow.effect_id)
                .where(EffectRow.case_id == case_id)
            )
            if authority_epoch is not None:
                statement = statement.where(EffectRow.authority_epoch == authority_epoch)
            rows = (
                db.execute(
                    statement.order_by(
                        RealizationRow.assessed_at,
                        RealizationRow.assessment_id,
                    )
                )
                .scalars()
                .all()
            )
            return [self._realization_from_row(row) for row in rows]

    def put_outcome(self, outcome: ConfirmedOutcome) -> ConfirmedOutcome:
        with self.store.sessions.begin() as db:
            effect = db.get(EffectRow, outcome.effect_id)
            if effect is None:
                raise ExecutionConflict("outcome requires a persisted effect")
            realization = db.get(
                RealizationRow, outcome.realization_assessment_id
            )
            if realization is None:
                raise ExecutionConflict("outcome requires a persisted realization")
            if realization.effect_id != outcome.effect_id:
                raise ExecutionConflict(
                    "outcome realization belongs to a different effect"
                )
            if (
                effect.case_id != outcome.case_id
                or effect.case_version != outcome.case_version
                or effect.authority_epoch != outcome.authority_epoch
            ):
                raise ExecutionConflict(
                    "outcome case, version, or authority epoch does not match its effect"
                )
            row = db.get(OutcomeRow, outcome.outcome_id)
            if row is not None:
                restored = self._outcome_from_row(row)
                if restored != outcome:
                    raise ExecutionConflict("outcome id already exists with different semantics")
                return restored
            db.add(
                OutcomeRow(
                    outcome_id=outcome.outcome_id,
                    case_id=outcome.case_id,
                    case_version=outcome.case_version,
                    authority_epoch=outcome.authority_epoch,
                    effect_id=outcome.effect_id,
                    realization_assessment_id=outcome.realization_assessment_id,
                    outcome_kind=outcome.outcome_kind,
                    evidence_json=[item.model_dump(mode="json") for item in outcome.evidence],
                    confirmed_at=outcome.confirmed_at,
                )
            )
            self.store._append_audit(
                db,
                outcome.case_id,
                "outcome.confirmed",
                {
                    "outcome_id": str(outcome.outcome_id),
                    "effect_id": str(outcome.effect_id),
                    "outcome_kind": outcome.outcome_kind,
                    "authority_epoch": outcome.authority_epoch,
                },
            )
            return outcome

    def get_outcome(self, outcome_id: UUID) -> ConfirmedOutcome | None:
        with self.store.sessions() as db:
            row = db.get(OutcomeRow, outcome_id)
            return None if row is None else self._outcome_from_row(row)

    def list_outcomes(
        self,
        case_id: UUID,
        authority_epoch: int | None = None,
    ) -> list[ConfirmedOutcome]:
        with self.store.sessions() as db:
            statement = select(OutcomeRow).where(OutcomeRow.case_id == case_id)
            if authority_epoch is not None:
                statement = statement.where(OutcomeRow.authority_epoch == authority_epoch)
            rows = (
                db.execute(
                    statement.order_by(OutcomeRow.confirmed_at, OutcomeRow.outcome_id)
                )
                .scalars()
                .all()
            )
            return [self._outcome_from_row(row) for row in rows]

    @staticmethod
    def _decision_from_row(row: DecisionRow) -> Decision:
        return Decision.model_validate(
            {
                "decision_id": row.decision_id,
                "case_id": row.case_id,
                "case_version": row.case_version,
                "authority_epoch": row.authority_epoch,
                "principal_id": row.principal_id,
                "decision_role": row.decision_role,
                "disposition": row.disposition,
                "rationale": row.rationale,
                "policy_ref": row.policy_json,
                "decided_at": row.decided_at,
            }
        )

    @staticmethod
    def _authorization_from_row(row: AuthorizationRow) -> ExecutionAuthorization:
        return ExecutionAuthorization.model_validate(
            {
                "authorization_id": row.authorization_id,
                "case_id": row.case_id,
                "case_version": row.case_version,
                "authority_epoch": row.authority_epoch,
                "decision_id": row.decision_id,
                "approval_satisfaction_id": row.approval_satisfaction_id,
                "issuer_principal_id": row.issuer_principal_id,
                "target_system": row.target_system,
                "subject_ref": row.subject_ref,
                "allowed_operations": tuple(row.allowed_operations),
                "authority_class": row.authority_class,
                "policy_ref": row.policy_json,
                "issued_at": row.issued_at,
                "expires_at": row.expires_at,
                "revoked_at": row.revoked_at,
            }
        )

    @staticmethod
    def _effect_lineage(
        db: Session, effect_id: UUID
    ) -> EffectObligationLinkRow | None:
        return db.get(EffectObligationLinkRow, effect_id)

    @staticmethod
    def _effect_from_row(
        row: EffectRow,
        lineage: EffectObligationLinkRow | None = None,
    ) -> EffectRecord:
        return EffectRecord.model_validate(
            {
                "effect_id": row.effect_id,
                "case_id": row.case_id,
                "case_version": row.case_version,
                "authority_epoch": row.authority_epoch,
                "authorization_id": row.authorization_id,
                "obligation_id": (
                    lineage.obligation_id if lineage is not None else None
                ),
                "governance_basis_id": (
                    lineage.governance_basis_id if lineage is not None else None
                ),
                "target_system": row.target_system,
                "operation": row.operation,
                "subject_ref": row.subject_ref,
                "reversibility": row.reversibility,
                "authority_class": row.authority_class,
                "status": row.status,
                "provider_ref": row.provider_ref,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )

    @staticmethod
    def _realization_from_row(row: RealizationRow) -> EffectRealizationAssessment:
        return EffectRealizationAssessment.model_validate(
            {
                "assessment_id": row.assessment_id,
                "effect_id": row.effect_id,
                "disposition": row.disposition,
                "evidence": row.evidence_json,
                "assessed_at": row.assessed_at,
            }
        )

    @staticmethod
    def _outcome_from_row(row: OutcomeRow) -> ConfirmedOutcome:
        return ConfirmedOutcome.model_validate(
            {
                "outcome_id": row.outcome_id,
                "case_id": row.case_id,
                "case_version": row.case_version,
                "authority_epoch": row.authority_epoch,
                "effect_id": row.effect_id,
                "realization_assessment_id": row.realization_assessment_id,
                "outcome_kind": row.outcome_kind,
                "evidence": row.evidence_json,
                "confirmed_at": row.confirmed_at,
            }
        )

    @staticmethod
    def _effect_identity(effect: EffectRecord) -> tuple[object, ...]:
        return (
            effect.effect_id,
            effect.case_id,
            effect.authority_epoch,
            effect.authorization_id,
            effect.target_system,
            effect.operation,
            effect.subject_ref,
            effect.reversibility,
            effect.authority_class,
        )
