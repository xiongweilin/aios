from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx

from .credentials import CredentialRef, CredentialResolver, EnvironmentCredentialResolver
from .effect_common import (
    ConnectorConfigurationError,
    ConnectorResult,
    ConnectorStatus,
    _ApplicationRejected,
    _TransportUnknown,
    _unavailable_result,
    _unknown_result,
    _validate_base_url,
)


@dataclass(frozen=True, slots=True)
class OdooEffectConnection:
    base_url: str
    database: str
    username: str
    credential: CredentialRef
    request_ref_field: str = "x_administrative_request_ref"
    deactivate_request_ref_field: str = "x_administrative_deactivate_request_ref"
    subject_ref_field: str = "x_administrative_subject_ref"
    transaction_request_ref_field: str = "x_administrative_transaction_request_ref"
    transaction_confirm_request_ref_field: str = (
        "x_administrative_transaction_confirm_request_ref"
    )
    transaction_subject_ref_field: str = "x_administrative_transaction_subject_ref"
    transaction_payload_field: str = "x_administrative_m8_payload_json"
    timeout_seconds: float = 10.0
    allow_insecure_http: bool = False

    def __post_init__(self) -> None:
        _validate_base_url(self.base_url, allow_insecure_http=self.allow_insecure_http)
        if not self.database.strip() or not self.username.strip():
            raise ConnectorConfigurationError("Odoo database and username are required")
        for field in (
            self.request_ref_field,
            self.deactivate_request_ref_field,
            self.subject_ref_field,
            self.transaction_request_ref_field,
            self.transaction_confirm_request_ref_field,
            self.transaction_subject_ref_field,
            self.transaction_payload_field,
        ):
            if not field.startswith("x_"):
                raise ConnectorConfigurationError(
                    "Odoo integration identity fields must be custom x_ fields"
                )


