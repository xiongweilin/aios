from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping

from .common import new_id
from .ledger import LedgerConcurrencyConflict, SemanticLedger


@dataclass(frozen=True, slots=True)
class QualificationBinding:
    id: str
    principal: str
    subject_ref: str
    dependency_ref: str
    dependency_version: str
    assumption: str
    scope: Mapping[str, object]
    review_policy: Mapping[str, object]
    basis_refs: tuple[str, ...]
    status: str = "active"
    supersedes_binding_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewCase:
    """One durable review lifecycle.

    Assessment and resolution are distinct transitions on the same case rather
    than separate top-level durable objects.
    """

    id: str
    principal: str
    binding_id: str
    subject_ref: str
    dependency_ref: str
    previous_version: str
    observed_version: str
    reason: str
    required_action: str
    basis_refs: tuple[str, ...]
    status: str = "open"
    assessment_id: str | None = None
    disposition: str | None = None
    assessment_basis_refs: tuple[str, ...] = ()
    rationale: str = ""
    resolution_ref: str | None = None
    resolution_basis_refs: tuple[str, ...] = ()


class QualificationService:
    """Targeted qualification review without automatic owner mutation."""

    _DISPOSITIONS = frozenset(
        {"continue", "revalidate", "reopen", "retire", "reauthorize"}
    )

    def __init__(self, ledger: SemanticLedger) -> None:
        self.ledger = ledger

    def register_binding(
        self,
        *,
        principal: str,
        subject_ref: str,
        dependency_ref: str,
        dependency_version: str,
        assumption: str,
        scope: Mapping[str, object] | None = None,
        review_policy: Mapping[str, object] | None = None,
        basis_refs: tuple[str, ...],
        binding_id: str | None = None,
        supersedes_binding_id: str | None = None,
    ) -> QualificationBinding:
        if not principal.strip():
            raise ValueError("qualification binding requires principal")
        if not subject_ref.strip() or not dependency_ref.strip():
            raise ValueError("qualification binding requires subject and dependency refs")
        if not dependency_version.strip():
            raise ValueError("qualification binding requires dependency version")
        if not assumption.strip():
            raise ValueError("qualification binding requires explicit assumption")
        if not basis_refs:
            raise ValueError("qualification binding requires basis refs")

        if supersedes_binding_id is not None:
            previous = self.get_binding(supersedes_binding_id)
            if previous.status != "active":
                raise ValueError("only active qualification binding can be superseded")
            if (
                previous.principal != principal
                or previous.subject_ref != subject_ref
                or previous.dependency_ref != dependency_ref
            ):
                raise ValueError("qualification binding successor must preserve identity")
            if previous.assumption != assumption or dict(previous.scope) != dict(scope or {}):
                raise ValueError("qualification binding successor must preserve assumption scope")

        item = QualificationBinding(
            id=binding_id or new_id("qualification-binding"),
            principal=principal,
            subject_ref=subject_ref,
            dependency_ref=dependency_ref,
            dependency_version=dependency_version,
            assumption=assumption,
            scope=dict(scope or {}),
            review_policy=dict(review_policy or {}),
            basis_refs=tuple(basis_refs),
            supersedes_binding_id=supersedes_binding_id,
        )
        value = self._binding_value(item)
        existing = self.ledger.project_get("qualification.binding", item.id)
        if existing is not None:
            if existing[0] != value:
                raise ValueError("qualification binding identity rebound")
            return self.get_binding(item.id)

        with self.ledger.transaction():
            self.ledger.project_put(
                "qualification.binding",
                item.id,
                value,
                expected_version=0,
            )
            if supersedes_binding_id is not None:
                previous_row = self.ledger.project_get(
                    "qualification.binding",
                    supersedes_binding_id,
                )
                if previous_row is None:
                    raise KeyError(supersedes_binding_id)
                previous_value, previous_version = previous_row
                if previous_value.get("status") != "active":
                    raise ValueError("qualification binding is not current")
                retired = dict(previous_value)
                retired["status"] = "superseded"
                retired["superseded_by"] = item.id
                self.ledger.project_put(
                    "qualification.binding",
                    supersedes_binding_id,
                    retired,
                    expected_version=previous_version,
                )
                self.ledger.append(
                    stream=f"qualification-binding:{supersedes_binding_id}",
                    kind="qualification.binding.superseded",
                    payload={
                        "binding_id": supersedes_binding_id,
                        "successor_id": item.id,
                    },
                )
            self.ledger.append(
                stream=f"qualification-binding:{item.id}",
                kind="qualification.binding.registered",
                payload=value,
            )
        return item

    def observe_dependency_change(
        self,
        *,
        principal: str,
        dependency_ref: str,
        observed_version: str,
        basis_refs: tuple[str, ...],
        reason: str = "",
    ) -> tuple[ReviewCase, ...]:
        if not principal.strip():
            raise ValueError("dependency change requires principal")
        if not observed_version.strip():
            raise ValueError("dependency change requires observed version")
        if not basis_refs:
            raise ValueError("dependency change requires basis refs")

        cases: list[ReviewCase] = []
        seen: set[str] = set()
        for event in self.ledger.events(kind="qualification.binding.registered"):
            binding_id = str(event.payload.get("id", ""))
            if not binding_id or binding_id in seen:
                continue
            seen.add(binding_id)
            item = self.get_binding(binding_id)
            if (
                item.status != "active"
                or item.principal != principal
                or item.dependency_ref != dependency_ref
                or item.dependency_version == observed_version
            ):
                continue

            review_id = self._review_id(item.id, observed_version)
            existing = self.ledger.project_get("qualification.review", review_id)
            if existing is not None:
                cases.append(self._review_from_value(existing[0]))
                continue

            case = ReviewCase(
                id=review_id,
                principal=item.principal,
                binding_id=item.id,
                subject_ref=item.subject_ref,
                dependency_ref=item.dependency_ref,
                previous_version=item.dependency_version,
                observed_version=observed_version,
                reason=reason or "qualified dependency changed",
                required_action=str(item.review_policy.get("on_change", "review")),
                basis_refs=tuple(basis_refs),
            )
            value = self._review_value(case)
            try:
                with self.ledger.transaction():
                    self.ledger.project_put(
                        "qualification.review",
                        case.id,
                        value,
                        expected_version=0,
                    )
                    self.ledger.append(
                        stream=f"qualification-review:{case.id}",
                        kind="qualification.review.opened",
                        payload=value,
                    )
            except LedgerConcurrencyConflict:
                concurrent = self.ledger.project_get("qualification.review", case.id)
                if concurrent is None:
                    raise
                case = self._review_from_value(concurrent[0])
            cases.append(case)
        return tuple(cases)

    def assess_review(
        self,
        review_id: str,
        *,
        disposition: str,
        basis_refs: tuple[str, ...],
        rationale: str = "",
        assessment_id: str | None = None,
    ) -> ReviewCase:
        if disposition not in self._DISPOSITIONS:
            raise ValueError("unsupported review disposition")
        if not basis_refs:
            raise ValueError("review assessment requires basis refs")

        row = self.ledger.project_get("qualification.review", review_id)
        if row is None:
            raise KeyError(review_id)
        value, version = row
        if value.get("status") != "open":
            raise ValueError("review is already assessed or resolved")

        updated = dict(value)
        updated["assessment_id"] = assessment_id or new_id("review-assessment")
        updated["disposition"] = disposition
        updated["assessment_basis_refs"] = list(basis_refs)
        updated["rationale"] = rationale
        if disposition == "continue":
            updated["status"] = "resolved"
            updated["resolution_ref"] = updated["assessment_id"]
            updated["resolution_basis_refs"] = list(basis_refs)
        else:
            updated["status"] = "assessed"

        with self.ledger.transaction():
            self.ledger.project_put(
                "qualification.review",
                review_id,
                updated,
                expected_version=version,
            )
            self.ledger.append(
                stream=f"qualification-review:{review_id}",
                kind="qualification.review.assessed",
                payload={
                    "review_id": review_id,
                    "assessment_id": updated["assessment_id"],
                    "disposition": disposition,
                    "basis_refs": list(basis_refs),
                    "rationale": rationale,
                },
            )
            if disposition == "continue":
                self.ledger.append(
                    stream=f"qualification-review:{review_id}",
                    kind="qualification.review.resolved",
                    payload={
                        "review_id": review_id,
                        "resolution_ref": updated["resolution_ref"],
                        "basis_refs": list(basis_refs),
                    },
                )
        return self._review_from_value(updated)

    def resolve_review(
        self,
        review_id: str,
        *,
        resolution_ref: str,
        basis_refs: tuple[str, ...],
    ) -> ReviewCase:
        if not resolution_ref.strip():
            raise ValueError("review resolution requires an owning-subsystem resolution ref")
        if not basis_refs:
            raise ValueError("review resolution requires basis refs")

        row = self.ledger.project_get("qualification.review", review_id)
        if row is None:
            raise KeyError(review_id)
        value, version = row
        status = str(value.get("status", "open"))
        if status == "resolved":
            if value.get("resolution_ref") != resolution_ref:
                raise ValueError("review resolution identity rebound")
            return self._review_from_value(value)
        if status != "assessed":
            raise ValueError("review must be assessed before resolution")
        if value.get("disposition") == "continue":
            raise ValueError("continue assessment resolves the review directly")

        updated = dict(value)
        updated["status"] = "resolved"
        updated["resolution_ref"] = resolution_ref
        updated["resolution_basis_refs"] = list(basis_refs)
        with self.ledger.transaction():
            self.ledger.project_put(
                "qualification.review",
                review_id,
                updated,
                expected_version=version,
            )
            self.ledger.append(
                stream=f"qualification-review:{review_id}",
                kind="qualification.review.resolved",
                payload={
                    "review_id": review_id,
                    "assessment_id": value.get("assessment_id"),
                    "disposition": value.get("disposition"),
                    "resolution_ref": resolution_ref,
                    "basis_refs": list(basis_refs),
                },
            )
        return self._review_from_value(updated)

    def advance_binding_after_review(
        self,
        binding_id: str,
        *,
        review_id: str,
        new_version: str,
        basis_refs: tuple[str, ...],
        successor_id: str | None = None,
    ) -> QualificationBinding:
        previous = self.get_binding(binding_id)
        review = self.get_review(review_id)
        if review.binding_id != binding_id:
            raise ValueError("review does not apply to qualification binding")
        if review.status != "resolved":
            raise ValueError("review must be resolved before binding replacement")
        if review.observed_version != new_version:
            raise ValueError("binding replacement must use reviewed observed version")
        if review.assessment_id is None:
            raise ValueError("resolved review is missing assessment")

        return self.register_binding(
            principal=previous.principal,
            subject_ref=previous.subject_ref,
            dependency_ref=previous.dependency_ref,
            dependency_version=new_version,
            assumption=previous.assumption,
            scope=previous.scope,
            review_policy=previous.review_policy,
            basis_refs=basis_refs,
            binding_id=successor_id,
            supersedes_binding_id=binding_id,
        )

    def get_binding(self, binding_id: str) -> QualificationBinding:
        row = self.ledger.project_get("qualification.binding", binding_id)
        if row is None:
            raise KeyError(binding_id)
        value = row[0]
        return QualificationBinding(
            id=str(value["id"]),
            principal=str(value["principal"]),
            subject_ref=str(value["subject_ref"]),
            dependency_ref=str(value["dependency_ref"]),
            dependency_version=str(value["dependency_version"]),
            assumption=str(value["assumption"]),
            scope=dict(value.get("scope", {})),
            review_policy=dict(value.get("review_policy", {})),
            basis_refs=tuple(str(v) for v in value.get("basis_refs", [])),
            status=str(value.get("status", "active")),
            supersedes_binding_id=(
                str(value["supersedes_binding_id"])
                if value.get("supersedes_binding_id")
                else None
            ),
        )

    def get_review(self, review_id: str) -> ReviewCase:
        row = self.ledger.project_get("qualification.review", review_id)
        if row is None:
            raise KeyError(review_id)
        return self._review_from_value(row[0])

    def pending_reviews(
        self,
        *,
        principal: str | None = None,
        subject_ref: str | None = None,
    ) -> tuple[ReviewCase, ...]:
        items: list[ReviewCase] = []
        seen: set[str] = set()
        for event in self.ledger.events(kind="qualification.review.opened"):
            review_id = str(event.payload.get("id", ""))
            if not review_id or review_id in seen:
                continue
            seen.add(review_id)
            review = self.get_review(review_id)
            if review.status == "resolved":
                continue
            if principal is not None and review.principal != principal:
                continue
            if subject_ref is not None and review.subject_ref != subject_ref:
                continue
            items.append(review)
        return tuple(items)

    def open_reviews(
        self,
        *,
        principal: str | None = None,
        subject_ref: str | None = None,
    ) -> tuple[ReviewCase, ...]:
        return tuple(
            item
            for item in self.pending_reviews(principal=principal, subject_ref=subject_ref)
            if item.status == "open"
        )

    @staticmethod
    def _review_id(binding_id: str, observed_version: str) -> str:
        digest = sha256(f"{binding_id}\0{observed_version}".encode()).hexdigest()[:24]
        return f"qualification-review:{digest}"

    @staticmethod
    def _binding_value(item: QualificationBinding) -> dict[str, object]:
        return {
            "id": item.id,
            "principal": item.principal,
            "subject_ref": item.subject_ref,
            "dependency_ref": item.dependency_ref,
            "dependency_version": item.dependency_version,
            "assumption": item.assumption,
            "scope": dict(item.scope),
            "review_policy": dict(item.review_policy),
            "basis_refs": list(item.basis_refs),
            "status": item.status,
            "supersedes_binding_id": item.supersedes_binding_id,
        }

    @staticmethod
    def _review_value(item: ReviewCase) -> dict[str, object]:
        return {
            "id": item.id,
            "principal": item.principal,
            "binding_id": item.binding_id,
            "subject_ref": item.subject_ref,
            "dependency_ref": item.dependency_ref,
            "previous_version": item.previous_version,
            "observed_version": item.observed_version,
            "reason": item.reason,
            "required_action": item.required_action,
            "basis_refs": list(item.basis_refs),
            "status": item.status,
            "assessment_id": item.assessment_id,
            "disposition": item.disposition,
            "assessment_basis_refs": list(item.assessment_basis_refs),
            "rationale": item.rationale,
            "resolution_ref": item.resolution_ref,
            "resolution_basis_refs": list(item.resolution_basis_refs),
        }

    @staticmethod
    def _review_from_value(value: Mapping[str, object]) -> ReviewCase:
        return ReviewCase(
            id=str(value["id"]),
            principal=str(value["principal"]),
            binding_id=str(value["binding_id"]),
            subject_ref=str(value["subject_ref"]),
            dependency_ref=str(value["dependency_ref"]),
            previous_version=str(value["previous_version"]),
            observed_version=str(value["observed_version"]),
            reason=str(value["reason"]),
            required_action=str(value["required_action"]),
            basis_refs=tuple(str(v) for v in value.get("basis_refs", [])),
            status=str(value.get("status", "open")),
            assessment_id=(
                str(value["assessment_id"]) if value.get("assessment_id") else None
            ),
            disposition=(
                str(value["disposition"]) if value.get("disposition") else None
            ),
            assessment_basis_refs=tuple(
                str(v) for v in value.get("assessment_basis_refs", [])
            ),
            rationale=str(value.get("rationale", "")),
            resolution_ref=(
                str(value["resolution_ref"]) if value.get("resolution_ref") else None
            ),
            resolution_basis_refs=tuple(
                str(v) for v in value.get("resolution_basis_refs", [])
            ),
        )


__all__ = ["QualificationBinding", "QualificationService", "ReviewCase"]
