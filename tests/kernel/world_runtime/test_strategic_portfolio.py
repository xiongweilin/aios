import pytest
from semantic_language import Decision, Goal, Mandate, Responsibility, SemanticKind, SemanticRef

from world_runtime import WorldRuntime


def _evidence(identifier: str) -> SemanticRef:
    return SemanticRef(SemanticKind.EVIDENCE, identifier)


def _record_decision(
    runtime: WorldRuntime,
    identifier: str,
    *,
    target_ref: str,
    operation: str,
    **selected: object,
) -> Decision:
    decision = Decision(
        id=identifier,
        subject=target_ref,
        decided_by="owner",
        selected={"target_ref": target_ref, "operation": operation, **selected},
        basis_refs=(_evidence(f"evidence:{identifier}"),),
    )
    runtime.decisions.record(decision)
    return decision


def _setup(runtime: WorldRuntime) -> tuple[Mandate, Goal, Responsibility]:
    mandate = Mandate(
        id="mandate:strategy",
        principal="owner",
        authority_ceiling={"action": "*", "resource": "*"},
    )
    runtime.governance.register_mandate(mandate)
    goal = Goal(
        id="goal:growth",
        subject="company",
        desired_state={"revenue": "grow"},
        basis_refs=(_evidence("evidence:goal"),),
    )
    decision = _record_decision(
        runtime,
        "decision:goal",
        target_ref=goal.id,
        operation="admit-goal",
    )
    runtime.strategy.register_goal(goal, mandate_id=mandate.id, decision_id=decision.id)
    responsibility = Responsibility(
        id="responsibility:sales",
        principal="owner",
        subject="acquire customers",
        scope={"quarter": "Q4"},
        goal_refs=(goal.ref,),
    )
    runtime.responsibility.create(responsibility, domain="sales")
    return mandate, goal, responsibility


def test_portfolio_activation_is_explicit_decision_not_option_ranking() -> None:
    runtime = WorldRuntime.sqlite()
    mandate, goal, _ = _setup(runtime)
    issue = runtime.portfolio.open_issue(
        issue_id="strategy-issue:growth",
        subject="company",
        question="Which growth path should we fund?",
        mandate_id=mandate.id,
        basis_refs=("evidence:market",),
    )
    conservative = runtime.portfolio.record_option(
        issue.id,
        option_id="strategic-option:conservative",
        hypothesis={"channel": "existing"},
        evaluation={"value_case": "steady", "risk": "low"},
        basis_refs=("evidence:existing",),
    )
    aggressive = runtime.portfolio.record_option(
        issue.id,
        option_id="strategic-option:aggressive",
        hypothesis={"channel": "new"},
        evaluation={"value_case": "high-upside", "risk": "high"},
        basis_refs=("evidence:new",),
    )

    assert conservative.evaluation["risk"] == "low"
    assert aggressive.evaluation["risk"] == "high"

    proposal = runtime.portfolio.propose_portfolio(
        issue.id,
        proposal_id="portfolio-proposal:growth",
        option_ids=(aggressive.id,),
        goal_refs=(goal.id,),
        resource_budget={
            "cash": {"amount": 100.0, "unit": "CNY"},
            "hours": {"amount": 40.0, "unit": "hour"},
        },
        basis_refs=("evidence:portfolio",),
    )

    with pytest.raises(ValueError, match="required decision"):
        runtime.portfolio.activate_portfolio(
            proposal.id,
            decision_id="decision:missing",
        )

    decision = _record_decision(
        runtime,
        "decision:portfolio",
        target_ref=proposal.id,
        operation="activate-portfolio",
    )
    portfolio = runtime.portfolio.activate_portfolio(
        proposal.id,
        decision_id=decision.id,
        portfolio_id="portfolio:growth",
    )

    assert portfolio.option_ids == (aggressive.id,)
    assert runtime.list_work() == []


