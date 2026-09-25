from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from .authority import DecisionAuthorityBindingRow
from .domain import Decision, EffectRealizationAssessment, ExecutionAuthorization
from .execution_repository import ExecutionRepository
from .persistence import AuthorizationRow, DecisionRow, EffectRow, RealizationRow, SqlStore


def list_decisions(store: SqlStore, case_id: UUID) -> list[Decision]:
    with store.sessions() as db:
        rows = (
            db.execute(
                select(DecisionRow)
                .where(DecisionRow.case_id == case_id)
                .order_by(DecisionRow.decided_at, DecisionRow.decision_id)
            )
            .scalars()
            .all()
        )
        decisions: list[Decision] = []
        for row in rows:
            decision = ExecutionRepository._decision_from_row(row)
            binding = db.get(DecisionAuthorityBindingRow, decision.decision_id)
            if binding is not None:
                decision = decision.model_copy(update={"decision_role": binding.decision_role})
            decisions.append(decision)
        return decisions


def list_authorizations(store: SqlStore, case_id: UUID) -> list[ExecutionAuthorization]:
    with store.sessions() as db:
        rows = (
            db.execute(
                select(AuthorizationRow)
                .where(AuthorizationRow.case_id == case_id)
                .order_by(AuthorizationRow.issued_at, AuthorizationRow.authorization_id)
            )
            .scalars()
            .all()
        )
        return [ExecutionRepository._authorization_from_row(row) for row in rows]


def list_realizations(store: SqlStore, case_id: UUID) -> list[EffectRealizationAssessment]:
    with store.sessions() as db:
        rows = (
            db.execute(
                select(RealizationRow)
                .join(EffectRow, EffectRow.effect_id == RealizationRow.effect_id)
                .where(EffectRow.case_id == case_id)
                .order_by(RealizationRow.assessed_at, RealizationRow.assessment_id)
            )
            .scalars()
            .all()
        )
        return [ExecutionRepository._realization_from_row(row) for row in rows]


__all__ = ["list_authorizations", "list_decisions", "list_realizations"]
