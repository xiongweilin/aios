"""Fail-closed executor boundary for model-relative contingent policy proposals.

A BAA-compiled plan is *advice*, not an authorization or proof of reality.
This adapter stages only requests; existing World Runtime authority, effect
identity, durable dispatch, independent readback and settlement remain mandatory.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping


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
        self._node = dict(policy)
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
        self._attempted.add(effect_name)
        if result != "verified" or not independent_readback:
            self._blocked = True
            raise ContingentPolicyViolation(
                "effect is not independently verified; reconciliation required"
            )
        continuation = self._node["next"]
        if not isinstance(continuation, dict):
            self._blocked = True
            raise ContingentPolicyViolation("effect continuation is malformed")
        self._node = continuation
        self._pending = None
