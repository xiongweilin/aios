import copy

import pytest
from semantic_language import Decision, Mandate, Responsibility, SemanticKind, SemanticRef

from world_runtime import WorldRuntime


def _populated_runtime() -> WorldRuntime:
    runtime = WorldRuntime.sqlite()
    runtime.responsibility.create(
        Responsibility(
            id="responsibility:bundle",
            principal="service:test",
            subject="bundle",
        ),
        domain="test",
    )
    work = runtime.execution.admit_work(
        responsibility_id="responsibility:bundle",
        kind="bundle-test",
        payload={"value": 1},
    )
    runtime.start_run(work.id, workflow_id="bundle-test")
    runtime.decisions.record(
        Decision(
            id="decision:bundle",
            subject="bundle",
            decided_by="service:test",
            selected={
                "target_ref": "resource:bundle",
                "operation": "authorize-effect",
                "action": "demo.effect",
            },
            basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:bundle"),),
        )
    )
    runtime.governance.register_mandate(
        Mandate(
            id="mandate:bundle",
            principal="service:test",
            authority_ceiling={"action": "demo.effect", "resource": "resource:bundle"},
        )
    )
    runtime.governance.issue_authorization(
        authorization_id="authorization:bundle",
        principal="service:test",
        action="demo.effect",
        resource="resource:bundle",
        mandate_id="mandate:bundle",
        decision_id="decision:bundle",
    )
    return runtime


def test_state_bundle_round_trips_all_durable_runtime_state() -> None:
    source = _populated_runtime()
    bundle = source.state_bundle.export()
    assert source.state_bundle.validate(bundle).valid is True

    target = WorldRuntime.sqlite()
    target.state_bundle.import_bundle(bundle)

    assert target.state_bundle.export() == bundle
    assert target.responsibility.get("responsibility:bundle").principal == "service:test"
    assert target.ledger.project_get(
        "governance.authorization",
        "authorization:bundle",
    ) is not None


def test_state_bundle_digest_detects_tampering() -> None:
    runtime = _populated_runtime()
    bundle = runtime.state_bundle.export()
    tampered = copy.deepcopy(bundle)
    tampered["projections"][0]["value"]["tampered"] = True

    validation = runtime.state_bundle.validate(tampered)
    assert validation.valid is False
    assert "bundle digest mismatch" in validation.errors


def test_state_bundle_rejects_dangling_semantic_graph() -> None:
    runtime = _populated_runtime()
    bundle = runtime.state_bundle.export()
    broken = copy.deepcopy(bundle)
    broken["projections"] = [
        row
        for row in broken["projections"]
        if not (
            row["namespace"] == "responsibility.current"
            and row["key"] == "responsibility:bundle"
        )
    ]
    payload = {
        "bundle_version": broken["bundle_version"],
        "events": broken["events"],
        "projections": broken["projections"],
    }
    import hashlib
    import json

    broken["manifest"]["projection_count"] = len(broken["projections"])
    broken["manifest"]["digest"] = "sha256:" + hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    validation = runtime.state_bundle.validate(broken)
    assert validation.valid is False
    assert any(
        "references missing responsibility.current/responsibility:bundle" in error
        for error in validation.errors
    )


def test_state_bundle_import_requires_empty_destination() -> None:
    source = _populated_runtime()
    target = _populated_runtime()

    with pytest.raises(ValueError, match="empty destination"):
        target.state_bundle.import_bundle(source.state_bundle.export())
