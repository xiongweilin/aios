from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .common import new_id
from .decisions import assert_decision_applies
from .governance import assert_mandate_current
from .ledger import LedgerConcurrencyConflict, SemanticLedger
from .responsibility import ResponsibilityService
from .strategy import StrategicOption, StrategyService


@dataclass(frozen=True, slots=True)
class ResourceBudgetLine:
    amount: float
    unit: str


@dataclass(frozen=True, slots=True)
class StrategicIssue:
    id: str
    principal: str
    subject: str
    question: str
    mandate_id: str
    basis_refs: tuple[str, ...]
    status: str = "open"


@dataclass(frozen=True, slots=True)
class PortfolioProposal:
    id: str
    issue_id: str
    option_ids: tuple[str, ...]
    goal_refs: tuple[str, ...]
    resource_budget: Mapping[str, ResourceBudgetLine]
    basis_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategicPortfolio:
    id: str
    proposal_id: str
    issue_id: str
    decision_id: str
    option_ids: tuple[str, ...]
    goal_refs: tuple[str, ...]
    resource_budget: Mapping[str, ResourceBudgetLine]
    status: str = "active"


@dataclass(frozen=True, slots=True)
class ResourceAllocation:
    id: str
    portfolio_id: str
    responsibility_id: str
    resource_type: str
    amount: float
    unit: str
    decision_id: str
    basis_refs: tuple[str, ...]
    status: str = "active"


