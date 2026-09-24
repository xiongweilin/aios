from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping
from uuid import uuid4


SEMANTIC_REF_WIRE_VERSION = "0.1"


class SemanticKind(StrEnum):
    CLAIM = "claim"
    EVIDENCE = "evidence"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"
    GOAL = "goal"
    CONSTRAINT = "constraint"
    MANDATE = "mandate"
    PROPOSAL = "proposal"
    DECISION = "decision"
    COMMITMENT = "commitment"
    PERMISSION = "permission"
    OBLIGATION = "obligation"
    AUTHORIZATION = "authorization"
    CAPABILITY = "capability"
    ACTION = "action"
    EFFECT = "effect"
    OUTCOME = "outcome"
    ACCEPTANCE = "acceptance"
    REVISION = "revision"
    RESPONSIBILITY = "responsibility"


def new_semantic_id(kind: SemanticKind | str) -> str:
    value = kind.value if isinstance(kind, SemanticKind) else str(kind)
    return f"{value}:{uuid4()}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class SemanticRef:
    """Canonical reference envelope.

    `version` is the SemanticRef wire-format version, not the semantic-language
    package version. Domain-specific kinds are allowed only in a non-universal
    namespace so extensions cannot masquerade as universal semantic primitives.
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
        if (
            isinstance(self.kind, str)
            and kind_value not in universal_values
            and self.namespace == "universal"
        ):
            raise ValueError("domain-specific SemanticRef kind requires non-universal namespace")
        if self.version != SEMANTIC_REF_WIRE_VERSION:
            raise ValueError(f"unsupported SemanticRef wire version: {self.version}")

    @property
    def kind_value(self) -> str:
        return self.kind.value if isinstance(self.kind, SemanticKind) else str(self.kind)


@dataclass(frozen=True, slots=True)
class SemanticObject:
    id: str
    created_at: datetime = field(default_factory=utc_now)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> SemanticKind:
        raise NotImplementedError

    @property
    def ref(self) -> SemanticRef:
        return SemanticRef(kind=self.kind, id=self.id)


@dataclass(frozen=True, slots=True)
class Claim(SemanticObject):
    subject: str = ""
    proposition: str = ""

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.CLAIM


@dataclass(frozen=True, slots=True)
class Evidence(SemanticObject):
    subject: str = ""
    content: Mapping[str, Any] = field(default_factory=dict)
    source: str = ""
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    derived_from: tuple[SemanticRef, ...] = ()

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.EVIDENCE


@dataclass(frozen=True, slots=True)
class Unknown(SemanticObject):
    subject: str = ""
    question: str = ""
    blocks: tuple[SemanticRef, ...] = ()

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.UNKNOWN


@dataclass(frozen=True, slots=True)
class Conflict(SemanticObject):
    subject: str = ""
    members: tuple[SemanticRef, ...] = ()
    description: str = ""

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.CONFLICT


@dataclass(frozen=True, slots=True)
class Goal(SemanticObject):
    subject: str = ""
    desired_state: Mapping[str, Any] = field(default_factory=dict)
    acceptance_refs: tuple[SemanticRef, ...] = ()
    basis_refs: tuple[SemanticRef, ...] = ()

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.GOAL


@dataclass(frozen=True, slots=True)
class Constraint(SemanticObject):
    subject: str = ""
    predicate: Mapping[str, Any] = field(default_factory=dict)
    basis_refs: tuple[SemanticRef, ...] = ()

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.CONSTRAINT


@dataclass(frozen=True, slots=True)
class Mandate(SemanticObject):
    principal: str = ""
    scope: Mapping[str, Any] = field(default_factory=dict)
    goal_refs: tuple[SemanticRef, ...] = ()
    constraint_refs: tuple[SemanticRef, ...] = ()
    authority_ceiling: Mapping[str, Any] = field(default_factory=dict)
    expires_at: datetime | None = None

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.MANDATE


@dataclass(frozen=True, slots=True)
class Proposal(SemanticObject):
    subject: str = ""
    proposed_by: str = ""
    content: Mapping[str, Any] = field(default_factory=dict)
    basis_refs: tuple[SemanticRef, ...] = ()

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.PROPOSAL


@dataclass(frozen=True, slots=True)
class Decision(SemanticObject):
    subject: str = ""
    decided_by: str = ""
    selected: Mapping[str, Any] = field(default_factory=dict)
    proposal_refs: tuple[SemanticRef, ...] = ()
    alternative_refs: tuple[SemanticRef, ...] = ()
    basis_refs: tuple[SemanticRef, ...] = ()
    authority_refs: tuple[SemanticRef, ...] = ()
    review_triggers: tuple[Mapping[str, Any], ...] = ()

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.DECISION


@dataclass(frozen=True, slots=True)
class Commitment(SemanticObject):
    principal: str = ""
    subject: str = ""
    terms: Mapping[str, Any] = field(default_factory=dict)
    decision_refs: tuple[SemanticRef, ...] = ()

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.COMMITMENT


@dataclass(frozen=True, slots=True)
class Permission(SemanticObject):
    principal: str = ""
    action: str = ""
    resource: str = ""
    conditions: Mapping[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.PERMISSION


@dataclass(frozen=True, slots=True)
class Obligation(SemanticObject):
    principal: str = ""
    subject: str = ""
    required_state: Mapping[str, Any] = field(default_factory=dict)
    due_at: datetime | None = None

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.OBLIGATION


@dataclass(frozen=True, slots=True)
class Authorization(SemanticObject):
    principal: str = ""
    action: str = ""
    resource: str = ""
    mandate_refs: tuple[SemanticRef, ...] = ()
    decision_refs: tuple[SemanticRef, ...] = ()
    conditions: Mapping[str, Any] = field(default_factory=dict)
    expires_at: datetime | None = None

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.AUTHORIZATION


@dataclass(frozen=True, slots=True)
class Capability(SemanticObject):
    provider: str = ""
    name: str = ""
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    effect_class: str = ""

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.CAPABILITY


@dataclass(frozen=True, slots=True)
class Action(SemanticObject):
    actor: str = ""
    capability_ref: SemanticRef | None = None
    parameters: Mapping[str, Any] = field(default_factory=dict)
    authorization_refs: tuple[SemanticRef, ...] = ()

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.ACTION


@dataclass(frozen=True, slots=True)
class Effect(SemanticObject):
    action_ref: SemanticRef | None = None
    external_ref: str | None = None
    observed_state: Mapping[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[SemanticRef, ...] = ()

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.EFFECT


@dataclass(frozen=True, slots=True)
class Outcome(SemanticObject):
    subject: str = ""
    observed_state: Mapping[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[SemanticRef, ...] = ()
    effect_refs: tuple[SemanticRef, ...] = ()

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.OUTCOME


@dataclass(frozen=True, slots=True)
class Acceptance(SemanticObject):
    subject: str = ""
    outcome_refs: tuple[SemanticRef, ...] = ()
    criteria: Mapping[str, Any] = field(default_factory=dict)
    accepted: bool | None = None
    assessed_by: str = ""

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.ACCEPTANCE


@dataclass(frozen=True, slots=True)
class Revision(SemanticObject):
    target_ref: SemanticRef | None = None
    supersedes_ref: SemanticRef | None = None
    reason: str = ""
    basis_refs: tuple[SemanticRef, ...] = ()

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.REVISION


@dataclass(frozen=True, slots=True)
class Responsibility(SemanticObject):
    principal: str = ""
    subject: str = ""
    scope: Mapping[str, Any] = field(default_factory=dict)
    goal_refs: tuple[SemanticRef, ...] = ()
    constraint_refs: tuple[SemanticRef, ...] = ()
    acceptance_refs: tuple[SemanticRef, ...] = ()
    authority_refs: tuple[SemanticRef, ...] = ()

    @property
    def kind(self) -> SemanticKind:
        return SemanticKind.RESPONSIBILITY
