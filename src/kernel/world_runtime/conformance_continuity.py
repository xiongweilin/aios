from __future__ import annotations

import json

import tempfile
from pathlib import Path
from semantic_language import SemanticKind
from semantic_language import SemanticRef
from .decisions import Decision
from .governance import Mandate
from .lineage import Revision
from .strategy import Goal
from .ontology import SemanticTypeDefinition
from .runtime import WorldRuntime
from .conformance_support import _responsibility

def _restart() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "runtime.db"
        runtime = WorldRuntime.sqlite(path)
        _responsibility(runtime, "responsibility:restart")
        work = runtime.execution.admit_work(
            responsibility_id="responsibility:restart",
            kind="restart",
            payload={},
        )
        run = runtime.start_run(work.id, workflow_id="restart")
        runtime.close()

        reopened = WorldRuntime.sqlite(path)
        if reopened.responsibility.get("responsibility:restart").principal != "service:conformance":
            raise AssertionError("responsibility identity was not durable")
        runs = reopened.list_runs(work.id)
        if len(runs) != 1 or runs[0].id != run.id:
            raise AssertionError("run identity was not durable")
        reopened.close()

def _dangling_bundle() -> None:
    runtime = WorldRuntime.sqlite()
    _responsibility(runtime)
    work = runtime.execution.admit_work(
        responsibility_id="responsibility:conformance",
        kind="bundle",
        payload={},
    )
    bundle = runtime.state_bundle.export()
    bundle["projections"] = [
        row
        for row in bundle["projections"]
        if row["namespace"] != "responsibility.current"
    ]
    payload = {
        "bundle_version": bundle["bundle_version"],
        "events": bundle["events"],
        "projections": bundle["projections"],
    }
    import hashlib

    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    bundle["manifest"]["projection_count"] = len(bundle["projections"])
    bundle["manifest"]["digest"] = "sha256:" + hashlib.sha256(raw).hexdigest()
    validation = runtime.state_bundle.validate(bundle)
    if validation.valid:
        raise AssertionError(f"dangling Work graph accepted: {work.id}")

def _institutional_revision(
    identifier: str,
    *,
    target: SemanticRef,
    previous: SemanticRef,
) -> Revision:
    return Revision(
        id=identifier,
        target_ref=target,
        supersedes_ref=previous,
        reason="conformance successor",
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, f"evidence:{identifier}"),),
    )

def _institutional_lineage_rejects_branch() -> None:
    runtime = WorldRuntime.sqlite()
    root = SemanticRef(SemanticKind.DECISION, "decision:lineage-root")
    current = SemanticRef(SemanticKind.DECISION, "decision:lineage-current")
    branch = SemanticRef(SemanticKind.DECISION, "decision:lineage-branch")
    runtime.lineage.record(
        _institutional_revision(
            "revision:lineage-current",
            target=current,
            previous=root,
        )
    )
    try:
        runtime.lineage.record(
            _institutional_revision(
                "revision:lineage-branch",
                target=branch,
                previous=root,
            )
        )
    except ValueError:
        if runtime.lineage.resolve_current(root) != current:
            raise AssertionError("lineage branch rejection changed current head")
        return
    raise AssertionError("historical lineage root admitted a second branch")

def _superseded_decision_not_current() -> None:
    runtime = WorldRuntime.sqlite()
    old = Decision(
        id="decision:institutional-old",
        subject="resource:institutional",
        decided_by="owner",
        selected={
            "target_ref": "resource:institutional",
            "operation": "authorize-effect",
            "action": "deploy",
        },
        basis_refs=(
            SemanticRef(SemanticKind.EVIDENCE, "evidence:decision-old"),
        ),
    )
    new = Decision(
        id="decision:institutional-new",
        subject="resource:institutional",
        decided_by="owner",
        selected={
            "target_ref": "resource:institutional",
            "operation": "authorize-effect",
            "action": "deploy",
            "policy_version": "2",
        },
        basis_refs=(
            SemanticRef(SemanticKind.EVIDENCE, "evidence:decision-new"),
        ),
    )
    runtime.decisions.record(old)
    runtime.decisions.supersede(
        old.id,
        new,
        _institutional_revision(
            "revision:decision-current",
            target=new.ref,
            previous=old.ref,
        ),
    )
    if runtime.decisions.get(old.id)["id"] != old.id:
        raise AssertionError("historical Decision was not preserved")
    if runtime.decisions.get_current(old.id)["id"] != new.id:
        raise AssertionError("Decision lineage did not resolve successor")
    try:
        runtime.decisions.assert_current(old.id)
    except ValueError:
        return
    raise AssertionError("superseded Decision remained currently applicable")

