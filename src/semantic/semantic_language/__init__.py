"""Cross-domain semantic boundary vocabulary.

The package owns stable roles, references, canonicalization and non-substitution
rules. Payload schemas, persistence and lifecycle state belong to their owner.
"""

from .canonical import canonical_json, semantic_digest
from .core import (
    SEMANTIC_REF_WIRE_VERSION,
    SemanticKind,
    SemanticRef,
    new_semantic_id,
)
from .promotion import PromotionCandidate, assert_promotion_eligible
from .rules import NonSubstitutionError, assert_distinct, distinction

__all__ = [
    "SEMANTIC_REF_WIRE_VERSION",
    "SemanticKind",
    "SemanticRef",
    "canonical_json",
    "semantic_digest",
    "new_semantic_id",
    "NonSubstitutionError",
    "assert_distinct",
    "distinction",
    "PromotionCandidate",
    "assert_promotion_eligible",
]
