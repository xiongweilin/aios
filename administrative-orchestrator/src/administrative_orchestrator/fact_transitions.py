from __future__ import annotations

from .domain import AdministrativeCase, CaseStatus, FactSnapshot
from .service import TransitionError, utcnow


def replace_facts_for_reevaluation(
    case: AdministrativeCase,
    fact_snapshot: FactSnapshot,
) -> AdministrativeCase:
    """Replace current facts and force the case back through policy evaluation.

    A changed fact world invalidates the current policy/decision authority.  The
    immutable prior FactSnapshot remains in history; only the current projection
    is replaced here.
    """
    if case.status in {CaseStatus.COMPLETED, CaseStatus.CANCELLED}:
        raise TransitionError("terminal case cannot replace current facts")
    return case.model_copy(
        update={
            "fact_snapshot": fact_snapshot,
            "policy_ref": None,
            "status": CaseStatus.GATHERING_FACTS,
            "reopen_reason": None,
            "version": case.version + 1,
            "authority_epoch": case.authority_epoch + 1,
            "updated_at": utcnow(),
        }
    )


__all__ = ["replace_facts_for_reevaluation"]