def _ontology_version_requires_revision() -> None:
    runtime = WorldRuntime.sqlite()
    first = SemanticTypeDefinition(
        name="conformance-type",
        owner="domain:conformance",
        version="1",
        description="first",
    )
    second = SemanticTypeDefinition(
        name="conformance-type",
        owner="domain:conformance",
        version="2",
        description="second",
    )
    runtime.ontology.register(first)
    try:
        runtime.ontology.register(second)
    except ValueError:
        pass
    else:
        raise AssertionError("ontology version changed without explicit Revision")

    runtime.ontology.supersede(
        second,
        _institutional_revision(
            "revision:ontology-version",
            target=runtime.ontology.definition_ref(second),
            previous=runtime.ontology.definition_ref(first),
        ),
    )
    if runtime.ontology.resolve("conformance-type") != second:
        raise AssertionError("ontology current version did not advance")
    if runtime.ontology.resolve_version("conformance-type", "1") != first:
        raise AssertionError("ontology historical version was lost")

def _experience_current_applicability() -> None:
    runtime = WorldRuntime.sqlite()
    old = runtime.memory.propose(
        scope={"service": "conformance"},
        lesson={"mode": "old"},
        basis_refs=("evidence:experience-old",),
    )
    runtime.memory.qualify(old.id, assessment_refs=("assessment:old",))
    runtime.memory.invalidate(
        old.id,
        reason="environment changed",
        basis_refs=("evidence:experience-invalidated",),
    )
    if runtime.memory.is_applicable(old.id):
        raise AssertionError("invalidated Experience remained applicable")
    runtime.memory.reopen(
        old.id,
        reason="new evaluation",
        basis_refs=("evidence:experience-reopen",),
    )
    runtime.memory.qualify(old.id, assessment_refs=("assessment:old-requalified",))

    successor = runtime.memory.propose(
        scope={"service": "conformance"},
        lesson={"mode": "new"},
        basis_refs=("evidence:experience-new",),
    )
    runtime.memory.qualify(successor.id, assessment_refs=("assessment:new",))
    runtime.memory.supersede(
        old.id,
        successor.id,
        _institutional_revision(
            "revision:experience",
            target=runtime.memory.experience_ref(successor.id),
            previous=runtime.memory.experience_ref(old.id),
        ),
    )
    if runtime.memory.is_applicable(old.id):
        raise AssertionError("superseded Experience remained applicable")
    if not runtime.memory.is_applicable(successor.id):
        raise AssertionError("qualified current Experience is not applicable")

def _superseded_mandate_not_current() -> None:
    runtime = WorldRuntime.sqlite()
    old = Mandate(
        id="mandate:institutional-old",
        principal="owner",
        scope={"resource": "resource:institutional"},
        authority_ceiling={
            "action": "deploy",
            "resource": "resource:institutional",
        },
    )
    runtime.governance.register_mandate(old)
    decision = Decision(
        id="decision:institutional-authorize",
        subject="resource:institutional",
        decided_by="owner",
        selected={
            "target_ref": "resource:institutional",
            "operation": "authorize-effect",
            "action": "deploy",
        },
        basis_refs=(
            SemanticRef(SemanticKind.EVIDENCE, "evidence:institutional-authorize"),
        ),
    )
    runtime.decisions.record(decision)
    authorization = runtime.governance.issue_authorization(
        authorization_id="authorization:institutional-old",
        principal="owner",
        action="deploy",
        resource="resource:institutional",
        mandate_id=old.id,
        decision_id=decision.id,
    )
    successor = Mandate(
        id="mandate:institutional-new",
        principal="owner",
        scope={"resource": "resource:institutional"},
        authority_ceiling={
            "actions": ["deploy", "rollback"],
            "resource": "resource:institutional",
        },
    )
    runtime.governance.supersede_mandate(
        old.id,
        successor,
        _institutional_revision(
            "revision:mandate-current",
            target=successor.ref,
            previous=old.ref,
        ),
    )
    historical = runtime.ledger.project_get(
        "governance.authorization",
        authorization.id,
    )
    if historical is None or historical[0].get("mandate_id") != old.id:
        raise AssertionError("historical Authorization was not preserved")
    try:
        runtime.governance.assert_usable(
            authorization.id,
            principal="owner",
            action="deploy",
            resource="resource:institutional",
        )
    except PermissionError:
        return
    raise AssertionError("Authorization through superseded Mandate remained current")

