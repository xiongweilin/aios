"""Model-relative policy cursor: no production dispatch, authority or readback forged."""
from __future__ import annotations

import pytest
from administrative_orchestrator.contingent_execution import (
    CaseBinding,
    ContingentPolicyCursor,
    ContingentPolicyViolation,
    ProposedStep,
)

BIND = CaseBinding("case:1", 2, 4)
PLAN = {
    "kind": "probe", "name": "independent-subject-check",
    "branches": {
        "ok": {"kind": "effect", "name": "iam.disable",
               "next": {"kind": "done"}},
        "absent": {"kind": "done"},
    },
}


def cursor(*, authorize=True, qualify=True, policy=PLAN):
    return ContingentPolicyCursor(
        policy, BIND,
        authorize_effect=lambda current, effect: bool(authorize) and effect == "iam.disable",
        qualify_probe=lambda current, source: bool(qualify)
        and source == "independent-subject-check",
    )


def test_qualified_observation_then_separately_authorized_and_verified_effect():
    item = cursor()
    assert item.next_step(BIND) == ProposedStep("probe", "independent-subject-check")
    item.observe(BIND, probe_name="independent-subject-check",
                 observed_label="ok", independent_readback=True)
    assert item.next_step(BIND) == ProposedStep("effect", "iam.disable")
    item.resolve_effect(BIND, effect_name="iam.disable",
                        result="verified", independent_readback=True)
    assert item.next_step(BIND).kind == "done"
    assert "independent domain completion" in item.next_step(BIND).reason


def test_incomplete_policy_cannot_be_used_as_permission():
    item = cursor(authorize=False)
    item.next_step(BIND)
    item.observe(BIND, probe_name="independent-subject-check",
                 observed_label="ok", independent_readback=True)
    with pytest.raises(ContingentPolicyViolation, match="not authorized"):
        item.next_step(BIND)
    assert item.next_step(BIND).kind == "blocked"


def test_effect_unknown_stays_blocked_and_cannot_be_replayed():
    item = cursor(policy={
        "kind": "effect", "name": "iam.disable",
        "next": {"kind": "done"},
    })
    assert item.next_step(BIND).kind == "effect"
    with pytest.raises(ContingentPolicyViolation, match="reconciliation"):
        item.resolve_effect(BIND, effect_name="iam.disable",
                            result="unknown", independent_readback=False)
    assert item.next_step(BIND).kind == "blocked"


def test_stale_authority_epoch_invalidates_policy():
    item = cursor()
    with pytest.raises(ContingentPolicyViolation, match="recompile"):
        item.next_step(CaseBinding("case:1", 3, 4))
    assert item.next_step(BIND).kind == "blocked"


def test_missing_or_forged_branch_fails_closed():
    item = cursor()
    item.next_step(BIND)
    with pytest.raises(ContingentPolicyViolation, match="unmodeled observation"):
        item.observe(BIND, probe_name="independent-subject-check",
                     observed_label="unlisted", independent_readback=True)
    assert item.next_step(BIND).kind == "blocked"


def test_unqualified_readback_cannot_choose_a_branch():
    item = cursor()
    item.next_step(BIND)
    with pytest.raises(ContingentPolicyViolation, match="unqualified"):
        item.observe(BIND, probe_name="independent-subject-check",
                     observed_label="ok", independent_readback=False)
    item = cursor(qualify=False)
    with pytest.raises(ContingentPolicyViolation, match="untrusted"):
        item.next_step(BIND)


def test_bad_terminal_or_unsupported_step_does_not_create_effect():
    item = cursor(policy={"kind": "done"})
    assert item.next_step(BIND).kind == "done"  # never Administrative completion
    item = cursor(policy={"kind": "invent-capability", "name": "iam.disable"})
    with pytest.raises(ContingentPolicyViolation, match="unrecognized"):
        item.next_step(BIND)


def test_direct_effect_without_independent_verification_stops():
    item = cursor(policy={"kind": "effect", "name": "iam.disable",
                          "next": {"kind": "done"}})
    item.next_step(BIND)
    with pytest.raises(ContingentPolicyViolation, match="reconciliation"):
        item.resolve_effect(BIND, effect_name="iam.disable",
                            result="verified", independent_readback=False)
