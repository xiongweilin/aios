"""Fail-closed executor boundary for model-relative contingent policy proposals.

A BAA-compiled plan is *advice*, not an authorization or proof of reality.
This adapter stages only requests; existing World Runtime authority, effect
identity, durable dispatch, independent readback and settlement remain mandatory.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal


class ContingentPolicyViolation(ValueError):
    """The proposed continuation cannot be executed under its current binding."""


@dataclass(frozen=True)
class CaseBinding:
    case_id: str
    authority_epoch: int
    state_version: int

    def __post_init__(self) -> None:
        if not self.case_id or self.authority_epoch < 0 or self.state_version < 0:
            raise ValueError("case and nonnegative authority/state versions are required")


@dataclass(frozen=True)
class ProposedStep:
    kind: Literal["effect", "probe", "done", "blocked"]
    name: str = ""
    # Terminal here means "plan traversal finished", not domain completion.
    reason: str = ""


def _validate_policy_shape(
    root: Mapping[str, Any], *, max_depth: int = 32, max_nodes: int = 128,
) -> None:
    """Bounded structural preflight; world-relative soundness is *not* proven.

    Refuse incomplete future branches before ANY proposed effect. This does
    not replace BAA's world-model checker or live execution authorization.
    """
    seen_on_path: set[int] = set()
    remaining_nodes = [max_nodes]

    def walk(node: Mapping[str, Any], depth: int, effects: frozenset[str]) -> None:
        remaining_nodes[0] -= 1
        if remaining_nodes[0] < 0 or depth > max_depth:
            raise ContingentPolicyViolation("policy exceeds finite size/depth bounds")
        if not isinstance(node, Mapping):
            raise ContingentPolicyViolation("policy continuation is not an object")
        identity = id(node)
        if identity in seen_on_path:
            raise ContingentPolicyViolation("cyclic policy graph")
        seen_on_path.add(identity)
        try:
            kind = node.get("kind")
            next_node = node.get("next")
            branches = node.get("branches")
            if kind == "done":
                if next_node is not None or branches:
                    raise ContingentPolicyViolation("malformed terminal policy node")
                return
            name = node.get("name")
            if not isinstance(name, str) or not name:
                raise ContingentPolicyViolation("policy operation name must be nonempty")
            if kind == "effect":
                if name in effects or branches or not isinstance(next_node, Mapping):
                    raise ContingentPolicyViolation(
                        "missing effect continuation or replayed effect in policy"
                    )
                walk(next_node, depth + 1, effects | {name})
            elif kind == "probe":
                if (next_node is not None or not isinstance(branches, Mapping)
                        or not branches or
                        any(not isinstance(k, str) or not k for k in branches)):
                    raise ContingentPolicyViolation(
                        "missing or malformed observation branch"
                    )
                for child in branches.values():
                    walk(child, depth + 1, effects)
            else:
                raise ContingentPolicyViolation("unrecognized policy node")
        finally:
            seen_on_path.remove(identity)

    walk(root, 0, frozenset())


class ContingentPolicyCursor:
    """Sequentially traverses a policy while enforcing real authority on every step.

    It does not call providers. An effect request returned by next_step must
    still follow the existing World Runtime execution pathway. The caller
    confirms successful *independent* readback before advancing the cursor.
    """

    def __init__(
        self,
        policy: Mapping[str, Any],
        binding: CaseBinding,
        *,
        authorize_effect: Callable[[CaseBinding, str], bool],
        qualify_probe: Callable[[CaseBinding, str], bool],
    ) -> None:
        # Validate the *entire* future tree before staging the first step.
        # Then own a snapshot so callers cannot mutate a later branch.
        _validate_policy_shape(policy)
        self._node = deepcopy(dict(policy))
        _validate_policy_shape(self._node)
        self._binding = binding
        self._authorize = authorize_effect
        self._qualify = qualify_probe
        self._pending: ProposedStep | None = None
        self._attempted: set[str] = set()
        self._blocked = False

    def _require_same_binding(self, binding: CaseBinding) -> None:
        if binding != self._binding:
            self._blocked = True
            raise ContingentPolicyViolation(
                "case, authority epoch or state version changed; recompile"
            )

    def next_step(self, binding: CaseBinding) -> ProposedStep:
        self._require_same_binding(binding)
        if self._blocked:
            return ProposedStep("blocked", reason="unresolved or invalidated policy")
        if self._pending is not None:
            if self._pending.kind == "effect":
                return ProposedStep("blocked", reason="effect attempted or in flight; await readback")
            return self._pending
        kind = self._node.get("kind")
        if kind == "done":
            # A plan-end hint never closes an Administrative case.
            return ProposedStep("done", reason="requires independent domain completion")
        name = self._node.get("name")
        if not isinstance(name, str) or not name:
            self._blocked = True
            raise ContingentPolicyViolation("malformed policy node")
        if kind == "effect":
            if name in self._attempted:
                self._blocked = True
                raise ContingentPolicyViolation("effect identity already attempted")
            if not self._authorize(binding, name):
                self._blocked = True
                raise ContingentPolicyViolation("effect not authorized by live policy")
            if not isinstance(self._node.get("next"), dict):
                self._blocked = True
                raise ContingentPolicyViolation("effect continuation missing")
        elif kind == "probe":
            if not self._qualify(binding, name):
                self._blocked = True
                raise ContingentPolicyViolation("untrusted or unavailable readback source")
            branches = self._node.get("branches")
            if not isinstance(branches, dict) or not branches:
                self._blocked = True
                raise ContingentPolicyViolation("observation branches missing")
        else:
            self._blocked = True
            raise ContingentPolicyViolation("unrecognized policy node")
        self._pending = ProposedStep(kind, name)
        return self._pending

    def observe(
        self,
        binding: CaseBinding,
        *,
        probe_name: str,
        observed_label: str,
        independent_readback: bool,
    ) -> None:
        self._require_same_binding(binding)
        if (self._blocked or self._pending != ProposedStep("probe", probe_name)
                or not independent_readback
                or not self._qualify(binding, probe_name)):
            self._blocked = True
            raise ContingentPolicyViolation("observation is unqualified or unrequested")
        branches = self._node["branches"]
        continuation = branches.get(observed_label)
        if not isinstance(continuation, dict):
            self._blocked = True
            raise ContingentPolicyViolation("unmodeled observation; halt and replan")
        self._node = continuation
        self._pending = None

    def resolve_effect(
        self,
        binding: CaseBinding,
        *,
        effect_name: str,
        result: Literal["verified", "unknown", "failed"],
        independent_readback: bool,
    ) -> None:
        self._require_same_binding(binding)
        if self._blocked or self._pending != ProposedStep("effect", effect_name):
            self._blocked = True
            raise ContingentPolicyViolation("effect was not independently admitted")
        # An effect-unknown response must never be treated as success or
        # license to dispatch another effect. A *precompiled, qualified*
        # read-only probe is the sole allowed next step for reconciliation.
        self._attempted.add(effect_name)
        continuation = self._node["next"]
        if not isinstance(continuation, dict):
            self._blocked = True
            raise ContingentPolicyViolation("effect continuation is malformed")
        if result == "unknown":
            probe_name = continuation.get("name")
            if (continuation.get("kind") != "probe"
                    or not isinstance(probe_name, str)
                    or not probe_name
                    or not self._qualify(binding, probe_name)):
                self._blocked = True
                raise ContingentPolicyViolation(
                    "effect unknown without qualified reconciliation probe"
                )
            self._node = continuation
            self._pending = None
            return
        if result != "verified" or not independent_readback:
            self._blocked = True
            raise ContingentPolicyViolation(
                "effect is not independently verified; reconciliation required"
            )
        self._node = continuation
        self._pending = None


def compile_authorized_external_intents(
    obligation_set: Any,
    allowed_effects: tuple[Any, ...],
    *,
    case: Any,
    governance_basis_id: Any,
) -> tuple[Any, ...]:
    """Preflight the full effect batch *before* mutable domain fulfillment.

    The immutable obligation set must agree with the current policy's exact
    target/operation/authority class. A duplicate or rebound item is rejected
    instead of being partly planned before the mismatch is detected.
    """
    from .obligations import ObligationFulfillmentKind

    # A batch can be internally consistent yet belong to a *different*
    # case, subject, or past approval. Compare it to live governed inputs.
    if (obligation_set.case_id != case.case_id
            or obligation_set.authority_epoch != case.authority_epoch
            or obligation_set.governance_basis_id != governance_basis_id
            or not case.subject_ref):
        raise ContingentPolicyViolation(
            "frozen batch does not match current case/authority/governance"
        )

    allowed: set[tuple[str, str, Any]] = {
        (t.target_system, t.operation, t.authority_class) for t in allowed_effects
    }
    if len(allowed) != len(allowed_effects):
        raise ContingentPolicyViolation("duplicate current-policy effect templates")
    selected: list[Any] = []
    seen_ids: set[Any] = set()
    seen_intents: set[tuple[str, str, str]] = set()
    for obligation in obligation_set.obligations:
        if (obligation.case_id != obligation_set.case_id
                or obligation.authority_epoch != obligation_set.authority_epoch
                or obligation.governance_basis_id != obligation_set.governance_basis_id):
            raise ContingentPolicyViolation("obligation escaped case/authority/governance binding")
        if obligation.obligation_id in seen_ids:
            raise ContingentPolicyViolation("duplicate frozen obligation identity")
        seen_ids.add(obligation.obligation_id)
        if obligation.fulfillment_kind is not ObligationFulfillmentKind.EXTERNAL_EFFECT_VERIFIED:
            continue
        if obligation.subject_ref != case.subject_ref:
            raise ContingentPolicyViolation(
                "effect subject rebound from current governed case"
            )
        exact = (obligation.target_system, obligation.required_operation,
                 obligation.authority_class)
        if exact not in allowed:
            raise ContingentPolicyViolation("effect is outside currently allowed policy")
        expected = obligation.expected_postcondition
        if (expected.get("target_system") != obligation.target_system
                or expected.get("operation") != obligation.required_operation
                or expected.get("subject_ref") != obligation.subject_ref):
            raise ContingentPolicyViolation("expected effect rebound from approved intent")
        identity = (obligation.subject_ref, obligation.target_system, obligation.required_operation)
        if identity in seen_intents:
            raise ContingentPolicyViolation("duplicate external intent; replay risk")
        seen_intents.add(identity)
        selected.append(obligation)
    # No silent omission of any current-policy required external effect.
    if {(item.target_system, item.required_operation, item.authority_class)
        for item in selected} != allowed:
        raise ContingentPolicyViolation("frozen obligations do not cover allowed effects")
    return tuple(selected)
