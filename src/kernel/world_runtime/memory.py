from dataclasses import dataclass
from typing import Any, Mapping

from semantic_language import Revision, SemanticRef

from .common import new_id
from .ledger import SemanticLedger
from .lineage import RevisionLineageService


@dataclass(frozen=True, slots=True)
class Experience:
    id: str
    scope: Mapping[str, Any]
    lesson: Mapping[str, Any]
    basis_refs: tuple[str, ...]
    validity_conditions: Mapping[str, Any]
    reopen_conditions: Mapping[str, Any]
    status: str = "candidate"


class MemoryService:
    NAMESPACE = "world-runtime.memory"
    KIND = "experience"

    def __init__(
        self,
        ledger: SemanticLedger,
        lineage: RevisionLineageService | None = None,
    ) -> None:
        self.ledger = ledger
        self.lineage = lineage or RevisionLineageService(ledger)

    @classmethod
    def experience_ref(cls, experience_id: str) -> SemanticRef:
        return SemanticRef(
            kind=cls.KIND,
            id=experience_id,
            namespace=cls.NAMESPACE,
        )

    @staticmethod
    def _experience(value: Mapping[str, Any]) -> Experience:
        return Experience(
            id=str(value["id"]),
            scope=dict(value.get("scope", {})),
            lesson=dict(value.get("lesson", {})),
            basis_refs=tuple(str(item) for item in value.get("basis_refs", [])),
            validity_conditions=dict(value.get("validity_conditions", {})),
            reopen_conditions=dict(value.get("reopen_conditions", {})),
            status=str(value.get("status", "candidate")),
        )

    def propose(
        self,
        *,
        scope: Mapping[str, Any],
        lesson: Mapping[str, Any],
        basis_refs: tuple[str, ...],
        validity_conditions: Mapping[str, Any] | None = None,
        reopen_conditions: Mapping[str, Any] | None = None,
    ) -> Experience:
        if not basis_refs:
            raise ValueError("experience requires evidence/outcome basis")
        item = Experience(
            new_id("experience"),
            dict(scope),
            dict(lesson),
            basis_refs,
            dict(validity_conditions or {}),
            dict(reopen_conditions or {}),
        )
        value = {
            "id": item.id,
            "scope": dict(item.scope),
            "lesson": dict(item.lesson),
            "basis_refs": list(item.basis_refs),
            "validity_conditions": dict(item.validity_conditions),
            "reopen_conditions": dict(item.reopen_conditions),
            "status": item.status,
        }
        with self.ledger.transaction():
            self.ledger.project_put(
                "memory.experience",
                item.id,
                value,
                expected_version=0,
            )
            self.ledger.append(
                stream=f"memory:{item.id}",
                kind="memory.experience.proposed",
                payload=value,
            )
        return item

    def get(self, experience_id: str) -> Experience:
        current = self.ledger.project_get("memory.experience", experience_id)
        if current is None:
            raise KeyError(experience_id)
        return self._experience(current[0])

    def qualify(
        self,
        experience_id: str,
        *,
        assessment_refs: tuple[str, ...],
    ) -> None:
        if not assessment_refs:
            raise ValueError("qualification requires explicit assessment basis")
        current = self.ledger.project_get("memory.experience", experience_id)
        if current is None:
            raise KeyError(experience_id)
        value, version = current
        status = str(value.get("status", "candidate"))
        if status == "qualified":
            if tuple(value.get("qualification_refs", ())) == tuple(assessment_refs):
                return
            raise ValueError("qualified experience requires reopen before requalification")
        if status not in {"candidate", "reopened"}:
            raise ValueError(f"experience status {status} cannot be qualified")
        value["status"] = "qualified"
        value["qualification_refs"] = list(assessment_refs)
        with self.ledger.transaction():
            self.ledger.project_put(
                "memory.experience",
                experience_id,
                value,
                expected_version=version,
            )
            self.ledger.append(
                stream=f"memory:{experience_id}",
                kind="memory.experience.qualified",
                payload={"assessment_refs": list(assessment_refs)},
            )

    def invalidate(
        self,
        experience_id: str,
        *,
        reason: str,
        basis_refs: tuple[str, ...],
    ) -> None:
        if not reason.strip() or not basis_refs:
            raise ValueError("experience invalidation requires reason and basis refs")
        self.lineage.assert_current(self.experience_ref(experience_id))
        current = self.ledger.project_get("memory.experience", experience_id)
        if current is None:
            raise KeyError(experience_id)
        value, version = current
        if value.get("status") != "qualified":
            raise ValueError("only a currently qualified experience can be invalidated")
        value["status"] = "invalidated"
        value["invalidation_reason"] = reason
        value["invalidation_basis_refs"] = list(basis_refs)
        with self.ledger.transaction():
            self.ledger.project_put(
                "memory.experience",
                experience_id,
                value,
                expected_version=version,
            )
            self.ledger.append(
                stream=f"memory:{experience_id}",
                kind="memory.experience.invalidated",
                payload={"reason": reason, "basis_refs": list(basis_refs)},
            )

    def reopen(
        self,
        experience_id: str,
        *,
        reason: str,
        basis_refs: tuple[str, ...],
    ) -> None:
        if not reason.strip() or not basis_refs:
            raise ValueError("experience reopen requires reason and basis refs")
        self.lineage.assert_current(self.experience_ref(experience_id))
        current = self.ledger.project_get("memory.experience", experience_id)
        if current is None:
            raise KeyError(experience_id)
        value, version = current
        if value.get("status") != "invalidated":
            raise ValueError("only an invalidated experience can be reopened")
        value["status"] = "reopened"
        value["reopen_reason"] = reason
        value["reopen_basis_refs"] = list(basis_refs)
        value.pop("qualification_refs", None)
        with self.ledger.transaction():
            self.ledger.project_put(
                "memory.experience",
                experience_id,
                value,
                expected_version=version,
            )
            self.ledger.append(
                stream=f"memory:{experience_id}",
                kind="memory.experience.reopened",
                payload={"reason": reason, "basis_refs": list(basis_refs)},
            )

    def supersede(
        self,
        previous_id: str,
        successor_id: str,
        revision: Revision,
    ) -> None:
        previous_ref = self.experience_ref(previous_id)
        successor_ref = self.experience_ref(successor_id)
        if revision.supersedes_ref != previous_ref:
            raise ValueError("Experience Revision must supersede the selected experience")
        if revision.target_ref != successor_ref:
            raise ValueError("Experience Revision target must be the successor experience")

        previous_row = self.ledger.project_get("memory.experience", previous_id)
        successor_row = self.ledger.project_get("memory.experience", successor_id)
        if previous_row is None:
            raise KeyError(previous_id)
        if successor_row is None:
            raise KeyError(successor_id)
        previous, previous_version = previous_row
        successor = successor_row[0]
        if previous.get("status") != "qualified":
            raise ValueError("only a qualified experience can be superseded")
        if successor.get("status") != "qualified":
            raise ValueError("successor experience must be qualified before supersession")
        self.lineage.assert_current(previous_ref)

        updated_previous = dict(previous)
        updated_previous["status"] = "superseded"
        updated_previous["successor_id"] = successor_id
        updated_previous["revision_id"] = revision.id
        with self.ledger.transaction():
            self.lineage.record(revision)
            self.ledger.project_put(
                "memory.experience",
                previous_id,
                updated_previous,
                expected_version=previous_version,
            )
            self.ledger.append(
                stream=f"memory:{previous_id}",
                kind="memory.experience.superseded",
                payload={
                    "successor_id": successor_id,
                    "revision_id": revision.id,
                    "basis_refs": [ref.id for ref in revision.basis_refs],
                },
            )

    def get_current(self, experience_id: str) -> Experience:
        current_ref = self.lineage.resolve_current(
            self.experience_ref(experience_id)
        )
        return self.get(current_ref.id)

    def is_applicable(self, experience_id: str) -> bool:
        ref = self.experience_ref(experience_id)
        if not self.lineage.is_current(ref):
            return False
        return self.get(experience_id).status == "qualified"
