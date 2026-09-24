from world_runtime import WorldRuntime
from world_runtime.migrations import MigrationDisposition, SemanticMigrator


def test_agent_kernel_migration_builds_canonical_responsibility_work_and_run() -> None:
    runtime = WorldRuntime.sqlite()
    migrator = SemanticMigrator(runtime)
    records = [
        {
            "namespace": "responsibility",
            "record": {
                "id": "resp-1",
                "object_type": "StandingResponsibility",
                "responsibility_kind": "administrative",
                "statement": "onboard employee 1",
                "scope": {"domain": "administrative"},
            },
        },
        {
            "namespace": "responsibility",
            "record": {
                "id": "admission-1",
                "object_type": "ResponsibilityAdmission",
                "responsibility_ref": "resp-1",
                "principal_ref": "service:administrative",
            },
        },
        {
            "namespace": "work",
            "record": {
                "id": "legacy-work-1",
                "kind": "administrative-effect",
                "title": "create employee",
                "metadata": {"responsibility_ref": "resp-1"},
                "requested_capabilities": ["administrative.hris.employee.create.v1"],
            },
        },
        {
            "namespace": "run",
            "record": {
                "id": "legacy-run-1",
                "work_id": "legacy-work-1",
                "workflow_id": "administrative-effect",
                "status": "succeeded",
            },
        },
    ]

    report = migrator.import_records("agent-kernel", records)

    assert report.deletion_ready is True
    assert report.unresolved == 0
    assert report.rejected == 0
    assert report.mapped == 4
    responsibility = runtime.responsibility.get("resp-1")
    assert responsibility.principal == "service:administrative"
    work = runtime.list_work()
    assert len(work) == 1
    assert work[0].responsibility_id == "resp-1"
    runs = runtime.list_runs(work[0].id)
    assert len(runs) == 1
    assert runs[0].status == "completed"


def test_agent_kernel_work_migration_accepts_standing_responsibility_alias() -> None:
    runtime = WorldRuntime.sqlite()
    migrator = SemanticMigrator(runtime)
    records = [
        {
            "namespace": "responsibility",
            "record": {
                "id": "resp-alias-1",
                "object_type": "StandingResponsibility",
                "responsibility_kind": "maintenance",
                "statement": "maintain service health",
                "scope": {"domain": "operations"},
            },
        },
        {
            "namespace": "responsibility",
            "record": {
                "id": "admission-alias-1",
                "object_type": "ResponsibilityAdmission",
                "responsibility_ref": "resp-alias-1",
                "principal_ref": "service:operations",
            },
        },
        {
            "namespace": "work",
            "record": {
                "id": "legacy-work-alias-1",
                "kind": "personal-incident-repair",
                "title": "repair service",
                "metadata": {"standing_responsibility_ref": "resp-alias-1"},
                "requested_capabilities": ["service.health.repair.v1"],
            },
        },
    ]

    report = migrator.import_records("agent-kernel", records)

    assert report.deletion_ready is True
    assert report.mapped == 3
    assert report.unresolved == 0
    assert runtime.list_work()[0].responsibility_id == "resp-alias-1"


def test_agent_kernel_migration_refuses_to_invent_missing_principal() -> None:
    runtime = WorldRuntime.sqlite()
    report = SemanticMigrator(runtime).import_records(
        "agent-kernel",
        [
            {
                "namespace": "responsibility",
                "record": {
                    "id": "resp-1",
                    "object_type": "StandingResponsibility",
                    "responsibility_kind": "administrative",
                    "statement": "onboard employee 1",
                    "scope": {},
                },
            }
        ],
    )

    assert report.deletion_ready is False
    assert report.unresolved == 1
    assert report.entries[0].disposition is MigrationDisposition.UNRESOLVED
    assert "authoritative principal" in report.entries[0].reason


def test_world_state_evidence_and_claim_revision_are_canonical_migration() -> None:
    runtime = WorldRuntime.sqlite()
    report = SemanticMigrator(runtime).import_records(
        "world-state",
        [
            {
                "namespace": "evidence",
                "record": {
                    "id": "evidence-1",
                    "kind": "runtime_observation",
                    "source": "metrics",
                    "locator": "checkout",
                    "scope": {"subject": "checkout"},
                    "validTime": {"from": "2026-09-20T00:00:00+00:00"},
                    "recordedAt": "2026-09-20T00:01:00+00:00",
                    "contentHash": "sha256:abc",
                    "data": {"latency_ms": 120},
                    "provenance": {"class": "runtime_observation", "producer": "metrics"},
                },
            },
            {
                "namespace": "claim_revision",
                "record": {
                    "id": "claim-revision-1",
                    "claimId": "claim-1",
                    "revisionNumber": 1,
                    "subject": "checkout",
                    "validTime": {"from": "2026-09-20T00:00:00+00:00"},
                    "recordedAt": "2026-09-20T00:00:10+00:00",
                },
            },
        ],
    )

    assert report.mapped == 2
    assert report.unresolved == 0
    assert report.deletion_ready is True
    assert runtime.ledger.project_get("epistemics.evidence", "evidence-1") is not None
    assert (
        runtime.ledger.project_get(
            "epistemics.claim-revision",
            "claim-revision-1",
        )
        is not None
    )


def test_meta_controller_policy_events_map_to_cognition_journal() -> None:
    runtime = WorldRuntime.sqlite()
    report = SemanticMigrator(runtime).import_records(
        "meta-controller",
        [
            {
                "namespace": "meta_policy_event",
                "record": {
                    "id": "meta-1",
                    "event_type": "MetaControlIntentSelected",
                    "controller_ref": "controller-1",
                    "kernel_state_version": 4,
                    "policy_version": "policy-v1",
                    "payload": {"intent": "wait"},
                    "basis_refs": ["evidence:1"],
                    "created_at": "2026-09-20T00:00:00+00:00",
                },
            }
        ],
    )

    assert report.deletion_ready is True
    assert report.mapped == 1
    events = runtime.ledger.events(stream="cognition:controller-1")
    assert events[-1].kind == "cognition.meta-control-intent.selected"
