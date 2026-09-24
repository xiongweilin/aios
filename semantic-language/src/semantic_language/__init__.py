"""Universal semantic primitives.

This package owns meanings and non-substitution rules only.
It does not own persistence, workflow, orchestration, or domain lifecycles.
"""

from .canonical import canonical_json, semantic_digest
from .core import (
    Acceptance,
    Action,
    Authorization,
    Capability,
    Claim,
    Commitment,
    Conflict,
    Constraint,
    Decision,
    Effect,
    Evidence,
    Goal,
    Mandate,
    Obligation,
    Outcome,
    Permission,
    Proposal,
    Responsibility,
    Revision,
    SEMANTIC_REF_WIRE_VERSION,
    SemanticKind,
    SemanticRef,
    Unknown,
    new_semantic_id,
)
from .promotion import PromotionCandidate, assert_promotion_eligible
from .rules import NonSubstitutionError, assert_distinct, distinction

__all__ = [
    "Acceptance", "Action", "Authorization", "Capability", "Claim", "Commitment",
    "Conflict", "Constraint", "Decision", "Effect", "Evidence", "Goal", "Mandate",
    "Obligation", "Outcome", "Permission", "Proposal", "Responsibility", "Revision",
    "SEMANTIC_REF_WIRE_VERSION", "SemanticKind", "SemanticRef", "Unknown", "canonical_json", "semantic_digest",
    "new_semantic_id", "NonSubstitutionError", "assert_distinct", "distinction",
    "PromotionCandidate", "assert_promotion_eligible",
]