class StrategicPortfolioService:
    """Durable strategic qualification without owning cognition or domain work.

    The Runtime stores strategic issues, externally produced options, explicit
    portfolio Decisions, and resource exposure. It does not rank options or
    decide which strategy is preferable.
    """

    def __init__(
        self,
        ledger: SemanticLedger,
        strategy: StrategyService,
        responsibilities: ResponsibilityService,
    ) -> None:
        self.ledger = ledger
        self.strategy = strategy
        self.responsibilities = responsibilities

    def open_issue(
        self,
        *,
        issue_id: str,
        subject: str,
        question: str,
        mandate_id: str,
        basis_refs: tuple[str, ...],
    ) -> StrategicIssue:
        if not question.strip():
            raise ValueError("strategic issue requires a question")
        if not basis_refs:
            raise ValueError("strategic issue requires basis refs")
        mandate = assert_mandate_current(self.ledger, mandate_id)
        principal = str(mandate["principal"])
        item = StrategicIssue(
            issue_id,
            principal,
            subject,
            question,
            mandate_id,
            tuple(basis_refs),
        )
        value = {
            "id": item.id,
            "principal": item.principal,
            "subject": item.subject,
            "question": item.question,
            "mandate_id": item.mandate_id,
            "basis_refs": list(item.basis_refs),
            "status": item.status,
        }
        existing = self.ledger.project_get("strategy.issue", issue_id)
        if existing is not None:
            identity_keys = (
                "id",
                "principal",
                "subject",
                "question",
                "mandate_id",
                "basis_refs",
            )
            existing_identity = {key: existing[0].get(key) for key in identity_keys}
            incoming_identity = {key: value.get(key) for key in identity_keys}
            if existing_identity != incoming_identity:
                raise ValueError("strategic issue identity rebound")
            return self.get_issue(issue_id)
        with self.ledger.transaction():
            self.ledger.project_put("strategy.issue", issue_id, value, expected_version=0)
            self.ledger.append(
                stream=f"strategy-issue:{issue_id}",
                kind="strategy.issue.opened",
                payload=value,
            )
        return item

    def record_option(
        self,
        issue_id: str,
        *,
        hypothesis: Mapping[str, object],
        evaluation: Mapping[str, object],
        basis_refs: tuple[str, ...],
        option_id: str | None = None,
    ) -> StrategicOption:
        issue = self.get_issue(issue_id)
        if issue.status != "open":
            raise ValueError("strategic option requires an open issue")
        if not basis_refs:
            raise ValueError("strategic option requires basis refs")
        option = StrategicOption(
            id=option_id or new_id("strategic-option"),
            subject=issue.subject,
            hypothesis=dict(hypothesis),
            evaluation=dict(evaluation),
            basis_refs=tuple(basis_refs),
        )
        value = {
            "id": option.id,
            "issue_id": issue_id,
            "subject": option.subject,
            "hypothesis": dict(option.hypothesis),
            "evaluation": dict(option.evaluation),
            "basis_refs": list(option.basis_refs),
        }
        existing = self.ledger.project_get("strategy.option", option.id)
        if existing is not None:
            if existing[0] != value:
                raise ValueError("strategic option identity rebound")
            return self.get_option(option.id)
        with self.ledger.transaction():
            self.ledger.project_put("strategy.option", option.id, value, expected_version=0)
            self.ledger.append(
                stream=f"strategy-issue:{issue_id}",
                kind="strategy.option.recorded",
                payload=value,
            )
        return option

    def propose_portfolio(
        self,
        issue_id: str,
        *,
        option_ids: tuple[str, ...],
        goal_refs: tuple[str, ...],
        resource_budget: Mapping[str, ResourceBudgetLine | Mapping[str, object]],
        basis_refs: tuple[str, ...],
        proposal_id: str | None = None,
    ) -> PortfolioProposal:
        issue = self.get_issue(issue_id)
        if issue.status != "open":
            raise ValueError("portfolio proposal requires an open strategic issue")
        if not option_ids:
            raise ValueError("portfolio proposal requires at least one option")
        if not basis_refs:
            raise ValueError("portfolio proposal requires basis refs")
        for option_id in option_ids:
            option = self.ledger.project_get("strategy.option", option_id)
            if option is None or option[0].get("issue_id") != issue_id:
                raise ValueError("portfolio option must belong to the strategic issue")
        for goal_id in goal_refs:
            self.strategy.get_goal(goal_id)
        budget = self._normalize_budget(resource_budget)
        proposal = PortfolioProposal(
            id=proposal_id or new_id("portfolio-proposal"),
            issue_id=issue_id,
            option_ids=tuple(option_ids),
            goal_refs=tuple(goal_refs),
            resource_budget=budget,
            basis_refs=tuple(basis_refs),
        )
        value = self._proposal_value(proposal)
        existing = self.ledger.project_get("strategy.portfolio-proposal", proposal.id)
        if existing is not None:
            if existing[0] != value:
                raise ValueError("portfolio proposal identity rebound")
            return self.get_proposal(proposal.id)
        with self.ledger.transaction():
            self.ledger.project_put(
                "strategy.portfolio-proposal",
                proposal.id,
                value,
                expected_version=0,
            )
            self.ledger.append(
                stream=f"strategy-issue:{issue_id}",
                kind="strategy.portfolio.proposed",
                payload=value,
            )
        return proposal

    def activate_portfolio(
        self,
        proposal_id: str,
        *,
        decision_id: str,
        portfolio_id: str | None = None,
    ) -> StrategicPortfolio:
        proposal = self.get_proposal(proposal_id)
        issue = self.get_issue(proposal.issue_id)
        if issue.status != "open":
            raise ValueError("portfolio activation requires an open strategic issue")
        assert_mandate_current(self.ledger, issue.mandate_id)
        assert_decision_applies(
            self.ledger,
            decision_id,
            target_ref=proposal_id,
            operation="activate-portfolio",
        )
        current = self.ledger.project_get("strategy.portfolio-current", proposal.issue_id)
        if current is not None and current[0].get("status") == "active":
            raise ValueError("strategic issue already has an active portfolio")
        portfolio = StrategicPortfolio(
            id=portfolio_id or new_id("portfolio"),
            proposal_id=proposal.id,
            issue_id=proposal.issue_id,
            decision_id=decision_id,
            option_ids=proposal.option_ids,
            goal_refs=proposal.goal_refs,
            resource_budget=dict(proposal.resource_budget),
        )
        value = self._portfolio_value(portfolio)
        existing = self.ledger.project_get("strategy.portfolio", portfolio.id)
        if existing is not None:
            if existing[0] != value:
                raise ValueError("strategic portfolio identity rebound")
            return self.get_portfolio(portfolio.id)
        with self.ledger.transaction():
            self.ledger.project_put("strategy.portfolio", portfolio.id, value, expected_version=0)
            self.ledger.project_put(
                "strategy.portfolio-current",
                portfolio.issue_id,
                value,
                expected_version=0 if current is None else current[1],
            )
            self.ledger.project_put(
                "strategy.portfolio-allocation-state",
                portfolio.id,
                {"used": {}},
                expected_version=0,
            )
            self.ledger.append(
                stream=f"portfolio:{portfolio.id}",
                kind="strategy.portfolio.activated",
                payload=value,
            )
        return portfolio

    def retire_portfolio(
        self,
        portfolio_id: str,
        *,
        decision_id: str,
        basis_refs: tuple[str, ...],
    ) -> StrategicPortfolio:
        if not basis_refs:
            raise ValueError("portfolio retirement requires basis refs")
        row = self.ledger.project_get("strategy.portfolio", portfolio_id)
        if row is None:
            raise KeyError(portfolio_id)
        value, version = row
        if value.get("status") == "retired":
            return self.get_portfolio(portfolio_id)
        assert_decision_applies(
            self.ledger,
            decision_id,
            target_ref=portfolio_id,
            operation="retire-portfolio",
        )
        current = self.ledger.project_get("strategy.portfolio-current", str(value["issue_id"]))
        if current is None or current[0].get("id") != portfolio_id:
            raise ValueError("only the current portfolio may be retired")
        updated = dict(value)
        updated["status"] = "retired"
        updated["retirement_decision_id"] = decision_id
        updated["retirement_basis_refs"] = list(basis_refs)
        with self.ledger.transaction():
            self.ledger.project_put(
                "strategy.portfolio",
                portfolio_id,
                updated,
                expected_version=version,
            )
            self.ledger.project_put(
                "strategy.portfolio-current",
                str(value["issue_id"]),
                updated,
                expected_version=current[1],
            )
            self.ledger.append(
                stream=f"portfolio:{portfolio_id}",
                kind="strategy.portfolio.retired",
                payload={
                    "portfolio_id": portfolio_id,
                    "decision_id": decision_id,
                    "basis_refs": list(basis_refs),
                },
            )
        return self.get_portfolio(portfolio_id)

    def close_issue(
        self,
        issue_id: str,
        *,
        decision_id: str,
        basis_refs: tuple[str, ...],
    ) -> StrategicIssue:
        if not basis_refs:
            raise ValueError("strategic issue closure requires basis refs")
        row = self.ledger.project_get("strategy.issue", issue_id)
        if row is None:
            raise KeyError(issue_id)
        value, version = row
        if value.get("status") == "closed":
            return self.get_issue(issue_id)
        current = self.ledger.project_get("strategy.portfolio-current", issue_id)
        if current is not None and current[0].get("status") == "active":
            raise ValueError("active strategic portfolio must be retired before issue closure")
        assert_decision_applies(
            self.ledger,
            decision_id,
            target_ref=issue_id,
            operation="close-strategic-issue",
        )
        updated = dict(value)
        updated["status"] = "closed"
        updated["closure_decision_id"] = decision_id
        updated["closure_basis_refs"] = list(basis_refs)
        with self.ledger.transaction():
            self.ledger.project_put(
                "strategy.issue",
                issue_id,
                updated,
                expected_version=version,
            )
            self.ledger.append(
                stream=f"strategy-issue:{issue_id}",
                kind="strategy.issue.closed",
                payload={
                    "issue_id": issue_id,
                    "decision_id": decision_id,
                    "basis_refs": list(basis_refs),
                },
            )
        return self.get_issue(issue_id)

    def allocate(
        self,
        portfolio_id: str,
        responsibility_id: str,
        *,
        resource_type: str,
        amount: float,
        unit: str,
        decision_id: str,
        basis_refs: tuple[str, ...],
        allocation_id: str | None = None,
    ) -> ResourceAllocation:
        if amount <= 0:
            raise ValueError("resource allocation amount must be positive")
        if not resource_type.strip() or not unit.strip():
            raise ValueError("resource allocation requires type and unit")
        if not basis_refs:
            raise ValueError("resource allocation requires basis refs")
        portfolio = self.get_portfolio(portfolio_id)
        if portfolio.status != "active":
            raise ValueError("resource allocation requires active portfolio")
        responsibility = self.responsibilities.get(responsibility_id)
        issue = self.get_issue(portfolio.issue_id)
        if responsibility.principal != issue.principal:
            raise ValueError("resource allocation responsibility belongs to another principal")
        if portfolio.goal_refs and not set(responsibility.goal_refs).intersection(portfolio.goal_refs):
            raise ValueError("responsibility is outside portfolio goals")
        ceiling = portfolio.resource_budget.get(resource_type)
        if ceiling is None:
            raise ValueError("resource type is outside portfolio budget")
        if ceiling.unit != unit:
            raise ValueError("resource allocation unit differs from portfolio budget")
        assert_decision_applies(
            self.ledger,
            decision_id,
            target_ref=portfolio_id,
            operation="allocate-resource",
            expected={
                "responsibility_id": responsibility_id,
                "resource_type": resource_type,
                "amount": float(amount),
                "unit": unit,
            },
        )
        allocation = ResourceAllocation(
            id=allocation_id or new_id("resource-allocation"),
            portfolio_id=portfolio_id,
            responsibility_id=responsibility_id,
            resource_type=resource_type,
            amount=float(amount),
            unit=unit,
            decision_id=decision_id,
            basis_refs=tuple(basis_refs),
        )
        value = {
            "id": allocation.id,
            "portfolio_id": allocation.portfolio_id,
            "responsibility_id": allocation.responsibility_id,
            "resource_type": allocation.resource_type,
            "amount": allocation.amount,
            "unit": allocation.unit,
            "decision_id": allocation.decision_id,
            "basis_refs": list(allocation.basis_refs),
            "status": allocation.status,
        }
        existing = self.ledger.project_get("strategy.resource-allocation", allocation.id)
        if existing is not None:
            if existing[0] != value:
                raise ValueError("resource allocation identity rebound")
            return self.get_allocation(allocation.id)

        for attempt in range(3):
            state_row = self.ledger.project_get(
                "strategy.portfolio-allocation-state",
                portfolio_id,
            )
            if state_row is None:
                raise KeyError(portfolio_id)
            state, version = state_row
            used = {str(k): float(v) for k, v in dict(state.get("used", {})).items()}
            next_used = used.get(resource_type, 0.0) + allocation.amount
            if next_used > ceiling.amount:
                raise ValueError("resource allocation exceeds portfolio budget")
            updated_state = {"used": {**used, resource_type: next_used}}
            try:
                with self.ledger.transaction():
                    self.ledger.project_put(
                        "strategy.portfolio-allocation-state",
                        portfolio_id,
                        updated_state,
                        expected_version=version,
                    )
                    self.ledger.project_put(
                        "strategy.resource-allocation",
                        allocation.id,
                        value,
                        expected_version=0,
                    )
                    self.ledger.append(
                        stream=f"portfolio:{portfolio_id}",
                        kind="strategy.resource.allocated",
                        payload=value,
                    )
                return allocation
            except LedgerConcurrencyConflict:
                existing = self.ledger.project_get(
                    "strategy.resource-allocation",
                    allocation.id,
                )
                if existing is not None:
                    if existing[0] != value:
                        raise ValueError("resource allocation identity rebound")
                    return self.get_allocation(allocation.id)
                if attempt == 2:
                    raise
        raise AssertionError("unreachable")

    def get_issue(self, issue_id: str) -> StrategicIssue:
        row = self.ledger.project_get("strategy.issue", issue_id)
        if row is None:
            raise KeyError(issue_id)
        value = row[0]
        return StrategicIssue(
            id=str(value["id"]),
            principal=str(value["principal"]),
            subject=str(value["subject"]),
            question=str(value["question"]),
            mandate_id=str(value["mandate_id"]),
            basis_refs=tuple(str(v) for v in value.get("basis_refs", [])),
            status=str(value.get("status", "open")),
        )

    def get_option(self, option_id: str) -> StrategicOption:
        row = self.ledger.project_get("strategy.option", option_id)
        if row is None:
            raise KeyError(option_id)
        value = row[0]
        return StrategicOption(
            id=str(value["id"]),
            subject=str(value["subject"]),
            hypothesis=dict(value.get("hypothesis", {})),
            evaluation=dict(value.get("evaluation", {})),
            basis_refs=tuple(str(v) for v in value.get("basis_refs", [])),
        )

    def get_proposal(self, proposal_id: str) -> PortfolioProposal:
        row = self.ledger.project_get("strategy.portfolio-proposal", proposal_id)
        if row is None:
            raise KeyError(proposal_id)
        value = row[0]
        return PortfolioProposal(
            id=str(value["id"]),
            issue_id=str(value["issue_id"]),
            option_ids=tuple(str(v) for v in value.get("option_ids", [])),
            goal_refs=tuple(str(v) for v in value.get("goal_refs", [])),
            resource_budget=self._budget_from_value(value.get("resource_budget", {})),
            basis_refs=tuple(str(v) for v in value.get("basis_refs", [])),
        )

    def get_portfolio(self, portfolio_id: str) -> StrategicPortfolio:
        row = self.ledger.project_get("strategy.portfolio", portfolio_id)
        if row is None:
            raise KeyError(portfolio_id)
        value = row[0]
        return StrategicPortfolio(
            id=str(value["id"]),
            proposal_id=str(value["proposal_id"]),
            issue_id=str(value["issue_id"]),
            decision_id=str(value["decision_id"]),
            option_ids=tuple(str(v) for v in value.get("option_ids", [])),
            goal_refs=tuple(str(v) for v in value.get("goal_refs", [])),
            resource_budget=self._budget_from_value(value.get("resource_budget", {})),
            status=str(value.get("status", "active")),
        )

    def get_allocation(self, allocation_id: str) -> ResourceAllocation:
        row = self.ledger.project_get("strategy.resource-allocation", allocation_id)
        if row is None:
            raise KeyError(allocation_id)
        value = row[0]
        return ResourceAllocation(
            id=str(value["id"]),
            portfolio_id=str(value["portfolio_id"]),
            responsibility_id=str(value["responsibility_id"]),
            resource_type=str(value["resource_type"]),
            amount=float(value["amount"]),
            unit=str(value["unit"]),
            decision_id=str(value["decision_id"]),
            basis_refs=tuple(str(v) for v in value.get("basis_refs", [])),
            status=str(value.get("status", "active")),
        )

    @staticmethod
    def _normalize_budget(
        resource_budget: Mapping[str, ResourceBudgetLine | Mapping[str, object]],
    ) -> dict[str, ResourceBudgetLine]:
        budget: dict[str, ResourceBudgetLine] = {}
        for resource_type, raw in resource_budget.items():
            if isinstance(raw, ResourceBudgetLine):
                line = raw
            elif isinstance(raw, Mapping):
                if "amount" not in raw or "unit" not in raw:
                    raise ValueError("resource budget requires amount and unit")
                line = ResourceBudgetLine(float(raw["amount"]), str(raw["unit"]))
            else:
                raise ValueError("resource budget requires structured amount/unit lines")
            if not str(resource_type).strip() or line.amount < 0 or not line.unit.strip():
                raise ValueError("resource budget line is invalid")
            budget[str(resource_type)] = line
        return budget

    @staticmethod
    def _budget_value(
        resource_budget: Mapping[str, ResourceBudgetLine],
    ) -> dict[str, dict[str, object]]:
        return {
            str(resource_type): {"amount": line.amount, "unit": line.unit}
            for resource_type, line in resource_budget.items()
        }

    @classmethod
    def _budget_from_value(cls, value: object) -> dict[str, ResourceBudgetLine]:
        if not isinstance(value, Mapping):
            raise ValueError("stored resource budget is invalid")
        return cls._normalize_budget(
            {
                str(resource_type): raw
                for resource_type, raw in value.items()
                if isinstance(raw, Mapping)
            }
        )

    @classmethod
    def _proposal_value(cls, proposal: PortfolioProposal) -> dict[str, object]:
        return {
            "id": proposal.id,
            "issue_id": proposal.issue_id,
            "option_ids": list(proposal.option_ids),
            "goal_refs": list(proposal.goal_refs),
            "resource_budget": cls._budget_value(proposal.resource_budget),
            "basis_refs": list(proposal.basis_refs),
        }

    @classmethod
    def _portfolio_value(cls, portfolio: StrategicPortfolio) -> dict[str, object]:
        return {
            "id": portfolio.id,
            "proposal_id": portfolio.proposal_id,
            "issue_id": portfolio.issue_id,
            "decision_id": portfolio.decision_id,
            "option_ids": list(portfolio.option_ids),
            "goal_refs": list(portfolio.goal_refs),
            "resource_budget": cls._budget_value(portfolio.resource_budget),
            "status": portfolio.status,
        }


__all__ = [
    "PortfolioProposal",
    "ResourceAllocation",
    "ResourceBudgetLine",
    "StrategicIssue",
    "StrategicPortfolio",
    "StrategicPortfolioService",
]
