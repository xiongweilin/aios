"""Adversarial evidence-receipt tests for the STAGING-only policy cursor.

The independent verifier is a fixture, not a production evidence authority.
No provider writes or operational acceptance are exercised here.
"""
from __future__ import annotations

from dataclasses import replace

import pytest
from administrative_orchestrator.contingent_execution import (
    CaseBinding,
    ContingentPolicyCursor,
    ContingentPolicyViolation,
    EvidenceReceipt,
)

BIND = CaseBinding("case:fixture", 7, 12)
PLAN = {
    "kind": "probe", "name": "read.subject",
    "branches": {
        "eligible": {
            "kind": "effect", "name": "iam.disable",
            "next": {"kind": "done"},
        },
        "ineligible": {"kind": "done"},
    },
}
KNOWN = {"evidence:probe", "evidence:effect"}


def cursor(plan=PLAN, **changes):
    options = dict(
        authorize_effect=lambda _binding, name: name == "iam.disable",
        qualify_probe=lambda _binding, name: name == "read.subject",
        verify_receipt=lambda receipt: receipt.evidence_ref in KNOWN
        and receipt.source_ref == "independent:fixture",
        effect_identities={"iam.disable": "runtime-effect:immutable-42"},
    )
    options.update(changes)
    return ContingentPolicyCursor(plan, BIND, **options)


def probe_receipt(label="eligible"):
    return EvidenceReceipt(
        binding=BIND, kind="probe", step_name="read.subject",
        disposition=label, evidence_ref="evidence:probe",
        source_ref="independent:fixture",
    )


def effect_receipt():
    return EvidenceReceipt(
        binding=BIND, kind="effect", step_name="iam.disable",
        disposition="verified", evidence_ref="evidence:effect",
        source_ref="independent:fixture",
        effect_identity="runtime-effect:immutable-42",
    )


def test_verified_receipts_advance_but_do_not_dispatch_or_close_domain():
    item = cursor()
    assert item.next_step(BIND).name == "read.subject"
    item.observe_with_receipt(BIND, probe_name="read.subject", receipt=probe_receipt())
    assert item.next_step(BIND).name == "iam.disable"
    item.resolve_effect_with_receipt(
        BIND, effect_name="iam.disable", receipt=effect_receipt(),
    )
    assert item.next_step(BIND).kind == "done"
    assert "independent domain completion" in item.next_step(BIND).reason


def test_true_boolean_cannot_bypass_strict_probe_receipt():
    item = cursor()
    item.next_step(BIND)
    with pytest.raises(ContingentPolicyViolation, match="receipt required"):
        item.observe(BIND, probe_name="read.subject",
                     observed_label="eligible", independent_readback=True)
    assert item.next_step(BIND).kind == "blocked"


def test_true_boolean_cannot_bypass_strict_effect_receipt():
    item = cursor(plan={"kind": "effect", "name": "iam.disable", "next": {"kind": "done"}})
    item.next_step(BIND)
    with pytest.raises(ContingentPolicyViolation, match="receipt required"):
        item.resolve_effect(
            BIND, effect_name="iam.disable", result="verified", independent_readback=True,
        )
    assert item.next_step(BIND).kind == "blocked"


@pytest.mark.parametrize(
    "bad_receipt",
    [
        replace(probe_receipt(), binding=CaseBinding("case:other", 7, 12)),
        replace(probe_receipt(), binding=CaseBinding("case:fixture", 8, 12)),
        replace(probe_receipt(), step_name="read.other"),
        replace(probe_receipt(), evidence_ref="unverified:claimed"),
        replace(probe_receipt(), source_ref="agent:self-asserted"),
        replace(probe_receipt(), effect_identity="not-a-probe"),
    ],
)
def test_stale_wrong_source_or_unbound_probe_evidence_fails_closed(bad_receipt):
    item = cursor()
    item.next_step(BIND)
    with pytest.raises(ContingentPolicyViolation):
        item.observe_with_receipt(BIND, probe_name="read.subject", receipt=bad_receipt)
    assert item.next_step(BIND).kind == "blocked"


@pytest.mark.parametrize(
    "bad_receipt",
    [
        replace(effect_receipt(), effect_identity="another-effect"),
        replace(effect_receipt(), binding=CaseBinding("case:fixture", 7, 13)),
        replace(effect_receipt(), disposition="pending"),
        replace(effect_receipt(), evidence_ref="unverified:claimed"),
    ],
)
def test_effect_rebound_or_unverified_disposition_fails_closed(bad_receipt):
    item = cursor(plan={"kind": "effect", "name": "iam.disable", "next": {"kind": "done"}})
    item.next_step(BIND)
    with pytest.raises(ContingentPolicyViolation):
        item.resolve_effect_with_receipt(
            BIND, effect_name="iam.disable", receipt=bad_receipt,
        )
    assert item.next_step(BIND).kind == "blocked"


def test_receipt_fields_without_independent_verifier_are_not_evidence():
    item = cursor(verify_receipt=None)
    item.next_step(BIND)
    with pytest.raises(ContingentPolicyViolation, match="independent receipt"):
        item.observe_with_receipt(BIND, probe_name="read.subject", receipt=probe_receipt())


@pytest.mark.parametrize(
    "verifier",
    [
        lambda _receipt: "truthy-but-not-attested",
        lambda _receipt: (_ for _ in ()).throw(OSError("protected evidence unavailable")),
    ],
)
def test_malformed_or_unavailable_receipt_verifier_fails_closed(verifier):
    item = cursor(verify_receipt=verifier)
    item.next_step(BIND)
    with pytest.raises(ContingentPolicyViolation, match="receipt"):
        item.observe_with_receipt(
            BIND, probe_name="read.subject", receipt=probe_receipt(),
        )
    assert item.next_step(BIND).kind == "blocked"


