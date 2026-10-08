"""P3 isolated real-product access-probe qualification.

Only ephemeral Keycloak/Odoo identities created by real_e2e/run.py are used.
The test does NOT claim interval continuity, calibrated joint risk, or harm.
Secrets/bearer tokens are never written to evidence.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from baa_protocol.temporal_collector import (
    CollectorSources,
    ReadOnlyCollector,
    bracket_snapshots,
    classify_point,
)
from baa_protocol.temporal_outcome import (
    AccessProbe,
    SubjectPolicy,
    measure_offboarding,
)
from run import (
    KEYCLOAK_REALM,
    KEYCLOAK_SESSION_CLIENT,
    KEYCLOAK_USERNAME,
    KEYCLOAK_VERIFIER,
    ODOO_VERIFIER,
    _authorized_case,
    _build_engine,
    _drive_episode,
    _setup_products,
    _wait_ready,
)


def _diagnose_issued_token(keycloak: Any, token: str) -> dict[str, Any]:
    """Non-authoritative metadata only: no raw JWT or confidential claims."""
    result: dict[str, Any] = {}
    try:
        payload_b64 = token.split(".")[1]
        decoded = base64.urlsafe_b64decode(
            payload_b64 + "=" * (-len(payload_b64) % 4)
        )
        claims = json.loads(decoded)
        if isinstance(claims, dict):
            result["unverified_jwt_aud"] = claims.get("aud")
            result["unverified_jwt_azp"] = claims.get("azp")
    except (IndexError, ValueError, TypeError):
        result["unverified_jwt_metadata"] = "not-decodable"

    token_endpoint = (
        f"{keycloak.base_url}/realms/{KEYCLOAK_REALM}/"
        "protocol/openid-connect/token/introspect"
    )
    response = keycloak.client.post(
        token_endpoint,
        data={
            "client_id": KEYCLOAK_VERIFIER,
            "client_secret": os.environ["BAA_REAL_KEYCLOAK_VERIFIER_SECRET"],
            "token": token,
        },
        timeout=10,
    )
    result["introspection_http_status"] = response.status_code
    try:
        data = response.json()
        if isinstance(data, dict):
            result["introspection_active"] = data.get("active")
            result["introspection_client_id"] = data.get("client_id")
    except ValueError:
        result["introspection_payload"] = "invalid-json"

    userinfo = keycloak.client.get(
        f"{keycloak.base_url}/realms/{KEYCLOAK_REALM}/"
        "protocol/openid-connect/userinfo",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    result["userinfo_http_status"] = userinfo.status_code
    return result


def _configure_probe_audience(keycloak: Any) -> None:
    """Qualify the Keycloak 26.8 resource-server introspection audience.

    This changes ONLY the disposable realm's test client protocol mapper. It
    neither grants a realm-management role nor weakens introspection checks.
    """
    client = keycloak._client_rep(KEYCLOAK_SESSION_CLIENT)
    keycloak.request(
        "POST",
        f"/admin/realms/{KEYCLOAK_REALM}/clients/{client['id']}/protocol-mappers/models",
        json_body={
            "name": "p3-protected-resource-audience",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-audience-mapper",
            "consentRequired": False,
            "config": {
                "included.client.audience": KEYCLOAK_VERIFIER,
                "access.token.claim": "true",
                "id.token.claim": "false",
            },
        },
        expected={201},
    )


def _password_token(keycloak: Any, username: str, password: str) -> str:
    response = keycloak.client.post(
        f"{keycloak.base_url}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": KEYCLOAK_SESSION_CLIENT,
            "username": username,
            "password": password,
            "scope": "openid",
        },
        timeout=10.0,
    )
    if response.status_code != 200:
        raise AssertionError(
            f"isolated user direct-grant qualification failed: HTTP {response.status_code}"
        )
    token = response.json().get("access_token")
    if not isinstance(token, str) or not token:
        raise AssertionError("isolated user token missing")
    return token


def _protected_probe(base_url: str, token: str, expected_id: str) -> AccessProbe:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/protected",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            if response.status != 200:
                return AccessProbe.UNKNOWN
            result = json.load(response)
            if (
                not isinstance(result, dict)
                or result.get("access") != "ALLOW"
                or result.get("subject") != expected_id
            ):
                return AccessProbe.UNKNOWN
            return AccessProbe.ALLOW
    except urllib.error.HTTPError as error:
        if error.code != 403:
            return AccessProbe.UNKNOWN
        try:
            result = json.loads(error.read())
        except (ValueError, OSError):
            return AccessProbe.UNKNOWN
        return (
            AccessProbe.DENY
            if isinstance(result, dict) and result.get("access") == "DENY"
            else AccessProbe.UNKNOWN
        )
    except (urllib.error.URLError, OSError, TimeoutError, ValueError):
        return AccessProbe.UNKNOWN


def _identity(keycloak: Any, username: str) -> str:
    rows = keycloak.request(
        "GET",
        f"/admin/realms/{KEYCLOAK_REALM}/users",
        params={"username": username, "exact": "true"},
        expected={200},
    ).json()
    if not isinstance(rows, list) or len(rows) != 1:
        raise AssertionError("isolated control Keycloak identity not uniquely found")
    identity = rows[0].get("id")
    if not isinstance(identity, str) or not identity:
        raise AssertionError("isolated identity missing id")
    return identity


def _control_employee(odoo: Any) -> int:
    rows = odoo.admin(
        "hr.employee",
        "search_read",
        [[("name", "=", "BAA Real E2E Exposure Control Employee")]],
        {"fields": ["id"], "limit": 2, "context": {"active_test": False}},
    )
    if not isinstance(rows, list) or len(rows) != 1:
        raise AssertionError("isolated Odoo control employee not uniquely found")
    value = rows[0].get("id")
    if type(value) is not int or value <= 0:
        raise AssertionError("isolated control employee id invalid")
    return value


def _snapshot_json(snapshot: Any, point_result: bool | None) -> dict[str, Any]:
    value = snapshot.projection
    return {
        "subject_id": snapshot.subject_id,
        "time_unix_s": snapshot.observed_at_s,
        "kind": snapshot.kind.value,
        "collector": snapshot.collector_id,
        "evidence_ref": snapshot.evidence_ref,
        "point_violation": point_result,
        "sources_failed": list(snapshot.errors),
        "projection": {
            "hris_active": value.hris_active,
            "iam_enabled": value.iam_enabled,
            "active_sessions": value.active_sessions,
            "access_probe": value.access_probe.value,
        },
    }


def _write_evidence(path: str, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("P3 evidence written:", target, "status:", payload["status"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-base", required=True)
    parser.add_argument("--odoo-base", required=True)
    parser.add_argument("--keycloak-base", required=True)
    parser.add_argument("--probe-base", required=True)
    parser.add_argument("--runtime-token", required=True)
    parser.add_argument("--evidence-path", required=True)
    args = parser.parse_args()

    evidence: dict[str, Any] = {
        "status": "qualification_failed",
        "stage": "setup",
        "study": "p3-isolated-protected-resource-access-probe-v1",
        "evidence_grade": "real isolated product point-probe; not interval-continuity",
        "claim_exclusions": [
            "no production tenant", "no continuous duration measurement",
            "no calibrated joint risk", "no risk-factor assignment",
        ],
        "samples": [],
        "generated_at": datetime.now(UTC).isoformat(),
    }
    odoo = keycloak = bridge = None
    try:
        _wait_ready(f"{args.runtime_base}/healthz")
        _wait_ready(args.odoo_base)
        _wait_ready(f"{args.keycloak_base}/realms/master")
        _wait_ready(args.probe_base.rstrip("/") + "/healthz")

        odoo, keycloak, employee_id, user_id, subject_ref = _setup_products(
            odoo_base=args.odoo_base,
            keycloak_base=args.keycloak_base,
            odoo_writer_password=os.environ["BAA_REAL_ODOO_WRITER_PASSWORD"],
            odoo_verifier_password=os.environ["BAA_REAL_ODOO_VERIFIER_PASSWORD"],
            keycloak_admin_password=os.environ["BAA_REAL_KEYCLOAK_ADMIN_PASSWORD"],
            keycloak_writer_secret=os.environ["BAA_REAL_KEYCLOAK_WRITER_SECRET"],
            keycloak_verifier_secret=os.environ["BAA_REAL_KEYCLOAK_VERIFIER_SECRET"],
            keycloak_user_password=os.environ["BAA_REAL_KEYCLOAK_USER_PASSWORD"],
        )
        control_username = f"{KEYCLOAK_USERNAME}-exposure-control"
        control_user_id = _identity(keycloak, control_username)
        control_employee_id = _control_employee(odoo)
        control_ref = f"odoo:hr.employee:{control_employee_id}"

        # Keycloak 26.8 requires the introspecting confidential resource
        # client to be a token audience. The first qualification attempt
        # (run 37709634277, artifact 11520849286) failed with active test
        # sessions but baseline introspection denied: keep that failure as
        # an instrument-qualification record, not a loss observation.
        _configure_probe_audience(keycloak)

        # All tokens exist only in memory. The previously issued target token
        # is reused post-disable: a new login test alone would be insufficient.
        user_password = os.environ["BAA_REAL_KEYCLOAK_USER_PASSWORD"]
        bearer_by_subject = {
            subject_ref: _password_token(keycloak, KEYCLOAK_USERNAME, user_password),
            control_ref: _password_token(keycloak, control_username, user_password),
        }
        identity_ids = {subject_ref: user_id, control_ref: control_user_id}
        evidence["token_diagnostics"] = {
            "target": _diagnose_issued_token(
                keycloak, bearer_by_subject[subject_ref]
            ),
            "control": _diagnose_issued_token(
                keycloak, bearer_by_subject[control_ref]
            ),
            "role": "instrument qualification only; JWT payload not trusted as authorization",
        }
        employee_ids = {subject_ref: employee_id, control_ref: control_employee_id}

        verifier_token = keycloak.service_token(
            KEYCLOAK_VERIFIER, os.environ["BAA_REAL_KEYCLOAK_VERIFIER_SECRET"]
        )

        def read_hris(subject: str) -> bool:
            rows = odoo.execute_kw(
                login=ODOO_VERIFIER,
                password=os.environ["BAA_REAL_ODOO_VERIFIER_PASSWORD"],
                model="hr.employee",
                method="read",
                args=[[employee_ids[subject]]],
                kwargs={"fields": ["active"], "context": {"active_test": False}},
            )
            if not isinstance(rows, list) or len(rows) != 1:
                raise ValueError("ambiguous HRIS read")
            active = rows[0].get("active")
            if type(active) is not bool:
                raise ValueError("HRIS active field missing or invalid")
            return active

        def read_iam(subject: str) -> tuple[bool, int]:
            user = keycloak.request(
                "GET",
                f"/admin/realms/{KEYCLOAK_REALM}/users/{identity_ids[subject]}",
                token=verifier_token,
                expected={200},
            ).json()
            sessions = keycloak.request(
                "GET",
                f"/admin/realms/{KEYCLOAK_REALM}/users/{identity_ids[subject]}/sessions",
                token=verifier_token,
                expected={200},
            ).json()
            if not isinstance(user, dict) or type(user.get("enabled")) is not bool:
                raise ValueError("IAM enabled field missing")
            if not isinstance(sessions, list):
                raise ValueError("IAM session read malformed")
            return user["enabled"], len(sessions)

        def probe(subject: str) -> AccessProbe:
            return _protected_probe(
                args.probe_base, bearer_by_subject[subject], identity_ids[subject]
            )

        collector = ReadOnlyCollector(
            sources=CollectorSources(
                collector_id="p3-real-e2e-readonly-v1",
                hris_source="isolated-odoo-verifier",
                iam_source="isolated-keycloak-verifier",
                access_probe_source="online-introspection-protected-resource",
                hris_reader_domain="odoo:verifier",
                iam_reader_domain="keycloak:verifier",
                access_probe_domain="p3-protected-resource",
                hris_writer_domain="odoo:writer",
                iam_writer_domain="keycloak:writer",
            ),
            read_hris_active=read_hris,
            read_iam_state=read_iam,
            probe_access=probe,
        )
        now = datetime.now(UTC)
        # Same frozen effective time as _authorized_case(now,...). This
        # intentionally starts with a known late-revocation violation solely
        # for the disposable test subject; control remains entitled.
        policies = (
            SubjectPolicy(
                subject_id=subject_ref,
                effective_at_s=int((now - timedelta(minutes=1)).timestamp()),
                grace_s=0,
            ),
            SubjectPolicy(
                subject_id=control_ref,
                effective_at_s=int((now + timedelta(days=1)).timestamp()),
                grace_s=0,
            ),
        )
        evidence["identity_mapping"] = {
            "target": {
                "odoo_subject": subject_ref,
                "odoo_employee_id": employee_id,
                "keycloak_user_id": user_id,
            },
            "test_only_control": {
                "odoo_subject": control_ref,
                "odoo_employee_id": control_employee_id,
                "keycloak_user_id": control_user_id,
                "binding_provenance": "explicit isolated-fixture pairing; not an organizational identity claim",
            },
        }
        evidence["policy"] = {
            "target_effective_at": policies[0].effective_at_s,
            "target_grace_s": 0,
            "control_effective_at": policies[1].effective_at_s,
            "clock_error_bound_s": None,
            "horizon_claim": "snapshot brackets only",
        }

        def sample(label: str) -> dict[str, Any]:
            snapshots = {
                s: collector.capture(
                    subject_id=s, observed_at_s=int(time.time()),
                    sample_id=f"{label}:{s}",
                )
                for s in (subject_ref, control_ref)
            }
            rec = {
                "phase": label,
                "samples": {
                    s: _snapshot_json(snapshots[s], classify_point(snapshots[s], policy=p))
                    for s, p in zip((subject_ref, control_ref), policies, strict=True)
                },
            }
            evidence["samples"].append(rec)
            return {"raw": snapshots, "record": rec}

        evidence["stage"] = "baseline_probe"
        before = sample("before_dispatch")
        target_before = before["record"]["samples"][subject_ref]
        control_before = before["record"]["samples"][control_ref]
        if target_before["point_violation"] is not True:
            raise AssertionError("known injected pre-dispatch violation was not identified")
        if target_before["projection"]["access_probe"] != "allow":
            raise AssertionError("target failed baseline actual protected access")
        if control_before["point_violation"] is not False:
            raise AssertionError("compliant control failed baseline qualification")
        # Explicit negative instrument control: a separate unreachable
        # endpoint must be UNKNOWN, not an alleged revocation.
        outage = ReadOnlyCollector(
            sources=collector.sources,
            read_hris_active=read_hris,
            read_iam_state=read_iam,
            probe_access=lambda subject: _protected_probe(
                "http://127.0.0.1:1",
                bearer_by_subject[subject],
                identity_ids[subject],
            ),
        ).capture(
            subject_id=subject_ref,
            observed_at_s=int(time.time()),
            sample_id="probe_network_outage",
        )
        evidence["outage_control"] = _snapshot_json(
            outage, classify_point(outage, policy=policies[0])
        )
        if outage.projection.access_probe is not AccessProbe.UNKNOWN:
            raise AssertionError("probe outage was incorrectly recorded as authorization denial")
        evidence["stage"] = "dispatch"

        store, case = _authorized_case(
            now, subject_ref=subject_ref, keycloak_user_id=user_id
        )
        engine, bridge, gate, readback = _build_engine(
            store=store,
            runtime_base=args.runtime_base,
            odoo_base=args.odoo_base,
            keycloak_base=args.keycloak_base,
            runtime_token=args.runtime_token,
            now=now,
            odoo_admin=odoo,
            keycloak_admin=keycloak,
            fault_mode="none",
        )
        result, status_trace, _, _, _ = _drive_episode(
            engine, case, scenario="normal", odoo=odoo, keycloak=keycloak,
            employee_id=employee_id, keycloak_user_id=user_id
        )
        evidence["execution"] = {
            "final_state": result.status.value,
            "status_trace": status_trace,
            "covered_effects_verified": bool(
                len(gate._kernels) == 1
                and next(iter(gate._kernels.values())).externally_complete()
            ),
        }
        evidence["stage"] = "post-dispatch-probe"
        # Preserve all observations, including lag/UNKNOWN, in the denominator.
        attempts = []
        deadline = time.monotonic() + 12.0
        while True:
            after = sample(f"after_dispatch_{len(attempts)}")
            target = after["record"]["samples"][subject_ref]
            control = after["record"]["samples"][control_ref]
            attempts.append({
                "target_access": target["projection"]["access_probe"],
                "control_access": control["projection"]["access_probe"],
                "t": target["time_unix_s"],
            })
            if (
                target["projection"]["access_probe"] == "deny"
                and target["point_violation"] is False
                and control["projection"]["access_probe"] == "allow"
                and control["point_violation"] is False
            ):
                break
            if time.monotonic() >= deadline:
                raise AssertionError(
                    "qualified protected-resource cutover did not converge: "
                    f"attempts={attempts}"
                )
            time.sleep(1.0)

        # Do not convert two points to continuous subject-second truth.
        before_snap = before["raw"][subject_ref]
        after_snap = after["raw"][subject_ref]
        if after_snap.observed_at_s <= before_snap.observed_at_s:
            time.sleep(1.05)
            after = sample("after_dispatch_final_bracket")
            after_snap = after["raw"][subject_ref]
        bracket = bracket_snapshots(before_snap, after_snap)
        outcome = measure_offboarding(
            policies=(policies[0],),
            observations=(bracket,),
            horizon_start_s=before_snap.observed_at_s,
            horizon_end_s=after_snap.observed_at_s,
            max_clock_error_s=0,
        )
        evidence["temporal_y"] = {
            "instrument_bound_subject_seconds": [
                outcome.joint_violation.lower_s,
                outcome.joint_violation.upper_s,
            ],
            "exact_duration_identified": outcome.identified,
            "observation_kind": bracket.kind.value,
            "clock_error_bound": "not independently qualified",
            "claim": "snapshots do not identify continuous access duration",
        }
        if outcome.identified:
            raise AssertionError("polling snapshots improperly identified exact outcome")
        evidence["status"] = "qualified_point_probe_only"
        evidence["stage"] = "complete"
    except Exception as exc:
        evidence["error"] = {
            "type": type(exc).__name__,
            "detail": "See bounded step logs; no exception text stored to avoid credential leakage",
        }
        raise
    finally:
        if bridge is not None:
            bridge.close()
        if odoo is not None:
            odoo.close()
        if keycloak is not None:
            keycloak.close()
        _write_evidence(args.evidence_path, evidence)


if __name__ == "__main__":
    main()
