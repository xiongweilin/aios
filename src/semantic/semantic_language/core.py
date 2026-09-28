from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

SEMANTIC_REF_WIRE_VERSION = "0.1"


class SemanticKind(StrEnum):
    """Stable cross-domain semantic roles.

    A role belongs here only when collapsing it into another role can create a
    cross-domain correctness failure. Payload schemas and lifecycle state are
    owned by the subsystem that creates the object.
    """

    CLAIM = "claim"
    EVIDENCE = "evidence"
    UNKNOWN = "unknown"
    DECISION = "decision"
    AUTHORIZATION = "authorization"
    EFFECT = "effect"
    OUTCOME = "outcome"
    RESPONSIBILITY = "responsibility"
    REVISION = "revision"


def new_semantic_id(kind: SemanticKind | str) -> str:
    value = kind.value if isinstance(kind, SemanticKind) else str(kind)
    return f"{value}:{uuid4()}"


@dataclass(frozen=True, slots=True)
class SemanticRef:
    """Versioned reference envelope shared across owners.

    Universal roles are deliberately closed. Domain/runtime-owned concepts use an
    explicit non-universal namespace so extending one owner never requires editing
    the semantic kernel.
    """

    kind: SemanticKind | str
    id: str
    namespace: str = "universal"
    version: str = SEMANTIC_REF_WIRE_VERSION

    def __post_init__(self) -> None:
        kind_value = self.kind.value if isinstance(self.kind, SemanticKind) else str(self.kind)
        if not kind_value.strip() or not self.id.strip() or not self.namespace.strip():
            raise ValueError("SemanticRef requires non-empty kind, id and namespace")
        universal_values = {item.value for item in SemanticKind}
        if self.namespace == "universal" and kind_value not in universal_values:
            raise ValueError("owner-specific SemanticRef kind requires non-universal namespace")
        if self.version != SEMANTIC_REF_WIRE_VERSION:
            raise ValueError(f"unsupported SemanticRef wire version: {self.version}")

    @property
    def kind_value(self) -> str:
        return self.kind.value if isinstance(self.kind, SemanticKind) else str(self.kind)
