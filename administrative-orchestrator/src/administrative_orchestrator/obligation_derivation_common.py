from __future__ import annotations

from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from .domain import AdministrativeCase, AuthorityClass
from .obligations import (
    AdministrativeObligation,
    ObligationFulfillmentKind,
)


def domain_or_external_obligation(
    case: AdministrativeCase,
    governance_basis_id: UUID,
    *,
    discriminator: str,
    kind: str,
    target_system: str,
    operation: str,
    expected_postcondition: dict[str, Any],
    authority_class: AuthorityClass,
    fulfillment_kind: ObligationFulfillmentKind,
) -> AdministrativeObligation:
    """Construct one stable domain-owned obligation from qualified semantics."""
    return AdministrativeObligation(
        obligation_id=uuid5(
            NAMESPACE_URL,
            f"administrative:obligation:{case.case_id}:{case.authority_epoch}:"
            f"{discriminator}",
        ),
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        governance_basis_id=governance_basis_id,
        kind=kind,
        subject_ref=case.subject_ref,
        target_system=target_system,
        required_operation=operation,
        expected_postcondition=expected_postcondition,
        authority_class=authority_class,
        required=True,
        fulfillment_kind=fulfillment_kind,
    )


__all__ = ["domain_or_external_obligation"]