def _goal_successor_gate() -> None:
    runtime = WorldRuntime.sqlite()
    mandate = Mandate(id="mandate:goal-lineage", principal="owner")
    runtime.governance.register_mandate(mandate)
    old = Goal(
        id="goal:institutional-old",
        subject="service",
        desired_state={"state": "old"},
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:goal-old"),),
    )
    admit_old = Decision(
        id="decision:goal-old-admit",
        subject="service",
        decided_by="owner",
        selected={"target_ref": old.id, "operation": "admit-goal"},
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:goal-old-admit"),),
    )
    runtime.decisions.record(admit_old)
    runtime.strategy.register_goal(
        old,
        mandate_id=mandate.id,
        decision_id=admit_old.id,
    )
    successor = Goal(
        id="goal:institutional-new",
        subject="service",
        desired_state={"state": "new"},
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:goal-new"),),
    )
    admit_new = Decision(
        id="decision:goal-new-admit",
        subject="service",
        decided_by="owner",
        selected={
            "target_ref": successor.id,
            "operation": "admit-goal",
            "supersedes_goal_id": old.id,
        },
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:goal-new-admit"),),
    )
    runtime.decisions.record(admit_new)
    revision = _institutional_revision(
        "revision:goal-successor",
        target=successor.ref,
        previous=old.ref,
    )
    try:
        runtime.strategy.supersede_goal(
            old.id,
            successor,
            revision,
            mandate_id=mandate.id,
            decision_id=admit_new.id,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("active Goal was superseded before revision-required state")

    assessment = runtime.strategy.assess_goal(
        old.id,
        disposition="revise",
        basis_refs=("evidence:goal-revise",),
    )
    require_revision = Decision(
        id="decision:goal-revision-required",
        subject="service",
        decided_by="owner",
        selected={
            "target_ref": old.id,
            "operation": "transition-goal",
            "to_status": "revision-required",
            "assessment_id": assessment.id,
        },
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:goal-revise"),),
    )
    runtime.decisions.record(require_revision)
    runtime.strategy.transition_goal(
        old.id,
        to_status="revision-required",
        assessment_id=assessment.id,
        decision_id=require_revision.id,
        basis_refs=("evidence:goal-revise",),
    )
    runtime.strategy.supersede_goal(
        old.id,
        successor,
        revision,
        mandate_id=mandate.id,
        decision_id=admit_new.id,
    )
    if runtime.strategy.get_current_goal(old.id)["id"] != successor.id:
        raise AssertionError("Goal successor did not become current")
    if runtime.strategy.get_goal(old.id)["status"] != "retired":
        raise AssertionError("superseded Goal did not become historical/retired")

def _revoked_decision_not_current() -> None:
    runtime = WorldRuntime.sqlite()
    decision = Decision(
        id="decision:revoked-current",
        subject="resource:revoked",
        decided_by="owner",
        selected={
            "target_ref": "resource:revoked",
            "operation": "authorize-effect",
            "action": "deploy",
        },
        basis_refs=(
            SemanticRef(SemanticKind.EVIDENCE, "evidence:decision-revocable"),
        ),
    )
    runtime.decisions.record(decision)
    runtime.decisions.revoke(
        decision.id,
        reason="institutional policy withdrawn",
        basis_refs=("evidence:decision-revoked",),
    )
    if runtime.decisions.get(decision.id)["id"] != decision.id:
        raise AssertionError("revoked Decision history was lost")
    try:
        runtime.decisions.assert_current(decision.id)
    except ValueError:
        events = runtime.ledger.events(stream=f"decision:{decision.id}")
        if not events or events[-1].kind != "decision.revoked":
            raise AssertionError("Decision revocation history was not durable")
        return
    raise AssertionError("revoked Decision remained currently applicable")

def _revoked_authorization_not_usable() -> None:
    runtime = WorldRuntime.sqlite()
    mandate = Mandate(
        id="mandate:authorization-revocation",
        principal="owner",
        scope={"resource": "resource:authorization-revocation"},
        authority_ceiling={
            "action": "deploy",
            "resource": "resource:authorization-revocation",
        },
    )
    runtime.governance.register_mandate(mandate)
    decision = Decision(
        id="decision:authorization-revocation",
        subject="resource:authorization-revocation",
        decided_by="owner",
        selected={
            "target_ref": "resource:authorization-revocation",
            "operation": "authorize-effect",
            "action": "deploy",
        },
        basis_refs=(
            SemanticRef(SemanticKind.EVIDENCE, "evidence:authorization-revocation"),
        ),
    )
    runtime.decisions.record(decision)
    authorization = runtime.governance.issue_authorization(
        authorization_id="authorization:revocation",
        principal="owner",
        action="deploy",
        resource="resource:authorization-revocation",
        mandate_id=mandate.id,
        decision_id=decision.id,
    )
    runtime.governance.record_use(
        authorization.id,
        effect_request_id="request:before-revocation",
    )
    runtime.governance.revoke_authorization(
        authorization.id,
        reason="delegated authority ended",
        basis_refs=("evidence:authorization-ended",),
    )
    stored = runtime.ledger.project_get(
        "governance.authorization",
        authorization.id,
    )
    if stored is None or stored[0].get("uses") != 1:
        raise AssertionError("Authorization history was not preserved")
    try:
        runtime.governance.assert_usable(
            authorization.id,
            principal="owner",
            action="deploy",
            resource="resource:authorization-revocation",
        )
    except PermissionError:
        try:
            runtime.governance.record_use(
                authorization.id,
                effect_request_id="request:after-revocation",
            )
        except PermissionError:
            return
        raise AssertionError("revoked Authorization accepted a later use record")
    raise AssertionError("revoked Authorization remained usable")

def _strategy_reassessment_requires_lineage() -> None:
    runtime = WorldRuntime.sqlite()
    mandate = Mandate(id="mandate:strategy-reassessment", principal="owner")
    runtime.governance.register_mandate(mandate)
    goal = Goal(
        id="goal:strategy-reassessment",
        subject="service",
        desired_state={"state": "improve"},
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:goal-assessment"),),
    )
    admit = Decision(
        id="decision:strategy-reassessment-admit",
        subject="service",
        decided_by="owner",
        selected={"target_ref": goal.id, "operation": "admit-goal"},
        basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:goal-admit"),),
    )
    runtime.decisions.record(admit)
    runtime.strategy.register_goal(
        goal,
        mandate_id=mandate.id,
        decision_id=admit.id,
    )
    first = runtime.strategy.assess_goal(
        goal.id,
        disposition="continue",
        basis_refs=("evidence:assessment-first",),
    )
    try:
        runtime.strategy.assess_goal(
            goal.id,
            disposition="revise",
            basis_refs=("evidence:assessment-second",),
        )
    except ValueError:
        pass
    else:
        raise AssertionError("StrategyAssessment silently overwrote current assessment")

    second = runtime.strategy.assess_goal(
        goal.id,
        disposition="revise",
        basis_refs=("evidence:assessment-second",),
        supersedes_assessment_id=first.id,
        revision_reason="new evidence changes strategic disposition",
        revision_basis_refs=("evidence:assessment-second",),
    )
    if runtime.strategy.get_assessment(first.id).id != first.id:
        raise AssertionError("historical StrategyAssessment was lost")
    if runtime.strategy.get_current_assessment(first.id).id != second.id:
        raise AssertionError("StrategyAssessment lineage did not advance current head")
    if runtime.strategy.latest_assessment(goal.id).id != second.id:
        raise AssertionError("Goal latest StrategyAssessment did not advance")

CHECKS = {
    "runtime-state-survives-restart": _restart,
    "portable-state-rejects-dangling-graph": _dangling_bundle,
    "institutional-lineage-rejects-historical-branch": _institutional_lineage_rejects_branch,
    "superseded-decision-is-not-currently-applicable": _superseded_decision_not_current,
    "ontology-version-change-requires-revision": _ontology_version_requires_revision,
    "experience-applicability-requires-qualified-current-head": _experience_current_applicability,
    "superseded-mandate-cannot-qualify-current-authority": _superseded_mandate_not_current,
    "goal-successor-requires-revision-required-and-explicit-decision": _goal_successor_gate,
    "revoked-decision-is-not-currently-applicable": _revoked_decision_not_current,
    "revoked-authorization-is-not-usable": _revoked_authorization_not_usable,
    "strategy-reassessment-requires-explicit-lineage": _strategy_reassessment_requires_lineage,
}
