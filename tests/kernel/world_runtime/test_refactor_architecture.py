from semantic_language import SemanticKind
import semantic_language

from world_runtime import conformance
from world_runtime.decisions import Decision
from world_runtime.epistemics import Claim, EpistemicLedger
from world_runtime.execution import CapabilityRequest, ExecutionService
from world_runtime.governance import Mandate
from world_runtime.lineage import Revision
from world_runtime.qualification import QualificationService
from world_runtime.responsibility import Responsibility
from world_runtime.strategy import Goal


def test_semantic_kernel_exports_roles_not_payload_schemas() -> None:
    assert {item.value for item in SemanticKind} == {
        "claim",
        "evidence",
        "unknown",
        "decision",
        "authorization",
        "effect",
        "outcome",
        "responsibility",
        "revision",
    }
    forbidden_payload_exports = {
        "Claim",
        "Evidence",
        "Unknown",
        "Decision",
        "Authorization",
        "Responsibility",
        "Revision",
        "Goal",
        "Mandate",
        "Conflict",
        "Acceptance",
        "Capability",
        "Work",
        "Run",
    }
    assert forbidden_payload_exports.isdisjoint(vars(semantic_language))


def test_payload_classes_live_with_their_owner() -> None:
    assert Claim.__module__ == "world_runtime.epistemic_types"
    assert CapabilityRequest.__module__ == "world_runtime.execution_types"
    assert Decision.__module__ == "world_runtime.decisions"
    assert Mandate.__module__ == "world_runtime.governance"
    assert Responsibility.__module__ == "world_runtime.responsibility"
    assert Goal.__module__ == "world_runtime.strategy"
    assert Revision.__module__ == "world_runtime.lineage"
    assert EpistemicLedger.__module__ == "world_runtime.epistemics"
    assert ExecutionService.__module__ == "world_runtime.execution"


def test_conformance_runner_delegates_checks_to_partition_modules() -> None:
    vector_ids = {str(item["id"]) for item in conformance.conformance_vectors()["vectors"]}
    assert set(conformance.CHECKS) == vector_ids
    assert all(
        callback.__module__.startswith("world_runtime.conformance_")
        and callback.__module__ != "world_runtime.conformance"
        for callback in conformance.CHECKS.values()
    )


def test_compact_qualification_has_no_legacy_three_object_api() -> None:
    legacy_api = {
        "register_dependency",
        "get_dependency",
        "get_obligation",
        "pending_obligations",
        "supersede_dependency_after_review",
    }
    assert legacy_api.isdisjoint(vars(QualificationService))
