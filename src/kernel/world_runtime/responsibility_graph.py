from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .common import new_id
from .decisions import assert_decision_applies
from .ledger import LedgerConcurrencyConflict, SemanticLedger
from .responsibility import ResponsibilityService

ResponsibilityRelationKind = Literal["requires", "contributes-to"]


@dataclass(frozen=True, slots=True)
class ResponsibilityRelation:
    id: str
    source_responsibility_id: str
    target_responsibility_id: str
    relation: ResponsibilityRelationKind
    decision_id: str
    basis_refs: tuple[str, ...]
    status: str = "active"


class ResponsibilityGraphService:
    """Durable cross-domain responsibility topology.

    The graph owns only generic responsibility relations. Domain-specific process
    semantics remain in Domain Controllers. A `requires` edge is a hard
    qualification dependency: the source cannot be assessed satisfied or
    discharged until the target responsibility is discharged.
    """

    _RELATIONS = {"requires", "contributes-to"}
    _META_NAMESPACE = "responsibility.graph.meta"
    _RELATION_NAMESPACE = "responsibility.relation"
    _META_KEY = "global"

    def __init__(self, ledger: SemanticLedger, responsibilities: ResponsibilityService) -> None:
        self.ledger = ledger
        self.responsibilities = responsibilities

    def create(
        self,
        source_responsibility_id: str,
        target_responsibility_id: str,
        *,
        relation: ResponsibilityRelationKind,
        decision_id: str,
        basis_refs: tuple[str, ...],
        relation_id: str | None = None,
    ) -> ResponsibilityRelation:
        if relation not in self._RELATIONS:
            raise ValueError(f"unsupported responsibility relation: {relation}")
        if source_responsibility_id == target_responsibility_id:
            raise ValueError("responsibility relation cannot target itself")
        if not basis_refs:
            raise ValueError("responsibility relation requires basis refs")

        source = self.responsibilities.get(source_responsibility_id)
        target = self.responsibilities.get(target_responsibility_id)
        if source.principal != target.principal:
            raise ValueError("cross-principal responsibility relation is not allowed")

        assert_decision_applies(
            self.ledger,
            decision_id,
            target_ref=source_responsibility_id,
            operation="relate-responsibility",
            expected={
                "target_responsibility_id": target_responsibility_id,
                "relation": relation,
            },
        )

        item = ResponsibilityRelation(
            id=relation_id or new_id("responsibility-relation"),
            source_responsibility_id=source_responsibility_id,
            target_responsibility_id=target_responsibility_id,
            relation=relation,
            decision_id=decision_id,
            basis_refs=tuple(basis_refs),
        )
        value = self._value(item)
        existing = self.ledger.project_get(self._RELATION_NAMESPACE, item.id)
        if existing is not None:
            if self._identity(existing[0]) != self._identity(value):
                raise ValueError("responsibility relation identity rebound")
            return self.get(item.id)

        for attempt in range(3):
            meta = self.ledger.project_get(self._META_NAMESPACE, self._META_KEY)
            meta_version = 0 if meta is None else meta[1]
            if relation == "requires" and self._would_create_requires_cycle(
                source_responsibility_id,
                target_responsibility_id,
            ):
                raise ValueError("hard responsibility dependency cycle rejected")
            try:
                with self.ledger.transaction():
                    self.ledger.project_put(
                        self._META_NAMESPACE,
                        self._META_KEY,
                        {"generation": meta_version + 1},
                        expected_version=meta_version,
                    )
                    self.ledger.project_put(
                        self._RELATION_NAMESPACE,
                        item.id,
                        value,
                        expected_version=0,
                    )
                    self.ledger.append(
                        stream=f"responsibility-relation:{item.id}",
                        kind="responsibility.relation.created",
                        payload=value,
                    )
                return item
            except LedgerConcurrencyConflict:
                existing = self.ledger.project_get(self._RELATION_NAMESPACE, item.id)
                if existing is not None:
                    if self._identity(existing[0]) != self._identity(value):
                        raise ValueError("responsibility relation identity rebound")
                    return self.get(item.id)
                if attempt == 2:
                    raise
        raise AssertionError("unreachable")

    def retire(
        self,
        relation_id: str,
        *,
        decision_id: str,
        basis_refs: tuple[str, ...],
    ) -> ResponsibilityRelation:
        if not basis_refs:
            raise ValueError("responsibility relation retirement requires basis refs")
        current = self.ledger.project_get(self._RELATION_NAMESPACE, relation_id)
        if current is None:
            raise KeyError(relation_id)
        value, _ = current
        if value.get("status") == "retired":
            if value.get("retirement_decision_id") != decision_id or tuple(
                str(v) for v in value.get("retirement_basis_refs", [])
            ) != tuple(basis_refs):
                raise ValueError("responsibility relation retirement identity rebound")
            return self.get(relation_id)

        assert_decision_applies(
            self.ledger,
            decision_id,
            target_ref=relation_id,
            operation="retire-responsibility-relation",
        )
        updated = dict(value)
        updated["status"] = "retired"
        updated["retirement_decision_id"] = decision_id
        updated["retirement_basis_refs"] = list(basis_refs)

        for attempt in range(3):
            meta = self.ledger.project_get(self._META_NAMESPACE, self._META_KEY)
            meta_version = 0 if meta is None else meta[1]
            latest = self.ledger.project_get(self._RELATION_NAMESPACE, relation_id)
            if latest is None:
                raise KeyError(relation_id)
            if latest[0].get("status") == "retired":
                if latest[0].get("retirement_decision_id") != decision_id or tuple(
                    str(v) for v in latest[0].get("retirement_basis_refs", [])
                ) != tuple(basis_refs):
                    raise ValueError("responsibility relation retirement identity rebound")
                return self.get(relation_id)
            relation_version = latest[1]
            try:
                with self.ledger.transaction():
                    self.ledger.project_put(
                        self._META_NAMESPACE,
                        self._META_KEY,
                        {"generation": meta_version + 1},
                        expected_version=meta_version,
                    )
                    self.ledger.project_put(
                        self._RELATION_NAMESPACE,
                        relation_id,
                        updated,
                        expected_version=relation_version,
                    )
                    self.ledger.append(
                        stream=f"responsibility-relation:{relation_id}",
                        kind="responsibility.relation.retired",
                        payload={
                            "relation_id": relation_id,
                            "decision_id": decision_id,
                            "basis_refs": list(basis_refs),
                        },
                    )
                return self.get(relation_id)
            except LedgerConcurrencyConflict:
                if attempt == 2:
                    raise
        raise AssertionError("unreachable")

    def get(self, relation_id: str) -> ResponsibilityRelation:
        row = self.ledger.project_get(self._RELATION_NAMESPACE, relation_id)
        if row is None:
            raise KeyError(relation_id)
        value = row[0]
        return ResponsibilityRelation(
            id=str(value["id"]),
            source_responsibility_id=str(value["source_responsibility_id"]),
            target_responsibility_id=str(value["target_responsibility_id"]),
            relation=str(value["relation"]),  # type: ignore[arg-type]
            decision_id=str(value["decision_id"]),
            basis_refs=tuple(str(v) for v in value.get("basis_refs", [])),
            status=str(value.get("status", "active")),
        )

    def list_from(
        self,
        responsibility_id: str,
        *,
        relation: ResponsibilityRelationKind | None = None,
        active_only: bool = True,
    ) -> tuple[ResponsibilityRelation, ...]:
        items: list[ResponsibilityRelation] = []
        seen: set[str] = set()
        for event in self.ledger.events(kind="responsibility.relation.created"):
            relation_id = str(event.payload.get("id", ""))
            if not relation_id or relation_id in seen:
                continue
            seen.add(relation_id)
            try:
                item = self.get(relation_id)
            except KeyError:
                continue
            if item.source_responsibility_id != responsibility_id:
                continue
            if relation is not None and item.relation != relation:
                continue
            if active_only and item.status != "active":
                continue
            items.append(item)
        return tuple(items)

    def list_to(
        self,
        responsibility_id: str,
        *,
        relation: ResponsibilityRelationKind | None = None,
        active_only: bool = True,
    ) -> tuple[ResponsibilityRelation, ...]:
        items: list[ResponsibilityRelation] = []
        seen: set[str] = set()
        for event in self.ledger.events(kind="responsibility.relation.created"):
            relation_id = str(event.payload.get("id", ""))
            if not relation_id or relation_id in seen:
                continue
            seen.add(relation_id)
            try:
                item = self.get(relation_id)
            except KeyError:
                continue
            if item.target_responsibility_id != responsibility_id:
                continue
            if relation is not None and item.relation != relation:
                continue
            if active_only and item.status != "active":
                continue
            items.append(item)
        return tuple(items)

    def assert_requirements_resolved(self, responsibility_id: str) -> None:
        unresolved: list[str] = []
        for edge in self.list_from(responsibility_id, relation="requires"):
            target = self.responsibilities.get(edge.target_responsibility_id)
            if target.status != "discharged":
                unresolved.append(edge.target_responsibility_id)
        if unresolved:
            raise ValueError(
                "responsibility has unresolved required dependencies: "
                + ", ".join(sorted(unresolved))
            )

    def _would_create_requires_cycle(self, source_id: str, target_id: str) -> bool:
        frontier = [target_id]
        visited: set[str] = set()
        while frontier:
            current = frontier.pop()
            if current == source_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            frontier.extend(
                edge.target_responsibility_id
                for edge in self.list_from(current, relation="requires")
            )
        return False

    @staticmethod
    def _identity(value: dict[str, object]) -> dict[str, object]:
        return {
            key: value.get(key)
            for key in (
                "id",
                "source_responsibility_id",
                "target_responsibility_id",
                "relation",
                "decision_id",
                "basis_refs",
            )
        }

    @staticmethod
    def _value(item: ResponsibilityRelation) -> dict[str, object]:
        return {
            "id": item.id,
            "source_responsibility_id": item.source_responsibility_id,
            "target_responsibility_id": item.target_responsibility_id,
            "relation": item.relation,
            "decision_id": item.decision_id,
            "basis_refs": list(item.basis_refs),
            "status": item.status,
        }


__all__ = [
    "ResponsibilityGraphService",
    "ResponsibilityRelation",
    "ResponsibilityRelationKind",
]
