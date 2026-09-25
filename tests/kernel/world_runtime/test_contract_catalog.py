from world_runtime.contracts import (
    CATALOG_OWNER,
    CATALOG_VERSION,
    contract_catalog,
    contract_descriptor,
    contract_schema,
    domain_conformance_vectors,
)


def test_contract_catalog_is_runtime_owned_and_versioned() -> None:
    catalog = contract_catalog()
    assert catalog["owner"] == CATALOG_OWNER == "world-runtime/contracts"
    assert catalog["catalog_version"] == CATALOG_VERSION
    assert catalog["runtime_protocol"] == "4.0"
    assert catalog["semantic_language"] == "0.2.0"
    assert "persistent_responsibility" in catalog["contracts"]
    assert "reconciliation" in catalog["contracts"]
    assert "domain_effect_execution" in catalog["contracts"]
    assert "organization_durability" in catalog["contracts"]
    assert "postgres_backup_restore" in catalog["contracts"]
    assert "institutional_lineage" in catalog["contracts"]
    assert "decision_qualification" in catalog["contracts"]
    assert "authorization_revocation" in catalog["contracts"]
    assert "ontology_version_history" in catalog["contracts"]
    assert "domain_assignment" in catalog["contracts"]
    assert "domain_report" in catalog["contracts"]
    assert "strategy_assessment" in catalog["contracts"]
    assert "goal_lifecycle_transition" in catalog["contracts"]
    assert "responsibility_graph" in catalog["contracts"]
    assert "strategic_agency" in catalog["contracts"]
    assert "continuous_qualification" in catalog["contracts"]
    assert "state_access" in catalog["contracts"]
    assert "transition_authority" in catalog["contracts"]
    assert "fresh_execution_lifecycle" in catalog["contracts"]
    assert "read_authorization" in catalog["contracts"]
    assert catalog["contracts"]["domain_report"]["current"] == "domain-report-v3"
    assert catalog["contracts"]["domain_report"]["vectors_path"] == "domain/vectors-v3.json"
    assert "provider_success_not_outcome" in catalog["invariants"]
    assert "durable_effect_identity" in catalog["invariants"]
    assert "closed_capability_request" in catalog["invariants"]
    assert "domain_reality_effect_boundary" in catalog["invariants"]
    assert "projection_cas_is_cross_process" in catalog["invariants"]
    assert "provider_dispatch_has_single_reservation_winner" in catalog["invariants"]
    assert "run_lease_is_database_fenced" in catalog["invariants"]
    assert "durable_backend_portability" in catalog["invariants"]
    assert "institutional_history_is_append_only" in catalog["invariants"]
    assert "institutional_lineage_is_single_head" in catalog["invariants"]
    assert "current_qualification_is_not_history" in catalog["invariants"]
    assert "superseded_authority_is_not_current" in catalog["invariants"]
    assert "experience_applicability_requires_current_qualification" in catalog["invariants"]
    assert "revoked_decision_is_not_current" in catalog["invariants"]
    assert "revoked_authorization_is_not_usable" in catalog["invariants"]
    assert "strategy_reassessment_requires_lineage" in catalog["invariants"]
    assert "responsibility_dependency_is_not_completion" in catalog["invariants"]
    assert "strategy_requires_explicit_decision" in catalog["invariants"]
    assert "strategy_has_no_universal_utility_function" in catalog["invariants"]
    assert "resource_budget_is_unit_bound" in catalog["invariants"]
    assert "dependency_change_creates_review_not_invalidation" in catalog["invariants"]
    assert "review_assessment_is_not_resolution" in catalog["invariants"]
    assert "sensitive_state_reads_require_authentication" in catalog["invariants"]
    assert "public_command_schemas_are_closed" in catalog["invariants"]
    assert "delegated_transition_requires_operation_authority" in catalog["invariants"]
    assert "effect_authority_remains_distinct" in catalog["invariants"]
    assert "terminal_execution_cannot_start_fresh_work" in catalog["invariants"]
    assert "provider_result_read_is_actor_bound" in catalog["invariants"]
    assert catalog["contracts"]["provider_attempt"]["current"] == "provider-attempt-v2"
    assert catalog["contracts"]["work_admission"]["current"] == "work-admission-v4"
    assert catalog["contracts"]["domain_effect_execution"]["current"] == "domain-effect-execution-v3"
    assert catalog["contracts"]["institutional_lineage"]["current"] == "institutional-lineage-v1"
    assert catalog["contracts"]["ontology_version_history"]["current"] == "ontology-version-history-v1"
    assert catalog["contracts"]["experience_memory"]["current"] == "experience-memory-v2"
    assert catalog["contracts"]["strategy"]["current"] == "strategy-v2"
    assert catalog["contracts"]["decision_qualification"]["current"] == "decision-qualification-v1"
    assert catalog["contracts"]["authorization_revocation"]["current"] == "authorization-revocation-v1"
    assert catalog["contracts"]["strategy_assessment"]["current"] == "strategy-assessment-v2"


def test_contract_descriptor_rejects_unknown_contract() -> None:
    assert contract_descriptor("capability_invocation")["current"] == "capability-invocation-v6"
    try:
        contract_descriptor("not-real")
    except KeyError as exc:
        assert "unknown World Runtime contract" in str(exc)
    else:
        raise AssertionError("unknown contract must fail closed")


def test_contract_catalog_has_no_predecessor_owner() -> None:
    rendered = repr(contract_catalog())
    assert "agent-kernel/contracts" not in rendered
    assert "meta-controller" not in rendered


def test_domain_protocol_has_canonical_schemas_and_vectors() -> None:
    assignment_schema = contract_schema("domain_assignment")
    report_schema = contract_schema("domain_report")
    assert assignment_schema["title"] == "DomainAssignment v3"
    assert assignment_schema["$id"].endswith("domain-assignment-v3.schema.json")
    assert report_schema["title"] == "DomainReport v3"
    assert "basis_refs" in report_schema["properties"]
    assert report_schema["properties"]["evidence_refs"]["items"]["$ref"].endswith(
        "/evidenceRef"
    )

    vectors = domain_conformance_vectors()
    assert vectors["runtime_protocol"] == "4.0"
    assert vectors["contracts"]["domain_assignment"] == "domain-assignment-v3"
    assert vectors["contracts"]["domain_report"] == "domain-report-v3"
    assert {
        item["id"] for item in vectors["vectors"]
    } >= {
        "report-id-required",
        "outcome-candidate-evidence-is-typed",
        "outcome-candidate-outcome-is-namespaced",
        "rejected-only-from-offered",
        "completion-requires-active",
    }