class OdooEmployeeEffectConnector:
    """Kernel-facing Odoo employee writer/reconciler.

    Production Odoo must expose durable custom request/subject identity fields.
    A transport failure after create is UNKNOWN, never retry permission; Kernel
    recovery calls `reconcile(request_ref)` instead of re-invoking create.
    """

    def __init__(
        self,
        connection: OdooEffectConnection,
        *,
        credentials: CredentialResolver | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.connection = connection
        self.credentials = credentials or EnvironmentCredentialResolver()
        self._client = client

    async def invoke(
        self,
        *,
        request_ref: str,
        subject_ref: str,
        parameters: dict[str, Any],
    ) -> ConnectorResult:
        try:
            existing = await self._lookup(self.connection.request_ref_field, request_ref)
            if len(existing) > 1:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="DuplicateExternalRequestIdentity",
                    error_message="multiple Odoo employees share the same request_ref",
                )
            if existing:
                return ConnectorResult(
                    ConnectorStatus.SUCCEEDED,
                    external_operation_ref=f"odoo:hr.employee:{existing[0]['id']}",
                    reconciled=True,
                )

            by_subject = await self._lookup(self.connection.subject_ref_field, subject_ref)
            if len(by_subject) > 1:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="DuplicateExternalSubjectIdentity",
                    error_message="multiple Odoo employees share the same subject_ref",
                )
            if by_subject:
                return ConnectorResult(
                    ConnectorStatus.SUCCEEDED,
                    external_operation_ref=f"odoo:hr.employee:{by_subject[0]['id']}",
                    reconciled=True,
                )

            values: dict[str, Any] = {
                self.connection.request_ref_field: request_ref,
                self.connection.subject_ref_field: subject_ref,
                "name": str(parameters.get("name") or parameters.get("employee_ref") or subject_ref),
                "active": True,
            }
            if parameters.get("work_email"):
                values["work_email"] = parameters["work_email"]
            department_id = _odoo_numeric_ref(parameters.get("department_ref"), "hr.department")
            if department_id is not None:
                values["department_id"] = department_id
            manager_id = _odoo_numeric_ref(parameters.get("manager_ref"), "hr.employee")
            if manager_id is not None:
                values["parent_id"] = manager_id
            for source_key, target_field in {
                "manager_principal_id": "x_administrative_manager_principal_id",
                "employment_type": "x_administrative_employment_type",
                "start_date": "x_administrative_start_date",
            }.items():
                if parameters.get(source_key) is not None:
                    values[target_field] = parameters[source_key]

            employee_id = await self._execute_kw("hr.employee", "create", [values], {})
            if not isinstance(employee_id, int) or employee_id <= 0:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="InvalidOdooCreateResult",
                    error_message="Odoo did not return a valid employee id",
                )
            return ConnectorResult(
                ConnectorStatus.SUCCEEDED,
                external_operation_ref=f"odoo:hr.employee:{employee_id}",
            )
        except _TransportUnknown as exc:
            return ConnectorResult(
                ConnectorStatus.UNKNOWN,
                error_code=type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
                error_message=str(exc),
            )
        except _ApplicationRejected as exc:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="OdooApplicationRejected",
                error_message=str(exc),
            )

    async def reconcile(self, request_ref: str) -> ConnectorResult | None:
        try:
            rows = await self._lookup(self.connection.request_ref_field, request_ref)
        except _TransportUnknown as exc:
            return ConnectorResult(
                ConnectorStatus.UNKNOWN,
                error_code=type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
                error_message=str(exc),
                reconciled=True,
            )
        except _ApplicationRejected as exc:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="OdooApplicationRejected",
                error_message=str(exc),
                reconciled=True,
            )
        if not rows:
            return None
        if len(rows) != 1:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="DuplicateExternalRequestIdentity",
                error_message="reconciliation found multiple Odoo employee operations",
                reconciled=True,
            )
        return ConnectorResult(
            ConnectorStatus.SUCCEEDED,
            external_operation_ref=f"odoo:hr.employee:{rows[0]['id']}",
            reconciled=True,
        )

    async def _lookup(self, field: str, value: str) -> list[dict[str, Any]]:
        rows = await self._execute_kw(
            "hr.employee",
            "search_read",
            [[(field, "=", value)]],
            {"fields": ["id", field], "limit": 2},
        )
        return rows if isinstance(rows, list) else []

    async def _execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any],
    ) -> Any:
        secret = self.credentials.resolve(self.connection.credential)
        uid = await self._rpc(
            "common",
            "authenticate",
            [self.connection.database, self.connection.username, secret, {}],
        )
        if not isinstance(uid, int) or uid <= 0:
            raise _ApplicationRejected("Odoo connector authentication rejected")
        return await self._rpc(
            "object",
            "execute_kw",
            [self.connection.database, uid, secret, model, method, args, kwargs],
        )

    async def _rpc(self, service: str, method: str, args: list[Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": str(uuid4()),
        }
        url = f"{self.connection.base_url.rstrip('/')}/jsonrpc"
        try:
            if self._client is not None:
                response = await self._client.post(url, json=payload)
            else:
                async with httpx.AsyncClient(timeout=self.connection.timeout_seconds) as client:
                    response = await client.post(url, json=payload)
            response.raise_for_status()
            raw = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise _TransportUnknown("Odoo transport/result is ambiguous") from exc
        if not isinstance(raw, dict):
            raise _ApplicationRejected("Odoo returned a non-object JSON-RPC response")
        if raw.get("error") is not None:
            raise _ApplicationRejected("Odoo JSON-RPC rejected the operation")
        return raw.get("result")


class OdooEmployeeVerifier:
    """Independent Odoo readback under a separate credential identity."""

    def __init__(self, connector: OdooEmployeeEffectConnector) -> None:
        self.connector = connector

    async def observe(
        self,
        *,
        subject_ref: str,
        expected_postcondition: dict[str, Any],
    ) -> ConnectorResult:
        try:
            rows = await self.connector._lookup(self.connector.connection.subject_ref_field, subject_ref)
            if len(rows) != 1:
                observed: dict[str, Any] = {}
            else:
                employee_id = rows[0]["id"]
                full = await self.connector._execute_kw(
                    "hr.employee",
                    "read",
                    [[employee_id]],
                    {
                        "fields": [
                            "id",
                            "department_id",
                            "parent_id",
                            "work_email",
                            "active",
                            "x_administrative_manager_principal_id",
                            "x_administrative_employment_type",
                            "x_administrative_start_date",
                            self.connector.connection.subject_ref_field,
                        ]
                    },
                )
                row = full[0] if isinstance(full, list) and full else {}
                expected_payload = expected_postcondition.get("payload")
                expected_payload = expected_payload if isinstance(expected_payload, dict) else {}
                payload: dict[str, Any] = {}
                for key in expected_payload:
                    if key == "employee_ref":
                        payload[key] = subject_ref
                    elif key == "department_ref":
                        dep = _many2one_id(row.get("department_id"))
                        payload[key] = f"odoo:hr.department:{dep}" if dep is not None else None
                    elif key == "manager_principal_id":
                        payload[key] = row.get("x_administrative_manager_principal_id") or None
                    elif key == "employment_type":
                        payload[key] = row.get("x_administrative_employment_type") or None
                    elif key == "start_date":
                        payload[key] = row.get("x_administrative_start_date") or None
                    else:
                        payload[key] = expected_payload[key]
                observed = {
                    "target_system": "hris",
                    "operation": "employee.create",
                    "subject_ref": subject_ref,
                    "active": bool(row.get("active", False)),
                    "payload": payload,
                }
            return ConnectorResult(
                ConnectorStatus.SUCCEEDED,
                observed_postcondition=observed,
            )
        except _TransportUnknown as exc:
            return ConnectorResult(
                ConnectorStatus.UNAVAILABLE,
                error_code=type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
                error_message=str(exc),
            )
        except _ApplicationRejected as exc:
            return ConnectorResult(
                ConnectorStatus.UNAVAILABLE,
                error_code="OdooVerificationRejected",
                error_message=str(exc),
            )


class OdooFinancialEffectConnector:
    """Bounded Odoo writer for M8 draft transaction effects.

    The connector deliberately exposes only draft purchase orders, draft vendor
    bills and draft expense records. It never calls payment, bank, settlement,
    or reconciliation endpoints.
    """

    _MODELS = {
        "purchase_order.create_draft": "purchase.order",
        "vendor_bill.create_draft": "account.move",
        "expense_report.create": "hr.expense",
    }

    def __init__(
        self,
        connection: OdooEffectConnection,
        *,
        credentials: CredentialResolver | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.connection = connection
        self._payload_field = connection.transaction_payload_field
        self.transport = OdooEmployeeEffectConnector(
            connection,
            credentials=credentials,
            client=client,
        )

    async def invoke(
        self,
        *,
        request_ref: str,
        subject_ref: str,
        parameters: dict[str, Any],
        operation: str,
    ) -> ConnectorResult:
        model = self._MODELS.get(operation)
        if model is None:
            if operation == "purchase_order.confirm":
                return await self._confirm_purchase_order(
                    request_ref=request_ref,
                    subject_ref=subject_ref,
                    parameters=parameters,
                )
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="UnsupportedFinancialOperation",
                error_message="the Odoo financial connector does not support this operation",
            )

        request_field = self.connection.transaction_request_ref_field
        subject_field = self.connection.transaction_subject_ref_field
        try:
            existing = await self._search(
                model,
                request_field,
                request_ref,
                fields=["id", request_field],
            )
            if len(existing) > 1:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="DuplicateExternalRequestIdentity",
                    error_message="multiple Odoo transaction records share the request identity",
                )
            if existing:
                return self._success(model, int(existing[0]["id"]), reconciled=True)

            if operation != "expense_report.create":
                by_subject = await self._search(
                    model,
                    subject_field,
                    subject_ref,
                    fields=["id", request_field],
                )
                if len(by_subject) > 1:
                    return ConnectorResult(
                        ConnectorStatus.FAILED,
                        error_code="DuplicateExternalSubjectIdentity",
                        error_message="multiple Odoo transaction records share the subject identity",
                    )
                if by_subject:
                    return self._success(model, int(by_subject[0]["id"]), reconciled=True)

            if operation == "vendor_bill.create_draft":
                duplicates = await self.find_existing_vendor_bills(
                    vendor_ref=str(parameters.get("vendor_ref") or ""),
                    invoice_number=str(parameters.get("invoice_number") or ""),
                )
                if duplicates:
                    return ConnectorResult(
                        ConnectorStatus.FAILED,
                        error_code="DuplicateExternalInvoiceIdentity",
                        error_message="the vendor and invoice identity already exists in Odoo",
                    )

            values = self._create_values(
                operation,
                request_ref=request_ref,
                subject_ref=subject_ref,
                parameters=parameters,
            )
            external_id = await self.transport._execute_kw(model, "create", [values], {})
            if not isinstance(external_id, int) or external_id <= 0:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="InvalidOdooCreateResult",
                    error_message="Odoo did not return a valid transaction id",
                )
            return self._success(model, external_id)
        except _TransportUnknown as exc:
            return _unknown_result(exc)
        except _ApplicationRejected as exc:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="OdooApplicationRejected",
                error_message=str(exc),
            )

    async def reconcile(
        self,
        request_ref: str,
        *,
        operation: str,
    ) -> ConnectorResult | None:
        model = self._MODELS.get(operation)
        if model is None:
            return None
        identity_field = (
            self.connection.transaction_confirm_request_ref_field
            if operation == "purchase_order.confirm"
            else self.connection.transaction_request_ref_field
        )
        try:
            rows = await self._search(
                model,
                identity_field,
                request_ref,
                fields=["id", identity_field],
            )
            if not rows:
                return None
            if len(rows) != 1:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="DuplicateExternalRequestIdentity",
                    error_message="reconciliation found multiple Odoo transaction records",
                    reconciled=True,
                )
            return self._success(model, int(rows[0]["id"]), reconciled=True)
        except _TransportUnknown as exc:
            return _unknown_result(exc, reconciled=True)
        except _ApplicationRejected as exc:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="OdooApplicationRejected",
                error_message=str(exc),
                reconciled=True,
            )

    async def find_existing_vendor_bills(
        self,
        *,
        vendor_ref: str,
        invoice_number: str,
    ) -> list[dict[str, Any]]:
        vendor_id = _odoo_numeric_ref(vendor_ref, "res.partner")
        if vendor_id is None or not invoice_number.strip():
            return []
        rows = await self.transport._execute_kw(
            "account.move",
            "search_read",
            [
                [
                    ("move_type", "=", "in_invoice"),
                    ("partner_id", "=", vendor_id),
                    ("ref", "=", invoice_number),
                ]
            ],
            {
                "fields": [
                    "id",
                    "ref",
                    "partner_id",
                    self.connection.transaction_request_ref_field,
                    self.connection.transaction_subject_ref_field,
                ],
                "limit": 2,
            },
        )
        return rows if isinstance(rows, list) else []

    async def _confirm_purchase_order(
        self,
        *,
        request_ref: str,
        subject_ref: str,
        parameters: dict[str, Any],
    ) -> ConnectorResult:
        del subject_ref
        model = "purchase.order"
        confirm_field = self.connection.transaction_confirm_request_ref_field
        try:
            existing = await self._search(model, confirm_field, request_ref, fields=["id"])
            if len(existing) > 1:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="DuplicateExternalRequestIdentity",
                    error_message="multiple purchase orders share the confirm identity",
                )
            order_id: int | None = int(existing[0]["id"]) if existing else None
            if order_id is None:
                raw_ref = parameters.get("purchase_order_ref") or parameters.get("draft_ref")
                order_id = _odoo_numeric_ref(raw_ref, "purchase.order")
            if order_id is None:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="MissingPurchaseOrderReference",
                    error_message="purchase order confirmation requires an exact draft reference",
                )
            rows = await self.transport._execute_kw(
                model,
                "read",
                [[order_id]],
                {"fields": ["id", "state", confirm_field]},
            )
            row = rows[0] if isinstance(rows, list) and len(rows) == 1 else None
            if not isinstance(row, dict):
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="PurchaseOrderNotFound",
                    error_message="the exact purchase order draft was not found",
                )
            if row.get("state") in {"purchase", "done"}:
                return self._success(model, order_id, reconciled=True)
            written = await self.transport._execute_kw(
                model,
                "write",
                [[order_id], {confirm_field: request_ref}],
                {},
            )
            if written is not True:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="PurchaseOrderConfirmMarkerRejected",
                    error_message="Odoo did not accept the purchase order confirmation marker",
                )
            result = await self.transport._execute_kw(model, "button_confirm", [[order_id]], {})
            if result is not True:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="PurchaseOrderConfirmRejected",
                    error_message="Odoo did not confirm the purchase order",
                )
            return self._success(model, order_id)
        except _TransportUnknown as exc:
            return _unknown_result(exc)
        except _ApplicationRejected as exc:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="OdooApplicationRejected",
                error_message=str(exc),
            )

    async def _search(
        self,
        model: str,
        field: str,
        value: str,
        *,
        fields: list[str],
    ) -> list[dict[str, Any]]:
        rows = await self.transport._execute_kw(
            model,
            "search_read",
            [[(field, "=", value)]],
            {"fields": fields, "limit": 2},
        )
        return rows if isinstance(rows, list) else []

    def _create_values(
        self,
        operation: str,
        *,
        request_ref: str,
        subject_ref: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        payload_parameters = dict(parameters)
        payload_parameters.pop("subject_ref", None)
        values: dict[str, Any] = {
            self.connection.transaction_request_ref_field: request_ref,
            self.connection.transaction_subject_ref_field: subject_ref,
            self._payload_field: json.dumps(
                payload_parameters,
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
        if operation == "purchase_order.create_draft":
            values.update(
                {
                    "partner_id": _required_odoo_numeric_ref(
                        parameters.get("vendor_ref") or parameters.get("candidate_vendor"),
                        "res.partner",
                    ),
                    "date_order": parameters.get("needed_by"),
                    "origin": str(parameters.get("quote_ref") or request_ref),
                }
            )
        elif operation == "vendor_bill.create_draft":
            values.update(
                {
                    "move_type": "in_invoice",
                    "partner_id": _required_odoo_numeric_ref(
                        parameters.get("vendor_ref") or parameters.get("vendor_tax_id"),
                        "res.partner",
                    ),
                    "ref": parameters.get("invoice_number") or request_ref,
                    "invoice_date": parameters.get("invoice_date"),
                }
            )
        elif operation == "expense_report.create":
            amount = (
                (parameters.get("amount") or {}).get("amount", "0")
                if isinstance(parameters.get("amount"), dict)
                else parameters.get("amount", "0")
            )
            values.update(
                {
                    "name": str(parameters.get("business_purpose") or subject_ref),
                    "employee_id": _required_odoo_numeric_ref(
                        parameters.get("employee_ref"), "hr.employee"
                    ),
                    "date": parameters.get("expense_date"),
                    "quantity": 1,
                    "total_amount": str(amount),
                }
            )
        else:
            raise _ApplicationRejected("unsupported Odoo financial create operation")
        return values

    @staticmethod
    def _success(model: str, external_id: int, *, reconciled: bool = False) -> ConnectorResult:
        return ConnectorResult(
            ConnectorStatus.SUCCEEDED,
            external_operation_ref=f"odoo:{model}:{external_id}",
            reconciled=reconciled,
        )


class OdooFinancialVerifier:
    def __init__(self, connector: OdooFinancialEffectConnector, *, operation: str) -> None:
        self.connector = connector
        self.operation = operation

    async def observe(
        self,
        *,
        subject_ref: str,
        expected_postcondition: dict[str, Any],
    ) -> ConnectorResult:
        model = self.connector._MODELS.get(self.operation)
        if self.operation == "purchase_order.confirm":
            model = "purchase.order"
        if model is None:
            return ConnectorResult(
                ConnectorStatus.UNAVAILABLE,
                error_code="UnsupportedFinancialOperation",
                error_message="financial readback operation is not configured",
            )
        field = self.connector.connection.transaction_subject_ref_field
        try:
            rows = await self.connector._search(
                model,
                field,
                subject_ref,
                fields=["id", "state", field, self.connector._payload_field],
            )
            if self.operation == "expense_report.create":
                expected_payload = expected_postcondition.get("payload")
                if not isinstance(expected_payload, dict):
                    rows = []
                else:
                    rows = [
                        row
                        for row in rows
                        if self._payload_from_row(row) == expected_payload
                    ]
            if len(rows) != 1:
                return ConnectorResult(
                    ConnectorStatus.SUCCEEDED,
                    observed_postcondition={},
                )
            row = rows[0]
            state = str(row.get("state") or "draft")
            settlement = "forbidden" if state in {"draft", "purchase", "posted"} else state
            observed = dict(expected_postcondition)
            observed["subject_ref"] = subject_ref
            observed["settlement"] = settlement
            actual_payload = self._payload_from_row(row)
            if not isinstance(actual_payload, dict):
                observed["payload"] = {}
            elif actual_payload != expected_postcondition.get("payload"):
                observed["payload"] = actual_payload
            if self.operation == "purchase_order.confirm" and state not in {"purchase", "done"}:
                observed["state"] = state
            elif self.operation != "purchase_order.confirm" and state != "draft":
                observed["state"] = state
            return ConnectorResult(
                ConnectorStatus.SUCCEEDED,
                external_operation_ref=f"odoo:{model}:{row['id']}",
                observed_postcondition=observed,
            )
        except _TransportUnknown as exc:
            return _unavailable_result(exc)
        except _ApplicationRejected as exc:
            return ConnectorResult(
                ConnectorStatus.UNAVAILABLE,
                error_code="OdooVerificationRejected",
                error_message=str(exc),
            )

    def _payload_from_row(self, row: dict[str, Any]) -> dict[str, Any] | None:
        raw_payload = row.get(self.connector._payload_field)
        try:
            actual_payload = json.loads(raw_payload) if raw_payload else None
        except (TypeError, ValueError):
            actual_payload = None
        return actual_payload if isinstance(actual_payload, dict) else None


class OdooEmployeeDeactivateConnector:
    """Deactivate one exact Odoo employee with durable request identity."""

    def __init__(self, connector: OdooEmployeeEffectConnector) -> None:
        self.connector = connector

    async def invoke(
        self,
        *,
        request_ref: str,
        subject_ref: str,
        parameters: dict[str, Any],
    ) -> ConnectorResult:
        employee_ref = str(parameters.get("employee_external_ref") or subject_ref)
        employee_id = _odoo_numeric_ref(employee_ref, "hr.employee")
        if employee_id is None:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="InvalidOdooEmployeeReference",
                error_message="employee deactivation requires odoo:hr.employee:<id>",
            )
        try:
            row = await self._read(employee_id)
            if not row:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="OdooEmployeeNotFound",
                    error_message="the exact Odoo employee does not exist",
                )
            request_field = self.connector.connection.deactivate_request_ref_field
            recorded = str(row.get(request_field) or "").strip()
            if recorded and recorded != request_ref:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="ConflictingExternalRequestIdentity",
                    error_message="Odoo employee records a different deactivate request",
                )
            if recorded == request_ref and not bool(row.get("active", True)):
                return self._success(employee_id, reconciled=True)
            written = await self.connector._execute_kw(
                "hr.employee",
                "write",
                [[employee_id], {"active": False, request_field: request_ref}],
                {},
            )
            if written is not True:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="OdooDeactivateRejected",
                    error_message="Odoo did not confirm the employee update",
                )
            return self._success(employee_id)
        except _TransportUnknown as exc:
            return _unknown_result(exc)
        except _ApplicationRejected as exc:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="OdooApplicationRejected",
                error_message=str(exc),
            )

    async def reconcile(self, request_ref: str) -> ConnectorResult | None:
        try:
            rows = await self.connector._lookup(
                self.connector.connection.deactivate_request_ref_field, request_ref
            )
            if not rows:
                return None
            if len(rows) != 1:
                return ConnectorResult(
                    ConnectorStatus.FAILED,
                    error_code="DuplicateExternalRequestIdentity",
                    error_message="multiple Odoo employees share the deactivate request_ref",
                    reconciled=True,
                )
            employee_id = int(rows[0]["id"])
            row = await self._read(employee_id)
            if row and not bool(row.get("active", True)):
                return self._success(employee_id, reconciled=True)
            return ConnectorResult(
                ConnectorStatus.UNKNOWN,
                external_operation_ref=f"odoo:hr.employee:{employee_id}",
                error_code="OdooDeactivateNotObserved",
                error_message="request identity exists but inactive state is not observed",
                reconciled=True,
            )
        except _TransportUnknown as exc:
            return _unknown_result(exc, reconciled=True)
        except _ApplicationRejected as exc:
            return ConnectorResult(
                ConnectorStatus.FAILED,
                error_code="OdooApplicationRejected",
                error_message=str(exc),
                reconciled=True,
            )

    async def _read(self, employee_id: int) -> dict[str, Any]:
        rows = await self.connector._execute_kw(
            "hr.employee",
            "read",
            [[employee_id]],
            {
                "fields": [
                    "id",
                    "active",
                    self.connector.connection.deactivate_request_ref_field,
                ]
            },
        )
        return rows[0] if isinstance(rows, list) and len(rows) == 1 else {}

    @staticmethod
    def _success(employee_id: int, *, reconciled: bool = False) -> ConnectorResult:
        return ConnectorResult(
            ConnectorStatus.SUCCEEDED,
            external_operation_ref=f"odoo:hr.employee:{employee_id}",
            reconciled=reconciled,
        )


