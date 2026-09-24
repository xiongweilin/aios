from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping

from .common import new_id
from .ledger import LedgerConcurrencyConflict, SemanticLedger


@dataclass(frozen=True, slots=True)
class QualificationDependency:
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
    supersedes_dependency_id: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewObligation:
    id: str
    principal: str
    dependency_id: str
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
    resolution_ref: str | None = None


@dataclass(frozen=True, slots=True)
class RevalidationAssessment:
    id: str
    obligation_id: str
    disposition: str
    basis_refs: tuple[str, ...]
    rationale: str = ""


class QualificationService:
    """Tracks why a historical qualification may need targeted review.

    Dependency change creates a ReviewObligation; it never silently invalidates
    the subject. Resolution records an assessment, while any actual Decision,
    reauthorization, reopen, retirement, or replacement remains owned by the
    subsystem that owns the subject.
    """

    _DISPOSITIONS = {"continue", "revalidate", "reopen", "retire", "reauthorize"}

    def __init__(self, ledger: SemanticLedger) -> None:
        self.ledger = ledger

    def register_dependency(
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
        dependency_id: str | None = None,
        supersedes_dependency_id: str | None = None,
    ) -> QualificationDependency:
        if not principal.strip():
            raise ValueError("qualification dependency requires principal")
        if not subject_ref.strip() or not dependency_ref.strip():
            raise ValueError("qualification dependency requires subject and dependency refs")
        if not dependency_version.strip():
            raise ValueError("qualification dependency requires dependency version")
        if not assumption.strip():
            raise ValueError("qualification dependency requires explicit assumption")
        if not basis_refs:
            raise ValueError("qualification dependency requires basis refs")
        if supersedes_dependency_id is not None:
            previous = self.get_dependency(supersedes_dependency_id)
            if previous.status != "active":
                raise ValueError("only active qualification dependency can be superseded")
            if (
                previous.principal != principal
                or previous.subject_ref != subject_ref
                or previous.dependency_ref != dependency_ref
            ):
                raise ValueError("qualification dependency successor must preserve identity")
            if previous.assumption != assumption or dict(previous.scope) != dict(scope or {}):
                raise ValueError("qualification dependency successor must preserve assumption scope")

        item = QualificationDependency(
            id=dependency_id or new_id("qualification-dependency"),
            principal=principal,
            subject_ref=subject_ref,
            dependency_ref=dependency_ref,
            dependency_version=dependency_version,
            assumption=assumption,
            scope=dict(scope or {}),
            review_policy=dict(review_policy or {}),
            basis_refs=tuple(basis_refs),
            supersedes_dependency_id=supersedes_dependency_id,
        )
        value = self._dependency_value(item)
        existing = self.ledger.project_get("qualification.dependency", item.id)
        if existing is not None:
            if existing[0] != value:
                raise ValueError("qualification dependency identity rebound")
            return self.get_dependency(item.id)

        with self.ledger.transaction():
            self.ledger.project_put(
                "qualification.dependency",
                item.id,
                value,
                expected_version=0,
            )
            if supersedes_dependency_id is not None:
                previous_row = self.ledger.project_get(
                    "qualification.dependency",
                    supersedes_dependency_id,
                )
                if previous_row is None:
                    raise KeyError(supersedes_dependency_id)
                previous_value, previous_version = previous_row
                if previous_value.get("status") != "active":
                    raise ValueError("qualification dependency is not current")
                retired = dict(previous_value)
                retired["status"] = "superseded"
                retired["superseded_by"] = item.id
                self.ledger.project_put(
                    "qualification.dependency",
                    supersedes_dependency_id,
                    retired,
                    expected_version=previous_version,
                )
                self.ledger.append(
                    stream=f"qualification-dependency:{supersedes_dependency_id}",
                    kind="qualification.dependency.superseded",
                    payload={
                        "dependency_id": supersedes_dependency_id,
                        "successor_id": item.id,
                    },
                )
            self.ledger.append(
                stream=f"qualification-dependency:{item.id}",
                kind="qualification.dependency.registered",
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
    ) -> tuple[ReviewObligation, ...]:
        if not principal.strip():
            raise ValueError("dependency change requires principal")
        if not observed_version.strip():
            raise ValueError("dependency change requires observed version")
        if not basis_refs:
            raise ValueError("dependency change requires basis refs")
        obligations: list[ReviewObligation] = []
        seen: set[str] = set()
        for event in self.ledger.events(kind="qualification.dependency.registered"):
            dependency_id = str(event.payload.get("id", ""))
            if not dependency_id or dependency_id in seen:
                continue
            seen.add(dependency_id)
            item = self.get_dependency(dependency_id)
            if (
                item.status != "active"
                or item.principal != principal
                or item.dependency_ref != dependency_ref
            ):
                continue
            if item.dependency_version == observed_version:
                continue
            obligation_id = self._obligation_id(item.id, observed_version)
            existing = self.ledger.project_get("qualification.review-obligation", obligation_id)
            if existing is not None:
                obligations.append(self._obligation_from_value(existing[0]))
                continue
            required_action = str(item.review_policy.get("on_change", "review"))
            obligation = ReviewObligation(
                id=obligation_id,
                principal=item.principal,
                dependency_id=item.id,
                subject_ref=item.subject_ref,
                dependency_ref=item.dependency_ref,
                previous_version=item.dependency_version,
                observed_version=observed_version,
                reason=reason or "qualified dependency changed",
                required_action=required_action,
                basis_refs=tuple(basis_refs),
            )
            value = self._obligation_value(obligation)
            try:
                with self.ledger.transaction():
                    self.ledger.project_put(
                        "qualification.review-obligation",
                        obligation.id,
                        value,
                        expected_version=0,
                    )
                    self.ledger.append(
                        stream=f"qualification-review:{obligation.id}",
                        kind="qualification.review.required",
                        payload=value,
                    )
            except LedgerConcurrencyConflict:
                concurrent = self.ledger.project_get(
                    "qualification.review-obligation",
                    obligation.id,
                )
                if concurrent is None:
                    raise
                obligation = self._obligation_from_value(concurrent[0])
            obligations.append(obligation)
        return tuple(obligations)

    def assess_review(
        self,
        obligation_id: str,
        *,
        disposition: str,
        basis_refs: tuple[str, ...],
        rationale: str = "",
        assessment_id: str | None = None,
    ) -> RevalidationAssessment:
        if disposition not in self._DISPOSITIONS:
            raise ValueError("unsupported revalidation disposition")
        if not basis_refs:
            raise ValueError("revalidation assessment requires basis refs")
        row = self.ledger.project_get("qualification.review-obligation", obligation_id)
        if row is None:
            raise KeyError(obligation_id)
        obligation, version = row
        if obligation.get("status") != "open":
            raise ValueError("review obligation is already resolved")
        assessment = RevalidationAssessment(
            id=assessment_id or new_id("revalidation-assessment"),
            obligation_id=obligation_id,
            disposition=disposition,
            basis_refs=tuple(basis_refs),
            rationale=rationale,
        )
        assessment_value = {
            "id": assessment.id,
            "obligation_id": assessment.obligation_id,
            "disposition": assessment.disposition,
            "basis_refs": list(assessment.basis_refs),
            "rationale": assessment.rationale,
        }
        resolved = dict(obligation)
        resolved["status"] = "resolved" if disposition == "continue" else "assessed"
        resolved["assessment_id"] = assessment.id
        resolved["disposition"] = disposition
        if disposition == "continue":
            resolved["resolution_ref"] = assessment.id
        with self.ledger.transaction():
            self.ledger.project_put(
                "qualification.revalidation-assessment",
                assessment.id,
                assessment_value,
                expected_version=0,
            )
            self.ledger.project_put(
                "qualification.review-obligation",
                obligation_id,
                resolved,
                expected_version=version,
            )
            self.ledger.append(
                stream=f"qualification-review:{obligation_id}",
                kind="qualification.review.assessed",
                payload=assessment_value,
            )
        return assessment


    def resolve_review(
        self,
        obligation_id: str,
        *,
        resolution_ref: str,
        basis_refs: tuple[str, ...],
    ) -> ReviewObligation:
        if not resolution_ref.strip():
            raise ValueError("review resolution requires an owning-subsystem resolution ref")
        if not basis_refs:
            raise ValueError("review resolution requires basis refs")
        row = self.ledger.project_get("qualification.review-obligation", obligation_id)
        if row is None:
            raise KeyError(obligation_id)
        value, version = row
        status = str(value.get("status", "open"))
        if status == "resolved":
            if value.get("resolution_ref") != resolution_ref:
                raise ValueError("review resolution identity rebound")
            return self._obligation_from_value(value)
        if status != "assessed":
            raise ValueError("review obligation must be assessed before resolution")
        disposition = str(value.get("disposition", ""))
        if disposition == "continue":
            raise ValueError("continue assessment resolves the review directly")
        updated = dict(value)
        updated["status"] = "resolved"
        updated["resolution_ref"] = resolution_ref
        updated["resolution_basis_refs"] = list(basis_refs)
        with self.ledger.transaction():
            self.ledger.project_put(
                "qualification.review-obligation",
                obligation_id,
                updated,
                expected_version=version,
            )
            self.ledger.append(
                stream=f"qualification-review:{obligation_id}",
                kind="qualification.review.resolved",
                payload={
                    "obligation_id": obligation_id,
                    "assessment_id": value.get("assessment_id"),
                    "disposition": disposition,
                    "resolution_ref": resolution_ref,
                    "basis_refs": list(basis_refs),
                },
            )
        return self._obligation_from_value(updated)

    def supersede_dependency_after_review(
        self,
        dependency_id: str,
        *,
        obligation_id: str,
        assessment_id: str,
        new_version: str,
        basis_refs: tuple[str, ...],
        successor_id: str | None = None,
    ) -> QualificationDependency:
        previous = self.get_dependency(dependency_id)
        obligation = self.get_obligation(obligation_id)
        assessment = self.get_assessment(assessment_id)
        if obligation.dependency_id != dependency_id:
            raise ValueError("review obligation does not apply to qualification dependency")
        if assessment.obligation_id != obligation_id:
            raise ValueError("revalidation assessment does not apply to review obligation")
        if obligation.status != "resolved":
            raise ValueError("review obligation must be resolved before dependency replacement")
        if obligation.observed_version != new_version:
            raise ValueError("dependency replacement must use reviewed observed version")
        return self.register_dependency(
            principal=previous.principal,
            subject_ref=previous.subject_ref,
            dependency_ref=previous.dependency_ref,
            dependency_version=new_version,
            assumption=previous.assumption,
            scope=previous.scope,
            review_policy=previous.review_policy,
            basis_refs=basis_refs,
            dependency_id=successor_id,
            supersedes_dependency_id=dependency_id,
        )

    def get_dependency(self, dependency_id: str) -> QualificationDependency:
        row = self.ledger.project_get("qualification.dependency", dependency_id)
        if row is None:
            raise KeyError(dependency_id)
        value = row[0]
        return QualificationDependency(
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
            supersedes_dependency_id=(
                str(value["supersedes_dependency_id"])
                if value.get("supersedes_dependency_id")
                else None
            ),
        )

    def get_obligation(self, obligation_id: str) -> ReviewObligation:
        row = self.ledger.project_get("qualification.review-obligation", obligation_id)
        if row is None:
            raise KeyError(obligation_id)
        return self._obligation_from_value(row[0])

    def get_assessment(self, assessment_id: str) -> RevalidationAssessment:
        row = self.ledger.project_get("qualification.revalidation-assessment", assessment_id)
        if row is None:
            raise KeyError(assessment_id)
        value = row[0]
        return RevalidationAssessment(
            id=str(value["id"]),
            obligation_id=str(value["obligation_id"]),
            disposition=str(value["disposition"]),
            basis_refs=tuple(str(v) for v in value.get("basis_refs", [])),
            rationale=str(value.get("rationale", "")),
        )

    def pending_obligations(
        self,
        *,
        principal: str | None = None,
        subject_ref: str | None = None,
    ) -> tuple[ReviewObligation, ...]:
        items: list[ReviewObligation] = []
        seen: set[str] = set()
        for event in self.ledger.events(kind="qualification.review.required"):
            obligation_id = str(event.payload.get("id", ""))
            if not obligation_id or obligation_id in seen:
                continue
            seen.add(obligation_id)
            obligation = self.get_obligation(obligation_id)
            if obligation.status == "resolved":
                continue
            if principal is not None and obligation.principal != principal:
                continue
            if subject_ref is not None and obligation.subject_ref != subject_ref:
                continue
            items.append(obligation)
        return tuple(items)

    def open_obligations(
        self,
        *,
        principal: str | None = None,
        subject_ref: str | None = None,
    ) -> tuple[ReviewObligation, ...]:
        return tuple(
            item
            for item in self.pending_obligations(
                principal=principal,
                subject_ref=subject_ref,
            )
            if item.status == "open"
        )

    @staticmethod
    def _obligation_id(dependency_id: str, observed_version: str) -> str:
        digest = sha256(f"{dependency_id}\0{observed_version}".encode("utf-8")).hexdigest()[:24]
        return f"review-obligation:{digest}"

    @staticmethod
    def _dependency_value(item: QualificationDependency) -> dict[str, object]:
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
            "supersedes_dependency_id": item.supersedes_dependency_id,
        }

    @staticmethod
    def _obligation_value(item: ReviewObligation) -> dict[str, object]:
        return {
            "id": item.id,
            "principal": item.principal,
            "dependency_id": item.dependency_id,
            "subject_ref": item.subject_ref,
            "dependency_ref": item.dependency_ref,
            "previous_version": item.previous_version,
            "observed_version": item.observed_version,
            "reason": item.reason,
            "required_action": item.required_action,
            "basis_refs": list(item.basis_refs),
            "status": item.status,
        }

    @staticmethod
    def _obligation_from_value(value: Mapping[str, object]) -> ReviewObligation:
        return ReviewObligation(
            id=str(value["id"]),
            principal=str(value["principal"]),
            dependency_id=str(value["dependency_id"]),
            subject_ref=str(value["subject_ref"]),
            dependency_ref=str(value["dependency_ref"]),
            previous_version=str(value["previous_version"]),
            observed_version=str(value["observed_version"]),
            reason=str(value.get("reason", "")),
            required_action=str(value.get("required_action", "review")),
            basis_refs=tuple(str(v) for v in value.get("basis_refs", [])),
            status=str(value.get("status", "open")),
            assessment_id=(str(value["assessment_id"]) if value.get("assessment_id") else None),
            disposition=(str(value["disposition"]) if value.get("disposition") else None),
            resolution_ref=(str(value["resolution_ref"]) if value.get("resolution_ref") else None),
        )


__all__ = [
    "QualificationDependency",
    "QualificationService",
    "ReviewObligation",
    "RevalidationAssessment",
]
