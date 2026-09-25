from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from ..domain import utcnow
from .authoritative_sources import AuthoritativeRecord
from .credentials import CredentialRef, CredentialResolver, EnvironmentCredentialResolver


class OdooSourceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OdooConnection:
    base_url: str
    database: str
    username: str
    reader_credential: CredentialRef
    timeout_seconds: float = 10.0
    allow_insecure_http: bool = False

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        allowed = {"https"} if not self.allow_insecure_http else {"http", "https"}
        if parsed.scheme not in allowed or not parsed.hostname:
            raise ValueError("Odoo base_url is not permitted")
        if not self.database.strip() or not self.username.strip():
            raise ValueError("Odoo database and reader username are required")


class OdooHRFactSource:
    """Read-only authoritative HRIS adapter for Odoo.

    This adapter must never perform writes. Physical Odoo mutation belongs to a
    Kernel deployment CapabilityProvider and is intentionally a separate class.
    """

    def __init__(
        self,
        connection: OdooConnection,
        *,
        credentials: CredentialResolver | None = None,
        client: httpx.Client | None = None,
        termination_status_field: str = "x_administrative_termination_status",
        termination_effective_at_field: str = (
            "x_administrative_termination_effective_at"
        ),
        employment_episode_field: str = "x_administrative_employment_episode_ref",
        principal_id_field: str = "x_administrative_principal_id",
    ) -> None:
        self.connection = connection
        self.credentials = credentials or EnvironmentCredentialResolver()
        self._client = client
        self._available_models: dict[str, bool] = {}
        self._available_fields_cache: dict[str, set[str]] = {}
        self.termination_status_field = termination_status_field
        self.termination_effective_at_field = termination_effective_at_field
        self.employment_episode_field = employment_episode_field
        self.principal_id_field = principal_id_field

    def read_employee(self, employee_ref: str) -> AuthoritativeRecord:
        employee_id = _numeric_id(employee_ref, "hr.employee")
        termination_fields = [
            name
            for name in (
                self.termination_status_field,
                self.termination_effective_at_field,
                self.employment_episode_field,
                self.principal_id_field,
            )
            if name and name in self._available_fields("hr.employee")
        ]
        rows = self._execute_kw(
            "hr.employee",
            "read",
            [[employee_id]],
            {
                "fields": [
                    "id",
                    "name",
                    "department_id",
                    "parent_id",
                    "work_email",
                    "active",
                    "write_date",
                    *termination_fields,
                ]
            },
        )
        if not rows:
            return self._absent("hr.employee", employee_id)
        row = rows[0]
        department_id = _many2one_id(row.get("department_id"))
        manager_id = _many2one_id(row.get("parent_id"))
        contract = self._latest_contract(employee_id)
        value = {
            "present": True,
            "employee_ref": f"odoo:hr.employee:{employee_id}",
            "employee_id": employee_id,
            "name": row.get("name"),
            "department_ref": (
                f"odoo:hr.department:{department_id}" if department_id is not None else None
            ),
            "manager_ref": (
                f"odoo:hr.employee:{manager_id}" if manager_id is not None else None
            ),
            "work_email": row.get("work_email") or None,
            "active": bool(row.get("active", True)),
            "employment_state": contract.get("state") if contract else None,
            "employment_type": _many2one_name(contract.get("contract_type_id")) if contract else None,
            "start_date": contract.get("date_start") if contract else None,
        }
        if self.termination_status_field in termination_fields:
            raw_status = row.get(self.termination_status_field)
            status = str(raw_status).strip().lower() if raw_status else ""
            # An empty termination field is the authoritative statement that no
            # termination is scheduled for this employee.
            value["termination_status"] = status or "active"
        if self.termination_effective_at_field in termination_fields:
            value["termination_effective_at"] = (
                row.get(self.termination_effective_at_field) or None
            )
        if self.employment_episode_field in termination_fields:
            value["employment_episode_ref"] = (
                row.get(self.employment_episode_field) or None
            )
        if self.principal_id_field in termination_fields:
            value["departing_principal_id"] = (
                row.get(self.principal_id_field) or None
            )
        version = str(row.get("write_date") or "unknown")
        if contract and contract.get("write_date"):
            version = f"{version}|contract:{contract['write_date']}"
        return AuthoritativeRecord.build(
            source="odoo",
            source_ref=f"odoo:hr.employee:{employee_id}",
            source_version=version,
            value=value,
        )

    def read_department(self, department_ref: str) -> AuthoritativeRecord:
        department_id = _numeric_id(department_ref, "hr.department")
        rows = self._execute_kw(
            "hr.department",
            "read",
            [[department_id]],
            {"fields": ["id", "name", "manager_id", "parent_id", "active", "write_date"]},
        )
        if not rows:
            return self._absent("hr.department", department_id)
        row = rows[0]
        manager_id = _many2one_id(row.get("manager_id"))
        parent_id = _many2one_id(row.get("parent_id"))
        return AuthoritativeRecord.build(
            source="odoo",
            source_ref=f"odoo:hr.department:{department_id}",
            source_version=str(row.get("write_date") or "unknown"),
            value={
                "present": True,
                "department_ref": f"odoo:hr.department:{department_id}",
                "name": row.get("name"),
                "manager_ref": (
                    f"odoo:hr.employee:{manager_id}" if manager_id is not None else None
                ),
                "parent_department_ref": (
                    f"odoo:hr.department:{parent_id}" if parent_id is not None else None
                ),
                "active": bool(row.get("active", True)),
            },
        )

    def read_manager(self, employee_ref: str) -> AuthoritativeRecord:
        employee = self.read_employee(employee_ref)
        manager_ref = employee.value.get("manager_ref")
        return AuthoritativeRecord.build(
            source="odoo",
            source_ref=f"{employee.source_ref}:manager",
            source_version=employee.source_version,
            observed_at=employee.observed_at,
            value={
                "employee_ref": employee.value.get("employee_ref"),
                "manager_ref": manager_ref,
                "present": manager_ref is not None,
            },
        )

    def _latest_contract(self, employee_id: int) -> dict[str, Any] | None:
        if not self._model_available("hr.contract"):
            return None
        rows = self._execute_kw(
            "hr.contract",
            "search_read",
            [[("employee_id", "=", employee_id)]],
            {
                "fields": ["id", "date_start", "state", "contract_type_id", "write_date"],
                "order": "date_start desc,id desc",
                "limit": 1,
            },
        )
        return rows[0] if rows else None

    def _model_available(self, model: str) -> bool:
        """Return whether one optional Odoo model is installed."""
        cached = self._available_models.get(model)
        if cached is not None:
            return cached
        try:
            self._execute_kw(model, "search_count", [[]])
        except OdooSourceError as exc:
            text = str(exc).lower()
            if "doesn't exist" not in text and "does not exist" not in text:
                raise
            self._available_models[model] = False
            return False
        self._available_models[model] = True
        return True

    def _available_fields(self, model: str) -> set[str]:
        """Return the field names this reader can see on one Odoo model."""
        cached = self._available_fields_cache.get(model)
        if cached is not None:
            return cached
        try:
            result = self._execute_kw(model, "fields_get", [[], ["string"]])
        except OdooSourceError:
            # A reader without field introspection still keeps the base read
            # path working; optional facts then simply stay absent.
            self._available_fields_cache[model] = set()
            return set()
        available = set(result) if isinstance(result, dict) else set()
        self._available_fields_cache[model] = available
        return available

    def _absent(self, model: str, record_id: int) -> AuthoritativeRecord:
        observed_at = utcnow()
        return AuthoritativeRecord.build(
            source="odoo",
            source_ref=f"odoo:{model}:{record_id}",
            source_version=f"absent@{observed_at.isoformat()}",
            observed_at=observed_at,
            value={"present": False, "record_id": record_id, "model": model},
        )

    def _execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        secret = self.credentials.resolve(self.connection.reader_credential)
        uid = self._rpc(
            "common",
            "authenticate",
            [self.connection.database, self.connection.username, secret, {}],
        )
        if not isinstance(uid, int) or uid <= 0:
            raise OdooSourceError("Odoo reader authentication failed")
        return self._rpc(
            "object",
            "execute_kw",
            [
                self.connection.database,
                uid,
                secret,
                model,
                method,
                args,
                kwargs or {},
            ],
        )

    def _rpc(self, service: str, method: str, args: list[Any]) -> Any:
        url = f"{self.connection.base_url.rstrip('/')}/jsonrpc"
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": method, "args": args},
            "id": str(uuid4()),
        }
        try:
            if self._client is not None:
                response = self._client.post(url, json=payload)
            else:
                response = httpx.post(url, json=payload, timeout=self.connection.timeout_seconds)
            response.raise_for_status()
            raw = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OdooSourceError("Odoo authoritative read failed") from exc
        if not isinstance(raw, dict):
            raise OdooSourceError("Odoo JSON-RPC response is invalid")
        if raw.get("error") is not None:
            error = raw.get("error")
            data = error.get("data") if isinstance(error, dict) else None
            detail = ""
            if isinstance(data, dict):
                detail = str(data.get("message") or "")
            if not detail and isinstance(error, dict):
                detail = str(error.get("message") or "")
            raise OdooSourceError(
                "Odoo JSON-RPC returned an application error"
                + (f": {detail}" if detail else "")
            )
        return raw.get("result")


def _numeric_id(ref: str, expected_model: str) -> int:
    value = ref.strip()
    if value.isdigit():
        return int(value)
    prefix = f"odoo:{expected_model}:"
    if value.startswith(prefix) and value[len(prefix) :].isdigit():
        return int(value[len(prefix) :])
    raise OdooSourceError(f"invalid Odoo {expected_model} reference")


def _many2one_id(value: Any) -> int | None:
    if (
        isinstance(value, (list, tuple))
        and value
        and isinstance(value[0], int)
        and not isinstance(value[0], bool)
    ):
        return value[0]
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _many2one_name(value: Any) -> str | None:
    if isinstance(value, (list, tuple)) and len(value) >= 2 and isinstance(value[1], str):
        return value[1]
    if isinstance(value, str):
        return value
    return None


__all__ = ["OdooConnection", "OdooHRFactSource", "OdooSourceError"]
