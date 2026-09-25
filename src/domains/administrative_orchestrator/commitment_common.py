from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from .commitment_models import CommitmentRecord
from .domain import AdministrativeCase

M9_NAMESPACE = UUID("7c4f2b4a-7ed5-4c72-a45c-4ecbcb1a46a3")
REVIEW_ROLES = {"administrative_operator", "administrative_admin"}


class CommitmentIntakeError(ValueError):
    """The candidate cannot cross the M9 human-qualification boundary."""


@dataclass(frozen=True, slots=True)
class ResponsibilityRefs:
    responsibility_ref: str
    responsibility_version: int
    admission_ref: str | None = None
    assessment_ref: str | None = None
    proposal_ref: str | None = None


class ResponsibilityProvisioner(Protocol):
    def provision(
        self,
        *,
        case: AdministrativeCase,
        commitment: CommitmentRecord,
        governance_basis: Any,
    ) -> ResponsibilityRefs: ...


__all__ = [
    "CommitmentIntakeError",
    "M9_NAMESPACE",
    "REVIEW_ROLES",
    "ResponsibilityProvisioner",
    "ResponsibilityRefs",
]
