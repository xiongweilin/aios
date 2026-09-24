from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from semantic_language import Decision, Mandate, Responsibility, SemanticKind, SemanticRef

from world_runtime import WorldRuntime


PRINCIPAL = "service:long-horizon"


def _evidence(identifier: str) -> tuple[SemanticRef, ...]:
    return (SemanticRef(SemanticKind.EVIDENCE, identifier),)


def _decision(
    runtime: WorldRuntime,
    identifier: str,
    *,
    target_ref: str,
    operation: str,
    selected: dict[str, object] | None = None,
) -> None:
    runtime.decisions.record(
        Decision(
            id=identifier,
            subject=target_ref,
            decided_by=PRINCIPAL,
            selected={
                "target_ref": target_ref,
                "operation": operation,
                **dict(selected or {}),
            },
            basis_refs=_evidence(f"evidence:{identifier}"),
        )
    )


def _build_long_horizon_state(runtime: WorldRuntime) -> str:
    runtime.responsibility.create(
        Responsibility(
            id="responsibility:parent",
            principal=PRINCIPAL,
            subject="Deliver the durable outcome",
        ),
        domain="coordination",
    )
    runtime.responsibility.create(
        Responsibility(
            id="responsibility:child",
            principal=PRINCIPAL,
            subject="Complete the required domain work",
        ),
        domain="development",
    )
    _decision(
        runtime,
        "decision:relate",
        target_ref="responsibility:parent",
        operation="relate-responsibility",
        selected={
            "target_responsibility_id": "responsibility:child",
            "relation": "requires",
        },
    )
    runtime.responsibility_graph.create(
        "responsibility:parent",
        "responsibility:child",
        relation="requires",
        decision_id="decision:relate",
        basis_refs=("evidence:dependency",),
        relation_id="responsibility-relation:parent-child",
    )

    runtime.governance.register_mandate(
        Mandate(
            id="mandate:strategy",
            principal=PRINCIPAL,
            scope={"subject": "company"},
            authority_ceiling={"action": "*", "resource": "*"},
        )
    )
    issue = runtime.portfolio.open_issue(
        issue_id="strategy-issue:long-horizon",
        subject="company",
        question="Which strategy should remain active under current evidence?",
        mandate_id="mandate:strategy",
        basis_refs=("evidence:strategy-issue",),
    )
    option = runtime.portfolio.record_option(
        issue.id,
        option_id="strategic-option:long-horizon",
        hypothesis={"path": "bounded-growth"},
        evaluation={"evidence": "sufficient", "uncertainty": "bounded"},
        basis_refs=("evidence:option",),
    )
    proposal = runtime.portfolio.propose_portfolio(
        issue.id,
        proposal_id="portfolio-proposal:long-horizon",
        option_ids=(option.id,),
        goal_refs=(),
        resource_budget={"cash": {"amount": 1000.0, "unit": "CNY"}},
        basis_refs=("evidence:portfolio-proposal",),
    )
    _decision(
        runtime,
        "decision:activate-portfolio",
        target_ref=proposal.id,
        operation="activate-portfolio",
    )
    runtime.portfolio.activate_portfolio(
        proposal.id,
        decision_id="decision:activate-portfolio",
        portfolio_id="portfolio:long-horizon",
    )

    dependency = runtime.qualification.register_dependency(
        dependency_id="qualification-dependency:policy",
        principal=PRINCIPAL,
        subject_ref="portfolio:long-horizon",
        dependency_ref="policy:risk",
        dependency_version="v1",
        assumption="risk policy remains compatible with the active portfolio",
        review_policy={"on_change": "revalidate"},
        basis_refs=("evidence:policy-v1",),
    )
    review = runtime.qualification.observe_dependency_change(
        principal=PRINCIPAL,
        dependency_ref="policy:risk",
        observed_version="v2",
        basis_refs=("evidence:policy-v2",),
        reason="risk policy changed",
    )[0]
    runtime.qualification.assess_review(
        review.id,
        assessment_id="revalidation-assessment:policy",
        disposition="revalidate",
        basis_refs=("evidence:review",),
        rationale="material policy change requires renewed evidence",
    )
    assert dependency.status == "active"
    return review.id


