from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PersonalContextItem:
    ref: str
    revision: int
    kind: str
    semantic: dict[str, Any]
    value: Any
    status: str

    @property
    def basis_ref(self) -> str:
        return f"personal-world:{self.ref}@{self.revision}"


@dataclass(frozen=True, slots=True)
class PersonalContextBundle:
    projection_ref: str
    purpose: str
    included_items: tuple[PersonalContextItem, ...]
    blocked_items: tuple[PersonalContextItem, ...]
    unknowns: tuple[str, ...] = ()
    excluded_count: int = 0

    @property
    def basis_refs(self) -> tuple[str, ...]:
        return tuple(item.basis_ref for item in self.included_items)

    @property
    def revalidation_refs(self) -> tuple[str, ...]:
        return tuple(item.basis_ref for item in self.blocked_items)


class PersonalContextProvider(Protocol):
    def model_context(
        self,
        subject_id: UUID,
        *,
        purpose: str,
        query: str,
    ) -> PersonalContextBundle: ...

    def revalidate(
        self,
        subject_id: UUID,
        *,
        purpose: str,
        basis_refs: tuple[str, ...],
    ) -> None: ...