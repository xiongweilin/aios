from __future__ import annotations

from dataclasses import dataclass

from .journal import MetaPolicyEvent
from .policy_learning import PolicyEvaluation


@dataclass(frozen=True, slots=True)
class ReplayMetrics:
    episode_count: int
    intent_count: int
    blind_retry_count: int
    closure_ready_count: int
    reopen_count: int


class ReplayEvaluator:
    """Deterministic structural evaluation for policy promotion gates."""

    def metrics(self, events: tuple[MetaPolicyEvent, ...]) -> ReplayMetrics:
        controllers = {event.controller_ref for event in events}
        intents = tuple(
            event for event in events if event.event_type == "MetaControlIntentSelected"
        )
        blind_retries = sum(
            1
            for event in intents
            if event.payload.get("intent") == "acquire-evidence"
            and event.payload.get("novel_discrimination") is False
        )
        closure_ready = sum(
            1 for event in intents if event.payload.get("closure_readiness") == "ready"
        )
        reopen = sum(1 for event in intents if event.payload.get("intent") == "reopen")
        return ReplayMetrics(
            episode_count=len(controllers),
            intent_count=len(intents),
            blind_retry_count=blind_retries,
            closure_ready_count=closure_ready,
            reopen_count=reopen,
        )

    def compare(
        self,
        *,
        rule_ref: str,
        baseline: tuple[MetaPolicyEvent, ...],
        candidate: tuple[MetaPolicyEvent, ...],
        evidence_refs: tuple[str, ...] = (),
    ) -> PolicyEvaluation:
        before = self.metrics(baseline)
        after = self.metrics(candidate)
        regressions: list[str] = []
        improvements: list[str] = []
        if after.blind_retry_count > before.blind_retry_count:
            regressions.append("blind retry count increased")
        elif after.blind_retry_count < before.blind_retry_count:
            improvements.append("blind retry count decreased")
        if before.intent_count and after.intent_count > before.intent_count * 2:
            regressions.append("policy more than doubled cognitive action count")
        if after.closure_ready_count > before.closure_ready_count:
            improvements.append("bounded closure readiness increased")
        return PolicyEvaluation(
            rule_ref=rule_ref,
            passed=not regressions,
            replay_cases=max(before.episode_count, after.episode_count),
            regressions=tuple(regressions),
            improvements=tuple(improvements),
            evidence_refs=evidence_refs,
        )
