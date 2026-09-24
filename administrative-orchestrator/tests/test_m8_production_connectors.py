from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from administrative_orchestrator.integrations.credentials import CredentialRef
from administrative_orchestrator.integrations.production_effects import (
    ConnectorStatus,
    OdooEffectConnection,
    OdooFinancialEffectConnector,
    OdooFinancialVerifier,
)
from scripts.production_world_runtime_stack import ProductionEffectProvider


def _connector(
    *, payload_field: str = "x_administrative_m8_payload_json"
) -> OdooFinancialEffectConnector:
    return OdooFinancialEffectConnector(
        OdooEffectConnection(
            base_url="https://odoo.example.test",
            database="m8",
            username="erp-writer",
            credential=CredentialRef("odoo:erp-writer", "M8_ODOO_SECRET"),
            transaction_payload_field=payload_field,
        )
    )


@pytest.mark.asyncio
async def test_production_provider_uses_runtime_subject_before_business_employee_ref() -> None:
    calls: list[dict[str, object]] = []

    class Connector:
        async def invoke(self, **kwargs):
            calls.append(kwargs)
            return type("Result", (), {
                "status": ConnectorStatus.SUCCEEDED,
                "external_operation_ref": None,
                "reconciled": False,
                "error_code": None,
                "error_message": None,
            })()

        async def reconcile(self, **kwargs):
            del kwargs
            return None

    provider = ProductionEffectProvider(
        provider_id="provider:test",
        name="test",
        capability="administrative.erp.expense-report.create.v1",
        family="test",
        execution_domain="test",
        credential_configuration_ref="test",
        network_domain="test",
        connector=Connector(),
        operation="expense_report.create",
    )

    await provider.invoke(
        SimpleNamespace(
            id="request:test",
            parameters={
                "employee_ref": "odoo:hr.employee:1",
                "subject_ref": "m8:expense-recovery:8201",
            },
        ),
        None,
    )

    assert calls[0]["subject_ref"] == "m8:expense-recovery:8201"


@pytest.mark.asyncio
async def test_m8_purchase_order_writer_is_idempotent_and_draft_bounded(monkeypatch) -> None:
    connector = _connector()
    execute = AsyncMock(side_effect=[[], [], 42])
    monkeypatch.setattr(connector.transport, "_execute_kw", execute)

    result = await connector.invoke(
        request_ref="case:1:effect:1",
        subject_ref="transaction:1",
        operation="purchase_order.create_draft",
        parameters={
            "vendor_ref": "odoo:res.partner:7",
            "description": "laptops",
            "needed_by": "2026-10-01",
        },
    )

    assert result.status is ConnectorStatus.SUCCEEDED
    assert result.external_operation_ref == "odoo:purchase.order:42"
    create_call = execute.await_args_list[-1]
    assert create_call.args[0:2] == ("purchase.order", "create")
    values = create_call.args[2][0]
    assert values["partner_id"] == 7
    assert values["x_administrative_transaction_subject_ref"] == "transaction:1"


@pytest.mark.asyncio
async def test_m8_purchase_order_confirm_uses_readback_safe_marker(monkeypatch) -> None:
    connector = _connector()
    execute = AsyncMock(
        side_effect=[
            [],
            [{"id": 42, "state": "draft", "x_administrative_transaction_confirm_request_ref": ""}],
            True,
            True,
        ]
    )
    monkeypatch.setattr(connector.transport, "_execute_kw", execute)

    result = await connector.invoke(
        request_ref="case:1:effect:2",
        subject_ref="transaction:1",
        operation="purchase_order.confirm",
        parameters={"purchase_order_ref": "odoo:purchase.order:42"},
    )

    assert result.status is ConnectorStatus.SUCCEEDED
    assert result.external_operation_ref == "odoo:purchase.order:42"
    assert execute.await_args_list[-1].args[1] == "button_confirm"