class OdooEmployeeDeactivateVerifier:
    def __init__(self, connector: OdooEmployeeDeactivateConnector) -> None:
        self.connector = connector

    async def observe(
        self,
        *,
        subject_ref: str,
        expected_postcondition: dict[str, Any],
    ) -> ConnectorResult:
        employee_ref = str(
            expected_postcondition.get("employee_external_ref") or subject_ref
        )
        employee_id = _odoo_numeric_ref(employee_ref, "hr.employee")
        if employee_id is None:
            return ConnectorResult(ConnectorStatus.SUCCEEDED, observed_postcondition={})
        try:
            row = await self.connector._read(employee_id)
            observed = (
                {
                    "target_system": "hris",
                    "operation": "employee.deactivate",
                    "subject_ref": subject_ref,
                    "active": bool(row.get("active", True)),
                }
                if row
                else {}
            )
            return ConnectorResult(
                ConnectorStatus.SUCCEEDED, observed_postcondition=observed
            )
        except (_TransportUnknown, _ApplicationRejected) as exc:
            return _unavailable_result(exc)


def _required_odoo_numeric_ref(value: Any, model: str) -> int:
    numeric = _odoo_numeric_ref(value, model)
    if numeric is None:
        raise _ApplicationRejected(f"an exact {model} reference is required")
    return numeric


def _odoo_numeric_ref(value: Any, model: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    prefix = f"odoo:{model}:"
    if value.startswith(prefix) and value[len(prefix) :].isdigit():
        return int(value[len(prefix) :])
    if value.isdigit():
        return int(value)
    return None


def _many2one_id(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value and isinstance(value[0], int):
        return value[0]
    if isinstance(value, int):
        return value
    return None


__all__ = [
    "OdooEffectConnection",
    "OdooEmployeeDeactivateConnector",
    "OdooEmployeeDeactivateVerifier",
    "OdooEmployeeEffectConnector",
    "OdooEmployeeVerifier",
    "OdooFinancialEffectConnector",
    "OdooFinancialVerifier",
]
