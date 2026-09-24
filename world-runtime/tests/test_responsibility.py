import pytest
from semantic_language import Decision, Responsibility, SemanticKind, SemanticRef

from world_runtime import WorldRuntime


def test_work_completion_does_not_discharge_responsibility():
    rt = WorldRuntime.sqlite()
    item = Responsibility(id="r:1", principal="controller", subject="onboard employee")
    rt.responsibility.create(item, domain="administrative")
    work = rt.execution.admit_work(responsibility_id="r:1", kind="onboarding", payload={})
    rt.execution.mark_work_complete(work.id, evidence_refs=("evidence:hris",))
    assert rt.responsibility.get("r:1").status == "active"
    rt.responsibility.assess("r:1", status="satisfied", basis_refs=("outcome:verified",))
    with pytest.raises(ValueError):
        rt.responsibility.discharge("r:1", decision_id="missing")
    decision = Decision(id="decision:discharge", subject="done", decided_by="admin", selected={
            "target_ref": "r:1",
            "operation": "discharge-responsibility",
            "to_status": "discharged",
        }, basis_refs=(SemanticRef(SemanticKind.EVIDENCE, "evidence:hris"),))
    rt.decisions.record(decision)
    rt.responsibility.discharge("r:1", decision_id=decision.id)
    assert rt.responsibility.get("r:1").status == "discharged"