@pytest.mark.asyncio
async def test_m8_vendor_bill_writer_rejects_existing_erp_invoice_identity(monkeypatch) -> None:
    connector = _connector()
    execute = AsyncMock(
        side_effect=[
            [],
            [],
            [{"id": 7, "ref": "INV-1", "partner_id": [11, "M8 Acme Office Supplies"]}],
        ]
    )
    monkeypatch.setattr(connector.transport, "_execute_kw", execute)

    result = await connector.invoke(
        request_ref="case:duplicate:effect:1",
        subject_ref="transaction:duplicate",
        operation="vendor_bill.create_draft",
        parameters={
            "vendor_ref": "odoo:res.partner:11",
            "invoice_number": "INV-1",
            "invoice_date": "2026-09-12",
        },
    )

    assert result.status is ConnectorStatus.FAILED
    assert result.error_code == "DuplicateExternalInvoiceIdentity"
    assert all(call.args[1] != "create" for call in execute.await_args_list)


@pytest.mark.asyncio
async def test_m8_expense_writer_does_not_reuse_employee_subject_as_transaction_identity(
    monkeypatch,
) -> None:
    connector = _connector()
    execute = AsyncMock(side_effect=[[], 43])
    monkeypatch.setattr(connector.transport, "_execute_kw", execute)

    result = await connector.invoke(
        request_ref="case:expense:effect:1",
        subject_ref="odoo:hr.employee:2",
        operation="expense_report.create",
        parameters={
            "employee_ref": "odoo:hr.employee:2",
            "merchant": "M8 Acme Office Supplies",
            "expense_date": "2026-09-12",
            "amount": {"amount": "42.00", "currency": "USD"},
            "category": "office-supplies",
            "business_purpose": "M8 staging office supplies",
            "receipt_ref": "receipt:1",
        },
    )

    assert result.status is ConnectorStatus.SUCCEEDED
    assert result.external_operation_ref == "odoo:hr.expense:43"
    assert [call.args[1] for call in execute.await_args_list] == ["search_read", "create"]


@pytest.mark.asyncio
async def test_m8_expense_verifier_selects_exact_payload_among_employee_subject_rows(
    monkeypatch,
) -> None:
    connector = _connector()
    expected_payload = {
        "employee_ref": "odoo:hr.employee:2",
        "merchant": "M8 Acme Office Supplies",
        "expense_date": "2026-09-12",
        "amount": {"amount": "42.00", "currency": "USD"},
        "category": "office-supplies",
        "business_purpose": "M8 staging office supplies",
        "receipt_ref": "receipt:current",
    }
    monkeypatch.setattr(
        connector.transport,
        "_execute_kw",
        AsyncMock(
            return_value=[
                {
                    "id": 1,
                    "state": "draft",
                    "x_administrative_m8_payload_json": False,
                },
                {
                    "id": 43,
                    "state": "draft",
                    "x_administrative_m8_payload_json": json.dumps(expected_payload),
                },
            ]
        ),
    )
    expected = {
        "target_system": "erp",
        "operation": "expense_report.create",
        "subject_ref": "odoo:hr.employee:2",
        "transaction_case_ref": "case:expense",
        "payload": expected_payload,
        "settlement": "forbidden",
    }

    result = await OdooFinancialVerifier(
        connector,
        operation="expense_report.create",
    ).observe(subject_ref="odoo:hr.employee:2", expected_postcondition=expected)

    assert result.status is ConnectorStatus.SUCCEEDED
    assert result.observed_postcondition == expected


@pytest.mark.asyncio
async def test_m8_verifier_reports_draft_without_settlement(monkeypatch) -> None:
    connector = _connector()
    monkeypatch.setattr(
        connector.transport,
        "_execute_kw",
        AsyncMock(
            return_value=[
                {
                    "id": 42,
                    "state": "draft",
                    "x_administrative_m8_payload_json": json.dumps(
                        {"invoice_number": "INV-1"}
                    ),
                }
            ]
        ),
    )
    expected = {
        "target_system": "erp",
        "operation": "vendor_bill.create_draft",
        "subject_ref": "transaction:1",
        "transaction_case_ref": "case:1",
        "payload": {"invoice_number": "INV-1"},
        "settlement": "forbidden",
    }
    result = await OdooFinancialVerifier(
        connector,
        operation="vendor_bill.create_draft",
    ).observe(subject_ref="transaction:1", expected_postcondition=expected)

    assert result.status is ConnectorStatus.SUCCEEDED
    assert result.observed_postcondition == expected


