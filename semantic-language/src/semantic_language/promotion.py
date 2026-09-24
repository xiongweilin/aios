from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromotionCandidate:
    concept: str
    observed_domains: tuple[str, ...]
    collapse_failures: tuple[str, ...]
    stable_meaning: bool
    runtime_independent: bool
    domain_independent: bool

    @property
    def distinct_domains(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.observed_domains))

    @property
    def eligible(self) -> bool:
        return (
            len(self.distinct_domains) >= 3
            and bool(self.collapse_failures)
            and self.stable_meaning
            and self.runtime_independent
            and self.domain_independent
        )


def assert_promotion_eligible(candidate: PromotionCandidate) -> None:
    if candidate.eligible:
        return
    reasons: list[str] = []
    if len(candidate.distinct_domains) < 3:
        reasons.append("requires at least three materially different domains")
    if not candidate.collapse_failures:
        reasons.append("requires a demonstrated semantic correctness failure if collapsed")
    if not candidate.stable_meaning:
        reasons.append("meaning is not stable across contexts")
    if not candidate.runtime_independent:
        reasons.append("concept depends on one Runtime implementation")
    if not candidate.domain_independent:
        reasons.append("concept contains domain-specific policy")
    raise ValueError("; ".join(reasons))


__all__ = ["PromotionCandidate", "assert_promotion_eligible"]
