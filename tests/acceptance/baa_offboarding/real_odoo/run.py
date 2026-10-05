from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from administrative_orchestrator.integrations.credentials import CredentialRef
from administrative_orchestrator.integrations.effect_common import ConnectorStatus
from administrative_orchestrator.integrations.odoo_effects import (
    OdooEffectConnection,
    OdooEmployeeDeactivateConnector,
    OdooEmployeeDeactivateVerifier,
    OdooEmployeeEffectConnector,
)

DATABASE = "baa_odoo"
ADMIN_LOGIN = "admin"
ADMIN_PASSWORD = "admin"
WRITER_LOGIN = "baa-writer"
VERIFIER_LOGIN = "baa-verifier"
REQUEST_FIELD = "x_administrative_deactivate_request_ref"


class OdooRpc:
    def __init__(self, base_url: str, database: str = DATABASE) -> None:
        self.base_url = base_url.rstrip("/")
        self.database = database
        self.client = httpx.Client(timeout=15.0)

    def close(self) -> None:
        self.client.close()

    def rpc(self, service: str, method: str, args: list[Any]) -> Any:
        response = self.client.post(
            f"{self.base_url}/jsonrpc",
            json={
                "jsonrpc": "2.0",
                "method": "call",
                "params": {"service": service, "method": method, "args": args},
                "id": str(uuid4()),
            },
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("Odoo returned a non-object JSON-RPC response")
        if body.get("error") is not None:
            raise RuntimeError(
                "Odoo JSON-RPC rejected the operation: "
                + json.dumps(body["error"], sort_keys=True)[:1000]
            )
        return body.get("result")

    def wait_ready(self, timeout_seconds: int = 180) -> None:
        deadline = time.monotonic() + timeout_seconds
        last: object = None
        while time.monotonic() < deadline:
            try:
                version = self.rpc("common", "version", [])
                if isinstance(version, dict):
                    return
                last = version
            except Exception as exc:  # readiness diagnostic only
                last = repr(exc)
            time.sleep(1.0)
        raise RuntimeError(f"Odoo did not become ready: {last!r}")

    def authenticate(self, login: str, password: str) -> int:
        uid = self.rpc(
            "common",
            "authenticate",
            [self.database, login, password, {}],
        )
        if not isinstance(uid, int) or uid <= 0:
            raise RuntimeError(f"Odoo authentication failed for {login!r}")
        return uid

    def execute_kw(
        self,
        *,
        login: str,
        password: str,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        uid = self.authenticate(login, password)
        return self.rpc(
            "object",
            "execute_kw",
            [
                self.database,
                uid,
                password,
                model,
                method,
                args,
                kwargs or {},
            ],
        )

    def admin(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        return self.execute_kw(
            login=ADMIN_LOGIN,
            password=ADMIN_PASSWORD,
            model=model,
            method=method,
            args=args,
            kwargs=kwargs,
        )

    def server_version(self) -> str | None:
        payload = self.rpc("common", "version", [])
        if isinstance(payload, dict):
            version = payload.get("server_version")
            return str(version) if version else None
        return None

    def xmlid(self, module: str, name: str) -> int:
        rows = self.admin(
            "ir.model.data",
            "search_read",
            [[("module", "=", module), ("name", "=", name)]],
            {"fields": ["res_id"], "limit": 1},
        )
        if not isinstance(rows, list) or len(rows) != 1:
            raise RuntimeError(f"missing Odoo external id: {module}.{name}")
        return int(rows[0]["res_id"])

    def setup_custom_field(self) -> None:
        model_rows = self.admin(
            "ir.model",
            "search_read",
            [[("model", "=", "hr.employee")]],
            {"fields": ["id"], "limit": 1},
        )
        if not isinstance(model_rows, list) or len(model_rows) != 1:
            raise RuntimeError("hr.employee model not found")
        model_id = int(model_rows[0]["id"])
        existing = self.admin(
            "ir.model.fields",
            "search_read",
            [[("model_id", "=", model_id), ("name", "=", REQUEST_FIELD)]],
            {"fields": ["id"], "limit": 1},
        )
        if isinstance(existing, list) and existing:
            return
        field_id = self.admin(
            "ir.model.fields",
            "create",
            [
                {
                    "name": REQUEST_FIELD,
                    "field_description": "Administrative Deactivate Request Ref",
                    "model_id": model_id,
                    "ttype": "char",
                    "state": "manual",
                    "required": False,
                    "readonly": False,
                }
            ],
        )
        if not isinstance(field_id, int) or field_id <= 0:
            raise RuntimeError("failed to create Odoo custom request field")

    def grant_model_access(
        self,
        *,
        group_id: int,
        group_name: str,
        model: str,
        read: bool,
        write: bool,
    ) -> None:
        model_rows = self.admin(
            "ir.model",
            "search_read",
            [[("model", "=", model)]],
            {"fields": ["id"], "limit": 1},
        )
        if not isinstance(model_rows, list) or len(model_rows) != 1:
            raise RuntimeError(f"model not found for ACL: {model}")
        model_id = int(model_rows[0]["id"])
        acl_id = self.admin(
            "ir.model.access",
            "create",
            [
                {
                    "name": f"{group_name} {model} ACL",
                    "model_id": model_id,
                    "group_id": group_id,
                    "perm_read": read,
                    "perm_write": write,
                    "perm_create": False,
                    "perm_unlink": False,
                }
            ],
        )
        if not isinstance(acl_id, int) or acl_id <= 0:
            raise RuntimeError(f"failed to create ACL for {group_name!r} on {model}")

    def create_access_group(
        self,
        *,
        name: str,
        model: str,
        read: bool,
        write: bool,
    ) -> int:
        group_id = self.admin("res.groups", "create", [{"name": name}])
        if not isinstance(group_id, int) or group_id <= 0:
            raise RuntimeError(f"failed to create group {name!r}")
        self.grant_model_access(
            group_id=group_id,
            group_name=name,
            model=model,
            read=read,
            write=write,
        )
        return group_id

    def create_user(
        self,
        *,
        login: str,
        password: str,
        group_id: int,
    ) -> int:
        base_user = self.xmlid("base", "group_user")
        user_id = self.admin(
            "res.users",
            "create",
            [
                {
                    "name": login,
                    "login": login,
                    "password": password,
                    "groups_id": [(6, 0, [base_user, group_id])],
                }
            ],
        )
        if not isinstance(user_id, int) or user_id <= 0:
            raise RuntimeError(f"failed to create Odoo user {login!r}")
        self.authenticate(login, password)
        return user_id

    def create_employee(self) -> int:
        employee_id = self.admin(
            "hr.employee",
            "create",
            [{"name": "BAA Real Odoo Employee", "active": True}],
        )
        if not isinstance(employee_id, int) or employee_id <= 0:
            raise RuntimeError("failed to create Odoo employee")
        return employee_id


async def run_connectors(
    *,
    base_url: str,
    employee_id: int,
    writer_password: str,
    verifier_password: str,
) -> dict[str, Any]:
    os.environ["BAA_ODOO_WRITER_SECRET"] = writer_password
    os.environ["BAA_ODOO_VERIFIER_SECRET"] = verifier_password

    writer_transport = OdooEmployeeEffectConnector(
        OdooEffectConnection(
            base_url=base_url,
            database=DATABASE,
            username=WRITER_LOGIN,
            credential=CredentialRef(
                "odoo:baa-writer",
                "BAA_ODOO_WRITER_SECRET",
            ),
            allow_insecure_http=True,
        )
    )
    verifier_transport = OdooEmployeeEffectConnector(
        OdooEffectConnection(
            base_url=base_url,
            database=DATABASE,
            username=VERIFIER_LOGIN,
            credential=CredentialRef(
                "odoo:baa-verifier",
                "BAA_ODOO_VERIFIER_SECRET",
            ),
            allow_insecure_http=True,
        )
    )

    subject_ref = f"odoo:hr.employee:{employee_id}"
    request_ref = f"request:deactivate:{uuid4()}"

    writer = OdooEmployeeDeactivateConnector(writer_transport)
    result = await writer.invoke(
        request_ref=request_ref,
        subject_ref=subject_ref,
        parameters={"employee_external_ref": subject_ref},
    )
    if result.status is not ConnectorStatus.SUCCEEDED:
        raise AssertionError(f"Odoo deactivate failed: {result}")

    verifier = OdooEmployeeDeactivateVerifier(
        OdooEmployeeDeactivateConnector(verifier_transport)
    )
    observed = await verifier.observe(
        subject_ref=subject_ref,
        expected_postcondition={
            "employee_external_ref": subject_ref,
            "active": False,
        },
    )
    if observed.status is not ConnectorStatus.SUCCEEDED:
        raise AssertionError(f"Odoo verifier unavailable: {observed}")
    expected = {
        "target_system": "hris",
        "operation": "employee.deactivate",
        "subject_ref": subject_ref,
        "active": False,
    }
    if observed.observed_postcondition != expected:
        raise AssertionError(
            f"Odoo deactivate read-back mismatch: {observed.observed_postcondition}"
        )

    reconciled = await writer.reconcile(request_ref)
    if reconciled is None or reconciled.status is not ConnectorStatus.SUCCEEDED:
        raise AssertionError(f"Odoo deactivate reconciliation failed: {reconciled}")

    return {
        "subject_ref": subject_ref,
        "request_ref": request_ref,
        "status": result.status.value,
        "reconciled": bool(reconciled.reconciled),
        "observed": observed.observed_postcondition,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:28069")
    parser.add_argument("--evidence-path", required=True)
    args = parser.parse_args()

    writer_password = os.environ["BAA_ODOO_WRITER_PASSWORD"]
    verifier_password = os.environ["BAA_ODOO_VERIFIER_PASSWORD"]

    rpc = OdooRpc(args.base_url)
    try:
        rpc.wait_ready()
        rpc.authenticate(ADMIN_LOGIN, ADMIN_PASSWORD)
        rpc.setup_custom_field()
        writer_group = rpc.create_access_group(
            name="BAA Odoo Writer",
            model="hr.employee",
            read=True,
            write=True,
        )
        # hr.employee.active is synchronized to the underlying resource record
        # by Odoo itself. Grant only the model access needed for that exact
        # cascade rather than assigning a broad HR administrator role.
        rpc.grant_model_access(
            group_id=writer_group,
            group_name="BAA Odoo Writer",
            model="resource.resource",
            read=True,
            write=True,
        )
        verifier_group = rpc.create_access_group(
            name="BAA Odoo Verifier",
            model="hr.employee",
            read=True,
            write=False,
        )
        rpc.create_user(
            login=WRITER_LOGIN,
            password=writer_password,
            group_id=writer_group,
        )
        rpc.create_user(
            login=VERIFIER_LOGIN,
            password=verifier_password,
            group_id=verifier_group,
        )
        employee_id = rpc.create_employee()

        connector_evidence = asyncio.run(
            run_connectors(
                base_url=args.base_url,
                employee_id=employee_id,
                writer_password=writer_password,
                verifier_password=verifier_password,
            )
        )

        verifier_write_denied = False
        verifier_write_error: str | None = None
        try:
            changed = rpc.execute_kw(
                login=VERIFIER_LOGIN,
                password=verifier_password,
                model="hr.employee",
                method="write",
                args=[[employee_id], {"active": True}],
            )
            if changed is True:
                raise AssertionError(
                    "verifier credential unexpectedly acquired employee write authority"
                )
        except RuntimeError as exc:
            verifier_write_denied = True
            verifier_write_error = type(exc).__name__

        if not verifier_write_denied:
            raise AssertionError("verifier write denial was not observed")

        final_rows = rpc.admin(
            "hr.employee",
            "read",
            [[employee_id]],
            {"fields": ["id", "active", REQUEST_FIELD]},
        )
        if not isinstance(final_rows, list) or len(final_rows) != 1:
            raise AssertionError("final Odoo employee read failed")
        final_row = final_rows[0]
        if final_row.get("active") is not False:
            raise AssertionError(f"employee unexpectedly active: {final_row}")
        if not final_row.get(REQUEST_FIELD):
            raise AssertionError("durable deactivate request marker missing")

        evidence = {
            "status": "passed",
            "generated_at": datetime.now(UTC).isoformat(),
            "qualification": (
                "High-fidelity connector acceptance against a real ephemeral Odoo "
                "server and PostgreSQL database; not production tenant evidence."
            ),
            "odoo": {
                "reported_version": rpc.server_version(),
                "database": DATABASE,
                "writer_login": WRITER_LOGIN,
                "verifier_login": VERIFIER_LOGIN,
                "writer_verifier_separated": WRITER_LOGIN != VERIFIER_LOGIN,
                "verifier_write_denied": verifier_write_denied,
                "verifier_write_error_type": verifier_write_error,
                "durable_request_marker_present": bool(final_row.get(REQUEST_FIELD)),
                "final_active": bool(final_row.get("active", True)),
            },
            "connector": connector_evidence,
        }
        path = Path(args.evidence_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(evidence, indent=2, sort_keys=True))
    finally:
        rpc.close()
        os.environ.pop("BAA_ODOO_WRITER_SECRET", None)
        os.environ.pop("BAA_ODOO_VERIFIER_SECRET", None)


if __name__ == "__main__":
    main()