def test_resource_allocation_is_decision_qualified_and_budget_fenced() -> None:
    runtime = WorldRuntime.sqlite()
    mandate, goal, responsibility = _setup(runtime)
    issue = runtime.portfolio.open_issue(
        issue_id="strategy-issue:growth",
        subject="company",
        question="How much should we allocate?",
        mandate_id=mandate.id,
        basis_refs=("evidence:market",),
    )
    option = runtime.portfolio.record_option(
        issue.id,
        option_id="strategic-option:sales",
        hypothesis={"channel": "outbound"},
        evaluation={"channel": "outbound", "confidence": "medium"},
        basis_refs=("evidence:outbound",),
    )
    proposal = runtime.portfolio.propose_portfolio(
        issue.id,
        proposal_id="portfolio-proposal:growth",
        option_ids=(option.id,),
        goal_refs=(goal.id,),
        resource_budget={"cash": {"amount": 100.0, "unit": "CNY"}},
        basis_refs=("evidence:portfolio",),
    )
    activate = _record_decision(
        runtime,
        "decision:portfolio",
        target_ref=proposal.id,
        operation="activate-portfolio",
    )
    portfolio = runtime.portfolio.activate_portfolio(
        proposal.id,
        decision_id=activate.id,
        portfolio_id="portfolio:growth",
    )

    first_decision = _record_decision(
        runtime,
        "decision:allocate:60",
        target_ref=portfolio.id,
        operation="allocate-resource",
        responsibility_id=responsibility.id,
        resource_type="cash",
        amount=60.0,
        unit="CNY",
    )
    first = runtime.portfolio.allocate(
        portfolio.id,
        responsibility.id,
        allocation_id="resource-allocation:first",
        resource_type="cash",
        amount=60.0,
        unit="CNY",
        decision_id=first_decision.id,
        basis_refs=("evidence:allocation:first",),
    )
    assert first.amount == 60.0

    second_decision = _record_decision(
        runtime,
        "decision:allocate:50",
        target_ref=portfolio.id,
        operation="allocate-resource",
        responsibility_id=responsibility.id,
        resource_type="cash",
        amount=50.0,
        unit="CNY",
    )
    with pytest.raises(ValueError, match="exceeds portfolio budget"):
        runtime.portfolio.allocate(
            portfolio.id,
            responsibility.id,
            allocation_id="resource-allocation:second",
            resource_type="cash",
            amount=50.0,
            unit="CNY",
            decision_id=second_decision.id,
            basis_refs=("evidence:allocation:second",),
        )


def test_portfolio_state_survives_state_bundle_round_trip() -> None:
    runtime = WorldRuntime.sqlite()
    mandate, goal, _ = _setup(runtime)
    issue = runtime.portfolio.open_issue(
        issue_id="strategy-issue:portable",
        subject="company",
        question="Which strategy survives migration?",
        mandate_id=mandate.id,
        basis_refs=("evidence:portable",),
    )
    option = runtime.portfolio.record_option(
        issue.id,
        option_id="strategic-option:portable",
        hypothesis={"path": "portable"},
        evaluation={"portable": True},
        basis_refs=("evidence:option",),
    )
    proposal = runtime.portfolio.propose_portfolio(
        issue.id,
        proposal_id="portfolio-proposal:portable",
        option_ids=(option.id,),
        goal_refs=(goal.id,),
        resource_budget={"hours": {"amount": 10.0, "unit": "hour"}},
        basis_refs=("evidence:proposal",),
    )
    decision = _record_decision(
        runtime,
        "decision:portfolio:portable",
        target_ref=proposal.id,
        operation="activate-portfolio",
    )
    runtime.portfolio.activate_portfolio(
        proposal.id,
        decision_id=decision.id,
        portfolio_id="portfolio:portable",
    )

    bundle = runtime.state_bundle.export()
    restored = WorldRuntime.sqlite()
    restored.state_bundle.import_bundle(bundle)

    portfolio = restored.portfolio.get_portfolio("portfolio:portable")
    assert portfolio.issue_id == issue.id
    assert portfolio.goal_refs == (goal.id,)


