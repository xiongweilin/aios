from __future__ import annotations

import inspect
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, select, text

from administrative_orchestrator.config import get_settings
from administrative_orchestrator.domain import AdministrativeRequest, AuthorityClass
from administrative_orchestrator.obligations import (
    AdministrativeObligation,
    AdministrativeObligationSet,
    ObligationError,
    ObligationRepository,
    ObligationRow,
)
from administrative_orchestrator.persistence import SqlStore
from administrative_orchestrator.service import create_case
from alembic import command


def _case(store: SqlStore):
    request = AdministrativeRequest(
        requester_principal_id="person:test",
        channel="test",
        intent="prove declared obligation ordering",
    )
    case = create_case(
        request,
        case_kind="ordering-test",
        subject_ref="subject:test",
    )
    store.create_case(request, case)
    return case


def _obligation(case, governance_basis_id, operation: str):
    return AdministrativeObligation(
        obligation_id=uuid4(),
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        governance_basis_id=governance_basis_id,
        kind=f"test.{operation}",
        subject_ref=case.subject_ref,
        target_system="test-system",
        required_operation=operation,
        expected_postcondition={"operation": operation},
        authority_class=AuthorityClass.EMPLOYMENT,
    )


def test_repository_round_trip_preserves_declared_tuple_order() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    case = _case(store)
    basis_id = uuid4()
    declared = tuple(
        _obligation(case, basis_id, operation)
        for operation in ("zeta", "alpha", "middle")
    )
    obligation_set = AdministrativeObligationSet(
        requirement_id=uuid4(),
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        governance_basis_id=basis_id,
        obligations=declared,
    )

    repository = ObligationRepository(store)
    repository.put(obligation_set)
    restored = repository.get_current(case.case_id, case.authority_epoch)

    assert restored == obligation_set
    with store.sessions() as db:
        rows = (
            db.execute(
                select(ObligationRow)
                .where(ObligationRow.requirement_id == obligation_set.requirement_id)
                .order_by(ObligationRow.sequence)
            )
            .scalars()
            .all()
        )
    assert [row.sequence for row in rows] == [0, 1, 2]
    assert [row.required_operation for row in rows] == ["zeta", "alpha", "middle"]


def test_repository_fails_closed_on_non_contiguous_persisted_sequence() -> None:
    store = SqlStore("sqlite+pysqlite:///:memory:")
    store.init_schema()
    case = _case(store)
    basis_id = uuid4()
    obligation_set = AdministrativeObligationSet(
        requirement_id=uuid4(),
        case_id=case.case_id,
        authority_epoch=case.authority_epoch,
        governance_basis_id=basis_id,
        obligations=(
            _obligation(case, basis_id, "first"),
            _obligation(case, basis_id, "second"),
        ),
    )
    repository = ObligationRepository(store)
    repository.put(obligation_set)

    with store.sessions.begin() as db:
        second = (
            db.execute(
                select(ObligationRow)
                .where(ObligationRow.requirement_id == obligation_set.requirement_id)
                .order_by(ObligationRow.sequence)
            )
            .scalars()
            .all()[1]
        )
        second.sequence = 7

    with pytest.raises(ObligationError, match="contiguous"):
        repository.get_current(case.case_id, case.authority_epoch)


def test_runtime_repository_contains_no_domain_operation_ordering() -> None:
    source = inspect.getsource(ObligationRepository)
    for operation in (
        "purchase_order.create_draft",
        "purchase_order.confirm",
        "vendor_bill.create_draft",
        "expense_report.create",
    ):
        assert operation not in source


def test_0032_backfills_historical_runtime_order(monkeypatch, tmp_path) -> None:
    database_path = tmp_path / "obligation-sequence.db"
    database_url = f"sqlite+pysqlite:///{database_path}"
    monkeypatch.setenv("ADMIN_DATABASE_URL", database_url)
    get_settings.cache_clear()
    repo_root = Path(__file__).resolve().parents[3]
    config = Config()
    config.set_main_option(
        "script_location",
        str((repo_root / "migrations/domains/administrative/alembic").resolve()),
    )
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

    try:
        command.upgrade(config, "0031_adaptive_investigation")
        engine = create_engine(database_url, future=True)
        requirement_id = uuid4().hex
        case_id = uuid4().hex
        basis_id = uuid4().hex
        confirm_id = uuid4().hex
        draft_id = uuid4().hex
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO administrative_obligation_set "
                    "(requirement_id, case_id, authority_epoch, governance_basis_id) "
                    "VALUES (:requirement_id, :case_id, 1, :basis_id)"
                ),
                {
                    "requirement_id": requirement_id,
                    "case_id": case_id,
                    "basis_id": basis_id,
                },
            )
            for obligation_id, operation in (
                (confirm_id, "purchase_order.confirm"),
                (draft_id, "purchase_order.create_draft"),
            ):
                connection.execute(
                    text(
                        "INSERT INTO administrative_obligation "
                        "(obligation_id, requirement_id, case_id, authority_epoch, "
                        "governance_basis_id, kind, subject_ref, target_system, "
                        "required_operation, expected_postcondition_json, authority_class, "
                        "required, fulfillment_kind) "
                        "VALUES (:obligation_id, :requirement_id, :case_id, 1, :basis_id, "
                        ":kind, 'subject:test', 'erp', :operation, '{}', 'financial', 1, "
                        "'external_effect_verified')"
                    ),
                    {
                        "obligation_id": obligation_id,
                        "requirement_id": requirement_id,
                        "case_id": case_id,
                        "basis_id": basis_id,
                        "kind": f"erp.{operation}",
                        "operation": operation,
                    },
                )

        command.upgrade(config, "0032_obligation_sequence")
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT required_operation, sequence FROM administrative_obligation "
                    "WHERE requirement_id = :requirement_id ORDER BY sequence"
                ),
                {"requirement_id": requirement_id},
            ).all()

        assert rows == [
            ("purchase_order.create_draft", 0),
            ("purchase_order.confirm", 1),
        ]
    finally:
        get_settings.cache_clear()
