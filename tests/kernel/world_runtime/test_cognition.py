from semantic_language import Claim, Evidence, Unknown

from world_runtime import (
    BeliefVerdict,
    InvestigationBudget,
    InvestigationCandidate,
    InvestigationClosureReadiness,
    EvaluatorKind,
    WorldRuntime,
)


def test_cognition_controls_search_and_reopen_without_minting_work():
    rt = WorldRuntime.sqlite()
    claim = Claim(id="claim:1", subject="incident", proposition="cache caused errors")
    evidence = Evidence(id="e:1", subject="incident", source="metrics", content={"hit_rate": 0.2})
    unknown = Unknown(id="u:1", subject="incident", question="did saturation precede errors?")
    rt.epistemics.record_claim(claim)
    rt.epistemics.record_evidence(evidence)
    rt.epistemics.record_unknown(unknown)
    episode = rt.cognition.open_episode("incident")
    assert (
        rt.cognition.closure_readiness(subject="incident", material_claim_ids=(claim.id,))
        is InvestigationClosureReadiness.NOT_READY
    )
    selected = rt.cognition.select_candidate(
        [
            InvestigationCandidate("c:cheap", "ordered metrics", 0.8, 1.0),
            InvestigationCandidate("c:expensive", "replay", 0.9, 10.0),
        ],
        InvestigationBudget(max_actions=1, max_cost=2.0),
    )
    assert selected and selected.id == "c:cheap"
    rt.epistemics.resolve_unknown(unknown.id, basis_refs=(evidence.id,))
    rt.epistemics.assess(
        claim=claim,
        evidence=evidence,
        verdict=BeliefVerdict.SUPPORTED,
        confidence=0.8,
        calibration_ref="calibration:test-fixture-v1",
        rationale="ordered observation",
        assessed_by="verifier",
        evaluator_kind=EvaluatorKind.DOMAIN_VERIFIER,
    )
    rt.cognition.close_episode(episode.id, temporary=True, basis_refs=(evidence.id,))
    rt.cognition.reopen(episode.id, reason="contradiction", basis_refs=("e:2",))
    rt.cognition.revise_representation(
        episode.id,
        new_frame={"family": "dependency"},
        reason="old frame failed",
    )
    assert rt.ledger.project_get("execution.work", episode.id) is None