def test_verified_but_unmodeled_observation_halts():
    item = cursor()
    item.next_step(BIND)
    with pytest.raises(ContingentPolicyViolation, match="unmodeled observation"):
        item.observe_with_receipt(
            BIND, probe_name="read.subject", receipt=probe_receipt("surprise"),
        )


@pytest.mark.parametrize(
    "gate",
    [
        lambda _binding, _name: "truthy-but-not-approved",
        lambda _binding, _name: (_ for _ in ()).throw(OSError("auth unavailable")),
    ],
)
def test_live_authorization_gate_requires_boolean_true(gate):
    item = cursor(
        plan={"kind": "effect", "name": "iam.disable", "next": {"kind": "done"}},
        authorize_effect=gate,
    )
    with pytest.raises(ContingentPolicyViolation, match="not authorized"):
        item.next_step(BIND)
    assert item.next_step(BIND).kind == "blocked"


@pytest.mark.parametrize(
    "gate",
    [
        lambda _binding, _name: "maybe",
        lambda _binding, _name: (_ for _ in ()).throw(OSError("probe unavailable")),
    ],
)
def test_probe_qualification_gate_requires_boolean_true(gate):
    item = cursor(qualify_probe=gate)
    with pytest.raises(ContingentPolicyViolation, match="untrusted"):
        item.next_step(BIND)
    assert item.next_step(BIND).kind == "blocked"


def test_strict_mode_will_not_stage_an_effect_with_no_durable_identity():
    item = cursor(
        plan={"kind": "effect", "name": "iam.disable", "next": {"kind": "done"}},
        effect_identities={},
    )
    with pytest.raises(ContingentPolicyViolation, match="durable identity"):
        item.next_step(BIND)
    assert item.next_step(BIND).kind == "blocked"


def test_repeated_probe_requires_fresh_protected_evidence_locator():
    # Two reads of the same named probe cannot reuse one evidence reference
    # merely because the case/version and observation label still match.
    plan = {
        "kind": "probe", "name": "read.subject",
        "branches": {
            "eligible": {
                "kind": "probe", "name": "read.subject",
                "branches": {
                    "eligible": {"kind": "done"},
                    "ineligible": {"kind": "done"},
                },
            },
            "ineligible": {"kind": "done"},
        },
    }
    first = probe_receipt("eligible")
    item = cursor(plan=plan)
    assert item.next_step(BIND).name == "read.subject"
    item.observe_with_receipt(BIND, probe_name="read.subject", receipt=first)
    assert item.next_step(BIND).name == "read.subject"
    with pytest.raises(ContingentPolicyViolation, match="already consumed"):
        item.observe_with_receipt(BIND, probe_name="read.subject", receipt=first)
    assert item.next_step(BIND).kind == "blocked"

    # A second *independently qualified* locator advances, but the mocked
    # verifier is not evidence of production readback independence.
    fresh = replace(first, evidence_ref="evidence:fresh")
    other = cursor(
        plan=plan, verify_receipt=lambda r: r.evidence_ref in {
            "evidence:probe", "evidence:fresh",
        } and r.source_ref == "independent:fixture",
    )
    other.next_step(BIND)
    other.observe_with_receipt(BIND, probe_name="read.subject", receipt=first)
    other.next_step(BIND)
    other.observe_with_receipt(BIND, probe_name="read.subject", receipt=fresh)
    assert other.next_step(BIND).kind == "done"


    # Retagging one immutable evidence locator with another accepted source
    # must not let it certify a second observation.
    alias = cursor(
        plan=plan, verify_receipt=lambda r: r.evidence_ref == "evidence:probe"
        and r.source_ref in {"independent:fixture", "independent:alias"},
    )
    alias.next_step(BIND)
    alias.observe_with_receipt(BIND, probe_name="read.subject", receipt=first)
    alias.next_step(BIND)
    with pytest.raises(ContingentPolicyViolation, match="already consumed"):
        alias.observe_with_receipt(
            BIND, probe_name="read.subject",
            receipt=replace(first, source_ref="independent:alias"),
        )


def test_unknown_effect_requires_effect_readback_not_subject_eligibility():
    # Qualifying an initial subject is not the same as reading back the
    # durable effect. The required meaning remains external to this fixture.
    plan = {
        "kind": "effect", "name": "iam.disable",
        "next": {
            "kind": "probe", "name": "readback.effect",
            "branches": {
                "settled": {"kind": "done"},
                "pending": {
                    "kind": "effect", "name": "iam.reconcile",
                    "next": {"kind": "done"},
                },
            },
        },
    }
    identities = {
        "iam.disable": "runtime-effect:immutable-42",
        "iam.reconcile": "runtime-effect:reconcile-43",
    }
    for label in ("settled", "pending"):
        item = cursor(
            plan=plan, effect_identities=identities,
            authorize_effect=lambda _b, name: name in identities,
            qualify_probe=lambda _b, name: name == "readback.effect",
        )
        assert item.next_step(BIND).name == "iam.disable"
        item.resolve_effect(
            BIND, effect_name="iam.disable", result="unknown",
            independent_readback=False,
        )
        assert item.next_step(BIND).name == "readback.effect"
        item.observe_with_receipt(
            BIND, probe_name="readback.effect",
            receipt=EvidenceReceipt(
                binding=BIND, kind="probe", step_name="readback.effect",
                disposition=label, evidence_ref="evidence:probe",
                source_ref="independent:fixture",
            ),
        )
        if label == "pending":
            assert item.next_step(BIND).name == "iam.reconcile"
            assert item.next_step(BIND).kind == "blocked"  # no blind repeat
        else:
            assert item.next_step(BIND).kind == "done"
