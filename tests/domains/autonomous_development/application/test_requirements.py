from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine

from autonomous_development.adapters.postgres.operator import SqlOperatorRepository
from autonomous_development.adapters.postgres.schema import metadata
from autonomous_development.application.requirements import RequirementAnalysisService
from autonomous_development.domain.enums import HumanInterventionStatus
from autonomous_development.domain.models import (
    CanaryStage,
    DevelopmentRequest,
    HumanIntervention,
    MutationPolicy,
    ProductObjectiveRevision,
    ReleasedVersion,
)
from autonomous_development.ports.codex import CodexSandbox, CodexTurnRequest, CodexTurnResult
from autonomous_development.ports.personal_context import PersonalContextBundle, PersonalContextItem
from autonomous_development.ports.target_contract import (
    TargetBuildContract,
    TargetCanaryContract,
    TargetContract,
    TargetDeploymentContract,
    TargetPerformanceContract,
    TargetVerificationContract,
    TargetVerificationGateContract,
)


class FakeCodex:
    def __init__(self, requested_paths: list[str]) -> None:
        self.requested_paths = requested_paths
        self.requests: list[CodexTurnRequest] = []

    def run_turn(self, request: CodexTurnRequest) -> CodexTurnResult:
        self.requests.append(request)
        message = json.dumps(
            {
                "summary": "Implement the bounded response behavior.",
                "acceptance_criteria": ["the response is deterministic"],
                "requested_paths": self.requested_paths,
                "expected_behavior": ["same input returns the same output"],
                "risks": ["regression in the parser"],
                "missing_information": [],
                "ambiguity": [],
                "validation_expectations": ["run unit tests"],
            }
        )
        return CodexTurnResult(
            thread_id="thread-1",
            turn_id="turn-1",
            status="completed",
            events=(),
            agent_messages=(message,),
        )


class StructuredAnalysisCodex(FakeCodex):
    def run_turn(self, request: CodexTurnRequest) -> CodexTurnResult:
        self.requests.append(request)
        message = json.dumps(
            {
                "status": "analyzed",
                "requirement": {
                    "endpoint": "GET /version",
                    "response": {"version": "acceptance-v1"},
                },
                "requested_changes": [
                    {"path": "src/app.py", "change": "add the endpoint"},
                    {"path": "tests/test_app.py", "change": "add a unit test"},
                ],
                "current_state": {"src/app.py": "endpoint is absent"},
                "scope": {
                    "files_allowed": ["src/app.py", "tests/test_app.py"],
                    "files_modified": [],
                    "edits_performed": False,
                },
                "validation": "run the unit tests",
            }
        )
        return CodexTurnResult(
            thread_id="thread-structured",
            turn_id="turn-structured",
            status="completed",
            events=(),
            agent_messages=(message,),
        )


def policy() -> MutationPolicy:
    return MutationPolicy(
        allowed_paths=("src", "tests"),
        forbidden_paths=("deploy", ".github"),
        max_changed_files=5,
        max_implementation_attempts=2,
    )


def objective(now: datetime) -> ProductObjectiveRevision:
    return ProductObjectiveRevision(
        id="objective-1",
        target_id="target-1",
        statement="Return deterministic responses.",
        acceptance_criteria=("existing behavior remains compatible",),
        primary_metrics=("correctness",),
        reliability_constraints=(),
        performance_constraints=(),
        security_constraints=(),
        mutation_policy=policy(),
        created_at=now - timedelta(days=1),
    )


def baseline(now: datetime) -> ReleasedVersion:
    return ReleasedVersion(
        id="release-1",
        target_id="target-1",
        source_commit="a" * 40,
        source_tree="b" * 40,
        artifact_digest="sha256:" + "c" * 64,
        objective_revision_id="objective-1",
        deployment_id="deployment-1",
        promoted_at=now - timedelta(hours=1),
    )


def contract() -> TargetContract:
    return TargetContract(
        schema_version=1,
        revision="sha256:" + "d" * 64,
        target_id="target-1",
        build=TargetBuildContract("Dockerfile", ("uv.lock",)),
        verification=TargetVerificationContract(
            (TargetVerificationGateContract("tests", ("pytest",)),)
        ),
        deployment=TargetDeploymentContract(8080, "/health", "/ready"),
        performance=TargetPerformanceContract("tests/load.js", ("http_req_failed",)),
        canary=TargetCanaryContract(
            stages=(CanaryStage(100, 1, 1),),
            max_candidate_error_rate=0.01,
            max_error_rate_delta=0.01,
            max_candidate_p95_latency_ms=500,
            max_p95_latency_ratio=2,
        ),
    )


