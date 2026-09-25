from __future__ import annotations

import inspect

import administrative_orchestrator.obligations as obligation_core
from administrative_orchestrator import offboarding_execution, onboarding_execution
from administrative_orchestrator.financial_obligations import (
    derive_financial_obligations,
)
from administrative_orchestrator.obligation_derivation import (
    derive_administrative_obligations,
)
from administrative_orchestrator.offboarding_obligations import (
    derive_offboarding_obligations,
)
from administrative_orchestrator.onboarding_obligations import (
    derive_onboarding_obligations,
)


def test_compatibility_facade_preserves_derivation_signatures() -> None:
    assert inspect.signature(obligation_core.derive_onboarding_obligations) == inspect.signature(
        derive_onboarding_obligations
    )
    assert inspect.signature(obligation_core.derive_offboarding_obligations) == inspect.signature(
        derive_offboarding_obligations
    )
    assert inspect.signature(obligation_core.derive_financial_obligations) == inspect.signature(
        derive_financial_obligations
    )
    assert inspect.signature(
        obligation_core.derive_administrative_obligations
    ) == inspect.signature(derive_administrative_obligations)


def test_generic_obligation_core_contains_no_domain_interpretation_literals() -> None:
    source = inspect.getsource(obligation_core)
    for literal in (
        '"employee-onboarding"',
        '"employee-offboarding"',
        '"procurement-request"',
        '"invoice-ap-preparation"',
        '"expense-reimbursement"',
        '"identity.disable"',
        '"sessions.revoke"',
        '"employee.deactivate"',
        '"purchase_order.create_draft"',
        '"purchase_order.confirm"',
        '"vendor_bill.create_draft"',
        '"expense_report.create"',
    ):
        assert literal not in source


def test_execution_paths_import_derivations_from_domain_owners() -> None:
    onboarding_source = inspect.getsource(onboarding_execution)
    assert (
        "from .onboarding_obligations import derive_onboarding_obligations"
        in onboarding_source
    )
    assert (
        "from .financial_obligations import derive_financial_obligations"
        in onboarding_source
    )
    assert "derive_onboarding_obligations," not in onboarding_source.split(
        "from .obligations import (", 1
    )[1].split(")", 1)[0]
    assert "derive_financial_obligations," not in onboarding_source.split(
        "from .obligations import (", 1
    )[1].split(")", 1)[0]

    offboarding_source = inspect.getsource(offboarding_execution)
    assert (
        "from .offboarding_obligations import derive_offboarding_obligations"
        in offboarding_source
    )
    assert "derive_offboarding_obligations," not in offboarding_source.split(
        "from .obligations import (", 1
    )[1].split(")", 1)[0]