def test_resource_allocation_unit_is_part_of_budget_semantics() -> None:
    runtime = WorldRuntime.sqlite()
    mandate, goal, responsibility = _setup(runtime)
    issue = runtime.portfolio.open_issue(
        issue_id="strategy-issue:units",
        subject="company",
        question="How should currency budget be used?",
        mandate_id=mandate.id,
        basis_refs=("evidence:units",),
    )
    option = runtime.portfolio.record_option(
        issue.id,
        option_id="strategic-option:units",
        hypothesis={"path": "spend"},
        evaluation={"confidence": "high"},
        basis_refs=("evidence:units-option",),
    )
    proposal = runtime.portfolio.propose_portfolio(
        issue.id,
        proposal_id="portfolio-proposal:units",
        option_ids=(option.id,),
        goal_refs=(goal.id,),
        resource_budget={"cash": {"amount": 100.0, "unit": "CNY"}},
        basis_refs=("evidence:units-proposal",),
    )
    activate = _record_decision(
        runtime,
        "decision:units:activate",
        target_ref=proposal.id,
        operation="activate-portfolio",
    )
    portfolio = runtime.portfolio.activate_portfolio(
        proposal.id,
        decision_id=activate.id,
        portfolio_id="portfolio:units",
    )
    allocation_decision = _record_decision(
        runtime,
        "decision:units:allocate",
        target_ref=portfolio.id,
        operation="allocate-resource",
        responsibility_id=responsibility.id,
        resource_type="cash",
        amount=10.0,
        unit="USD",
    )

    with pytest.raises(ValueError, match="unit differs"):
        runtime.portfolio.allocate(
            portfolio.id,
            responsibility.id,
            resource_type="cash",
            amount=10.0,
            unit="USD",
            decision_id=allocation_decision.id,
            basis_refs=("evidence:units-allocation",),
        )


def test_portfolio_retirement_and_issue_closure_require_explicit_decisions() -> None:
    runtime = WorldRuntime.sqlite()
    mandate, goal, _ = _setup(runtime)
    issue = runtime.portfolio.open_issue(
        issue_id="strategy-issue:lifecycle",
        subject="company",
        question="Which strategy should remain active?",
        mandate_id=mandate.id,
        basis_refs=("evidence:lifecycle",),
    )
    option = runtime.portfolio.record_option(
        issue.id,
        option_id="strategic-option:lifecycle",
        hypothesis={"path": "one"},
        evaluation={"confidence": "high"},
        basis_refs=("evidence:lifecycle-option",),
    )
    proposal = runtime.portfolio.propose_portfolio(
        issue.id,
        proposal_id="portfolio-proposal:lifecycle",
        option_ids=(option.id,),
        goal_refs=(goal.id,),
        resource_budget={},
        basis_refs=("evidence:lifecycle-proposal",),
    )
    activate = _record_decision(
        runtime,
        "decision:lifecycle:activate",
        target_ref=proposal.id,
        operation="activate-portfolio",
    )
    portfolio = runtime.portfolio.activate_portfolio(
        proposal.id,
        decision_id=activate.id,
        portfolio_id="portfolio:lifecycle",
    )

    close_early = _record_decision(
        runtime,
        "decision:lifecycle:close-early",
        target_ref=issue.id,
        operation="close-strategic-issue",
    )
    with pytest.raises(ValueError, match="active strategic portfolio"):
        runtime.portfolio.close_issue(
            issue.id,
            decision_id=close_early.id,
            basis_refs=("evidence:close-early",),
        )

    retire = _record_decision(
        runtime,
        "decision:lifecycle:retire",
        target_ref=portfolio.id,
        operation="retire-portfolio",
    )
    retired = runtime.portfolio.retire_portfolio(
        portfolio.id,
        decision_id=retire.id,
        basis_refs=("evidence:retire",),
    )
    assert retired.status == "retired"

    close = _record_decision(
        runtime,
        "decision:lifecycle:close",
        target_ref=issue.id,
        operation="close-strategic-issue",
    )
    closed = runtime.portfolio.close_issue(
        issue.id,
        decision_id=close.id,
        basis_refs=("evidence:close",),
    )
    assert closed.status == "closed"