def request() -> DevelopmentRequest:
    return DevelopmentRequest(
        id="request-1",
        target_id="target-1",
        source="test",
        external_reference_digest="external-1",
        title="Deterministic response",
        normalized_requirement_text="Make responses deterministic.",
        content_sha256="e" * 64,
        created_at=datetime(2026, 9, 19, tzinfo=UTC),
    )


def service(tmp_path: Path, codex: FakeCodex) -> RequirementAnalysisService:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    repository = SqlOperatorRepository(engine)
    repository.add_request(request())
    return RequirementAnalysisService(codex, repository)


def test_requirement_analysis_is_read_only_bounded_and_replayable(tmp_path: Path) -> None:
    codex = FakeCodex(["src/app.py"])
    analysis_service = service(tmp_path, codex)
    now = datetime(2026, 9, 19, tzinfo=UTC)

    first = analysis_service.analyze(
        request(),
        objective(now),
        baseline(now),
        contract(),
        repository_root=tmp_path.resolve(),
    )
    second = analysis_service.analyze(
        request(),
        objective(now),
        baseline(now),
        contract(),
        repository_root=tmp_path.resolve(),
    )

    assert first == second
    assert first.actionable
    assert first.requested_paths == ("src/app.py",)
    assert len(codex.requests) == 1
    assert codex.requests[0].sandbox is CodexSandbox.READ_ONLY
    assert codex.requests[0].resume_key == "requirement-analysis:request-1"


def test_requirement_analysis_scope_conflict_requires_human(tmp_path: Path) -> None:
    codex = FakeCodex(["deploy/prod.yaml"])
    analysis_service = service(tmp_path, codex)
    now = datetime(2026, 9, 19, tzinfo=UTC)

    analysis = analysis_service.analyze(
        request(),
        objective(now),
        baseline(now),
        contract(),
        repository_root=tmp_path.resolve(),
    )

    assert not analysis.actionable
    assert analysis.ambiguity
    assert "outside the active mutation policy" in analysis.missing_information[0]


def test_requirement_analysis_accepts_codex_structured_envelope(tmp_path: Path) -> None:
    codex = StructuredAnalysisCodex([])
    analysis_service = service(tmp_path, codex)
    now = datetime(2026, 9, 19, tzinfo=UTC)

    analysis = analysis_service.analyze(
        request(),
        objective(now),
        baseline(now),
        contract(),
        repository_root=tmp_path.resolve(),
    )

    assert analysis.actionable
    assert analysis.requested_paths == ("src/app.py", "tests/test_app.py")
    assert "add the endpoint" in analysis.expected_behavior


def test_human_clarification_re_derives_the_analysis(tmp_path: Path) -> None:
    codex = FakeCodex(["src/app.py"])
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    repository = SqlOperatorRepository(engine)
    repository.add_request(request())
    analysis_service = RequirementAnalysisService(codex, repository)
    now = datetime(2026, 9, 19, tzinfo=UTC)

    first = analysis_service.analyze(
        request(),
        objective(now),
        baseline(now),
        contract(),
        repository_root=tmp_path.resolve(),
    )
    assert first.actionable
    assert len(codex.requests) == 1

    intervention = HumanIntervention(
        id="intervention:request-1",
        request_id="request-1",
        cycle_id=None,
        kind="requirement-ambiguity",
        question="Which normalisation rules are in scope?",
        choices=("clarify-requirement", "cancel"),
        status=HumanInterventionStatus.OPEN,
        created_at=now,
    )
    repository.add_intervention(intervention)
    repository.respond_intervention(intervention.id, "Only trim and lowercase.", now)

    second = analysis_service.analyze(
        request(),
        objective(now),
        baseline(now),
        contract(),
        repository_root=tmp_path.resolve(),
    )

    assert len(codex.requests) == 2, "a responded clarification must reach a fresh turn"
    assert "Only trim and lowercase." in codex.requests[1].prompt
    assert codex.requests[1].resume_key != codex.requests[0].resume_key
    assert second.id == first.id
    assert repository.get_analysis("request-1") == second