def _recompute_bundle(bundle: dict[str, object]) -> None:
    payload = {
        "bundle_version": bundle["bundle_version"],
        "events": bundle["events"],
        "projections": bundle["projections"],
    }
    manifest = bundle["manifest"]
    assert isinstance(manifest, dict)
    manifest["event_count"] = len(bundle["events"])  # type: ignore[arg-type]
    manifest["projection_count"] = len(bundle["projections"])  # type: ignore[arg-type]
    manifest["digest"] = "sha256:" + hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def test_long_horizon_agency_survives_restart_and_state_bundle_migration(
    tmp_path: Path,
) -> None:
    path = tmp_path / "agency.db"
    runtime = WorldRuntime.sqlite(path, runtime_id="runtime:long-horizon:first")
    review_id = _build_long_horizon_state(runtime)
    runtime.close()

    restarted = WorldRuntime.sqlite(path, runtime_id="runtime:long-horizon:restarted")
    try:
        edge = restarted.responsibility_graph.get(
            "responsibility-relation:parent-child"
        )
        assert edge.relation == "requires"
        assert edge.status == "active"

        portfolio = restarted.portfolio.get_portfolio("portfolio:long-horizon")
        assert portfolio.status == "active"
        assert portfolio.resource_budget["cash"].unit == "CNY"

        pending = restarted.qualification.pending_obligations(
            principal=PRINCIPAL,
        )
        assert len(pending) == 1
        assert pending[0].id == review_id
        assert pending[0].status == "assessed"
        assert pending[0].disposition == "revalidate"

        bundle = restarted.state_bundle.export()
        validation = restarted.state_bundle.validate(bundle)
        assert validation.valid is True

        migrated = WorldRuntime.sqlite(
            tmp_path / "migrated.db",
            runtime_id="runtime:long-horizon:migrated",
        )
        try:
            migrated.state_bundle.import_bundle(bundle)
            assert (
                migrated.responsibility_graph.get(
                    "responsibility-relation:parent-child"
                ).target_responsibility_id
                == "responsibility:child"
            )
            assert migrated.portfolio.get_portfolio(
                "portfolio:long-horizon"
            ).status == "active"
            migrated_review = migrated.qualification.get_obligation(review_id)
            assert migrated_review.status == "assessed"
            assert migrated_review.resolution_ref is None
        finally:
            migrated.close()
    finally:
        restarted.close()


def test_state_bundle_rejects_dangling_1_0_agency_graph(tmp_path: Path) -> None:
    runtime = WorldRuntime.sqlite(tmp_path / "source.db")
    review_id = _build_long_horizon_state(runtime)
    try:
        bundle = runtime.state_bundle.export()

        missing_child = copy.deepcopy(bundle)
        missing_child["projections"] = [
            row
            for row in missing_child["projections"]
            if not (
                row["namespace"] == "responsibility.current"
                and row["key"] == "responsibility:child"
            )
        ]
        _recompute_bundle(missing_child)
        validation = runtime.state_bundle.validate(missing_child)
        assert validation.valid is False
        assert any(
            "responsibility.relation/responsibility-relation:parent-child "
            "references missing responsibility.current/responsibility:child"
            in error
            for error in validation.errors
        )

        missing_issue = copy.deepcopy(bundle)
        missing_issue["projections"] = [
            row
            for row in missing_issue["projections"]
            if not (
                row["namespace"] == "strategy.issue"
                and row["key"] == "strategy-issue:long-horizon"
            )
        ]
        _recompute_bundle(missing_issue)
        validation = runtime.state_bundle.validate(missing_issue)
        assert validation.valid is False
        assert any(
            "references missing strategy.issue/strategy-issue:long-horizon"
            in error
            for error in validation.errors
        )

        missing_dependency = copy.deepcopy(bundle)
        missing_dependency["projections"] = [
            row
            for row in missing_dependency["projections"]
            if not (
                row["namespace"] == "qualification.dependency"
                and row["key"] == "qualification-dependency:policy"
            )
        ]
        _recompute_bundle(missing_dependency)
        validation = runtime.state_bundle.validate(missing_dependency)
        assert validation.valid is False
        assert any(
            f"qualification.review-obligation/{review_id} references missing "
            "qualification.dependency/qualification-dependency:policy"
            in error
            for error in validation.errors
        )
    finally:
        runtime.close()
