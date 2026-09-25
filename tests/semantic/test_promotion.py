import pytest

from semantic_language.promotion import PromotionCandidate, assert_promotion_eligible


def test_promotion_requires_three_materially_different_domains() -> None:
    candidate = PromotionCandidate(
        concept="Qualification",
        observed_domains=("development", "administrative"),
        collapse_failures=("qualification collapsed into permission",),
        stable_meaning=True,
        runtime_independent=True,
        domain_independent=True,
    )
    assert candidate.eligible is False
    with pytest.raises(ValueError, match="three materially different domains"):
        assert_promotion_eligible(candidate)


def test_promotion_requires_real_non_substitution_failure() -> None:
    candidate = PromotionCandidate(
        concept="Assignment",
        observed_domains=("development", "administrative", "personal-operations"),
        collapse_failures=(),
        stable_meaning=True,
        runtime_independent=True,
        domain_independent=True,
    )
    assert candidate.eligible is False


def test_candidate_is_eligible_only_after_cross_domain_validation() -> None:
    candidate = PromotionCandidate(
        concept="Delegation",
        observed_domains=("development", "administrative", "personal-operations"),
        collapse_failures=(
            "delegation collapsed into authorization loses responsibility lineage",
        ),
        stable_meaning=True,
        runtime_independent=True,
        domain_independent=True,
    )
    assert candidate.eligible is True
    assert_promotion_eligible(candidate)