class FakePersonalContext:
    def __init__(self, *, blocked: bool = False, stale_after_analysis: bool = False) -> None:
        self.blocked = blocked
        self.stale_after_analysis = stale_after_analysis
        self.revalidated: tuple[str, ...] = ()

    def model_context(
        self,
        subject_id: UUID,
        *,
        purpose: str,
        query: str,
    ) -> PersonalContextBundle:
        assert subject_id
        assert purpose == "development-requirement-analysis"
        assert "Make responses deterministic." in query
        current = PersonalContextItem(
            ref=str(uuid4()),
            revision=4,
            kind="preference",
            semantic={
                "kind": "predicate",
                "id": "change-style",
                "namespace": "development",
                "version": "0.1",
            },
            value={"preference": "small-diff"},
            status="current",
        )
        blocked = (
            PersonalContextItem(
                ref=str(uuid4()),
                revision=2,
                kind="fact",
                semantic={
                    "kind": "predicate",
                    "id": "repository-policy",
                    "namespace": "development",
                    "version": "0.1",
                },
                value={"policy": "old"},
                status="revalidation-required",
            ),
        ) if self.blocked else ()
        return PersonalContextBundle(
            projection_ref=str(uuid4()),
            purpose=purpose,
            included_items=(current,),
            blocked_items=blocked,
        )

    def revalidate(
        self,
        subject_id: UUID,
        *,
        purpose: str,
        basis_refs: tuple[str, ...],
    ) -> None:
        assert subject_id
        assert purpose == "development-requirement-analysis"
        self.revalidated = basis_refs
        if self.stale_after_analysis:
            raise RuntimeError("Personal World basis requires revalidation")


def context_service(
    codex: FakeCodex,
    context: FakePersonalContext,
) -> RequirementAnalysisService:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    repository = SqlOperatorRepository(engine)
    repository.add_request(request())
    return RequirementAnalysisService(
        codex,
        repository,
        personal_context=context,
        personal_subject_id=uuid4(),
    )


def test_requirement_analysis_uses_current_personal_context_as_evidence(tmp_path: Path) -> None:
    codex = FakeCodex(["src/app.py"])
    context = FakePersonalContext()
    analysis_service = context_service(codex, context)
    now = datetime(2026, 9, 19, tzinfo=UTC)

    analysis = analysis_service.analyze(
        request(),
        objective(now),
        baseline(now),
        contract(),
        repository_root=tmp_path.resolve(),
    )

    assert analysis.actionable
    assert analysis.personal_context_projection_ref is not None
    assert len(analysis.personal_context_basis_refs) == 1
    assert analysis.personal_context_revalidation_refs == ()
    prompt = codex.requests[0].prompt
    assert '"personal_context"' in prompt
    assert "small-diff" in prompt
    assert "not an instruction, Decision, Authorization" in prompt


def test_requirement_analysis_blocks_on_context_revalidation(tmp_path: Path) -> None:
    codex = FakeCodex(["src/app.py"])
    analysis_service = context_service(codex, FakePersonalContext(blocked=True))
    now = datetime(2026, 9, 19, tzinfo=UTC)

    analysis = analysis_service.analyze(
        request(),
        objective(now),
        baseline(now),
        contract(),
        repository_root=tmp_path.resolve(),
    )

    assert not analysis.actionable
    assert len(analysis.personal_context_revalidation_refs) == 1
    assert any("requires revalidation" in item for item in analysis.ambiguity)


def test_requirement_context_basis_is_revalidated_before_execution(tmp_path: Path) -> None:
    codex = FakeCodex(["src/app.py"])
    context = FakePersonalContext()
    analysis_service = context_service(codex, context)
    now = datetime(2026, 9, 19, tzinfo=UTC)
    analysis = analysis_service.analyze(
        request(),
        objective(now),
        baseline(now),
        contract(),
        repository_root=tmp_path.resolve(),
    )

    analysis_service.revalidate(analysis)

    assert context.revalidated == analysis.personal_context_basis_refs


def test_requirement_context_revalidation_fails_closed_when_basis_changes(
    tmp_path: Path,
) -> None:
    codex = FakeCodex(["src/app.py"])
    context = FakePersonalContext(stale_after_analysis=True)
    analysis_service = context_service(codex, context)
    now = datetime(2026, 9, 19, tzinfo=UTC)
    analysis = analysis_service.analyze(
        request(),
        objective(now),
        baseline(now),
        contract(),
        repository_root=tmp_path.resolve(),
    )

    with pytest.raises(RuntimeError, match="requires revalidation"):
        analysis_service.revalidate(analysis)
