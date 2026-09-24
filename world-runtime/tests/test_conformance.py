import pytest

from world_runtime.conformance import (
    SUITE_VERSION,
    conformance_vectors,
    run_reference_conformance,
)


def test_public_conformance_vectors_are_versioned_and_cover_deletion_gates() -> None:
    suite = conformance_vectors()
    assert suite["suite_version"] == SUITE_VERSION
    ids = {item["id"] for item in suite["vectors"]}
    assert {
        "responsibility-terminal-assessment-requires-basis",
        "responsibility-discharge-requires-satisfied-and-decision",
        "authorization-requires-active-mandate-and-decision",
        "ambiguous-effect-never-blind-redispatches",
        "reconciliation-contract-drift-fails-closed",
        "runtime-state-survives-restart",
        "portable-state-rejects-dangling-graph",
        "decision-applicability-is-required",
        "identity-rebound-is-rejected",
        "expired-mandate-is-not-current",
        "expired-authorization-is-not-usable",
        "empty-authority-ceiling-delegates-no-effect",
        "discharged-responsibility-rejects-work",
        "discharged-responsibility-rejects-effect",
        "effectful-invocation-requires-work",
        "run-must-belong-to-work",
        "authorization-required-context-is-enforced",
        "effectful-invocation-requires-durable-identity",
        "effect-identity-rebound-is-rejected",
        "capability-request-unknown-field-rejected",
        "effect-identity-cannot-rebind-through-extension-field",
        "authority-bearing-http-requires-authentication",
        "claimed-principal-cannot-override-authenticated-identity",
        "revoked-delegation-cannot-act",
        "unattested-decision-cannot-be-adopted",
        "unattested-authorization-cannot-execute-over-http",
        "delegation-cannot-widen-authority",
        "revoked-credential-cannot-authenticate",
        "bounded-subdelegation-preserves-root-authority",
        "stable-work-identity-is-replayable",
        "domain-effect-requires-start-before-dispatch",
        "domain-effect-start-is-single-use",
        "ambiguous-domain-effect-blocks-redispatch",
        "domain-effect-result-identity-is-bound",
        "domain-effect-start-revalidates-current-authority",
        "projection-cas-cross-connection-single-winner",
        "run-lease-cross-runtime-single-owner",
        "domain-effect-start-cross-runtime-single-dispatch",
        "provider-attempt-cross-runtime-single-dispatch",
        "shared-authorization-distinct-runtime-effects-survive-contention",
        "shared-authorization-distinct-domain-starts-survive-contention",
        "institutional-lineage-rejects-historical-branch",
        "superseded-decision-is-not-currently-applicable",
        "ontology-version-change-requires-revision",
        "experience-applicability-requires-qualified-current-head",
        "superseded-mandate-cannot-qualify-current-authority",
        "goal-successor-requires-revision-required-and-explicit-decision",
        "revoked-decision-is-not-currently-applicable",
        "revoked-authorization-is-not-usable",
        "strategy-reassessment-requires-explicit-lineage",
        "responsibility-required-dependency-blocks-parent-satisfaction",
        "responsibility-hard-dependency-cycle-rejected",
        "strategic-portfolio-activation-requires-decision",
        "strategic-resource-budget-unit-is-bound",
        "qualification-change-creates-review-not-invalidation",
        "qualification-action-assessment-remains-pending",
        "state-export-requires-direct-root-principal",
        "sensitive-runtime-read-requires-authentication",
        "public-command-unknown-field-rejected",
        "delegated-transition-requires-operation-authority",
        "delegated-effect-use-respects-action-resource-ceiling",
        "terminal-work-rejects-fresh-run",
        "terminal-run-rejects-fresh-invocation-but-replay-survives",
        "provider-result-read-is-principal-actor-bound",
    } <= ids


@pytest.mark.asyncio
async def test_reference_runtime_passes_all_public_conformance_vectors() -> None:
    results = await run_reference_conformance()
    failures = [item for item in results if not item.passed]
    assert failures == []