@pytest.mark.asyncio
async def test_m8_purchase_order_confirm_verifier_requires_confirmed_state(monkeypatch) -> None:
    connector = _connector()
    monkeypatch.setattr(
        connector.transport,
        "_execute_kw",
        AsyncMock(
            return_value=[
                {
                    "id": 42,
                    "state": "purchase",
                    "x_administrative_m8_payload_json": json.dumps(
                        {"quote_ref": "m8-quote-1"}
                    ),
                }
            ]
        ),
    )
    expected = {
        "target_system": "erp",
        "operation": "purchase_order.confirm",
        "subject_ref": "transaction:1",
        "transaction_case_ref": "case:1",
        "payload": {"quote_ref": "m8-quote-1"},
        "settlement": "forbidden",
    }

    result = await OdooFinancialVerifier(
        connector,
        operation="purchase_order.confirm",
    ).observe(subject_ref="transaction:1", expected_postcondition=expected)

    assert result.status is ConnectorStatus.SUCCEEDED
    assert result.observed_postcondition == expected


@pytest.mark.asyncio
async def test_m8_purchase_order_confirm_verifier_exposes_unconfirmed_state(monkeypatch) -> None:
    connector = _connector()
    monkeypatch.setattr(
        connector.transport,
        "_execute_kw",
        AsyncMock(
            return_value=[
                {
                    "id": 42,
                    "state": "draft",
                    "x_administrative_m8_payload_json": json.dumps(
                        {"quote_ref": "m8-quote-1"}
                    ),
                }
            ]
        ),
    )
    expected = {
        "target_system": "erp",
        "operation": "purchase_order.confirm",
        "subject_ref": "transaction:1",
        "transaction_case_ref": "case:1",
        "payload": {"quote_ref": "m8-quote-1"},
        "settlement": "forbidden",
    }

    result = await OdooFinancialVerifier(
        connector,
        operation="purchase_order.confirm",
    ).observe(subject_ref="transaction:1", expected_postcondition=expected)

    assert result.status is ConnectorStatus.SUCCEEDED
    assert result.observed_postcondition == {**expected, "state": "draft"}


def test_m8_expense_writer_supplies_required_single_receipt_quantity() -> None:
    connector = _connector()

    values = connector._create_values(
        "expense_report.create",
        request_ref="case:expense:1",
        subject_ref="odoo:hr.employee:4",
        parameters={
            "employee_ref": "odoo:hr.employee:4",
            "subject_ref": "odoo:hr.employee:4",
            "business_purpose": "M8 staging expense",
            "expense_date": "2026-09-12",
            "amount": {"amount": "42.00", "currency": "USD"},
        },
    )

    assert values["quantity"] == 1
    assert values["total_amount"] == "42.00"
    assert json.loads(values["x_administrative_m8_payload_json"]) == {
        "employee_ref": "odoo:hr.employee:4",
        "business_purpose": "M8 staging expense",
        "expense_date": "2026-09-12",
        "amount": {"amount": "42.00", "currency": "USD"},
    }


def test_financial_connector_uses_the_configured_payload_field() -> None:
    connector = _connector(payload_field="x_administrative_m9_payload_json")

    values = connector._create_values(
        "vendor_bill.create_draft",
        request_ref="case:vendor-bill:1",
        subject_ref="transaction:1",
        parameters={
            "vendor_ref": "odoo:res.partner:11",
            "invoice_number": "INV-1",
            "invoice_date": "2026-09-12",
        },
    )

    assert "x_administrative_m8_payload_json" not in values
    assert (
        json.loads(values["x_administrative_m9_payload_json"])["invoice_number"]
        == "INV-1"
    )
