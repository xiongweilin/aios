from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Iterable, Mapping

from semantic_language import (
    Evidence,
    Responsibility,
    SemanticKind,
    SemanticRef,
)

from .epistemics import (
    ClaimRevision,
    EvidenceAssessment,
    EvidencePredicate,
    EvidenceRelation,
    EvidenceRequirement,
    EvaluatorKind,
    FalsificationCondition,
)
from .runtime import WorldRuntime


class MigrationDisposition(StrEnum):
    MAPPED = "mapped"
    INTENTIONALLY_SKIPPED = "intentionally-skipped"
    UNRESOLVED = "unresolved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ReconciliationEntry:
    source: str
    namespace: str
    source_id: str
    disposition: MigrationDisposition
    target_refs: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True, slots=True)
class MigrationReport:
    source: str
    total: int
    mapped: int
    intentionally_skipped: int
    unresolved: int
    rejected: int
    entries: tuple[ReconciliationEntry, ...]

    @property
    def deletion_ready(self) -> bool:
        return self.unresolved == 0 and self.rejected == 0


@dataclass(frozen=True, slots=True)
class _SourceRecord:
    namespace: str
    source_id: str
    value: Mapping[str, Any]


class SemanticMigrator:
    """Source-specific semantic migration into canonical Runtime state.

    A record counts as mapped only after the target Runtime invariant has been
    validated and canonical state has been written. Unknown source semantics are
    unresolved rather than hidden inside an opaque envelope.
    """

    SUPPORTED_SOURCES = frozenset({"agent-kernel", "meta-controller", "world-state"})

    def __init__(self, runtime: WorldRuntime) -> None:
        self.runtime = runtime
        self._target_by_source: dict[tuple[str, str], str] = {}
        self._current_source_index: dict[str, dict[str, _SourceRecord]] = {}

    def import_records(
        self,
        source: str,
        records: Iterable[Mapping[str, Any]],
    ) -> MigrationReport:
        if source not in self.SUPPORTED_SOURCES:
            raise ValueError("unsupported migration source")
        normalized = tuple(self._normalize(record) for record in records)
        index = self._index(normalized)
        self._current_source_index = index
        entries: list[ReconciliationEntry] = []
        for record in self._ordered(source, normalized):
            existing = self._existing_terminal(source, record)
            if existing is not None:
                entries.append(existing)
                continue
            try:
                if source == "agent-kernel":
                    entry = self._map_agent_kernel(record, index)
                elif source == "meta-controller":
                    entry = self._map_meta_controller(record)
                else:
                    entry = self._map_world_state(record)
            except (KeyError, TypeError, ValueError) as exc:
                entry = self._entry(
                    source,
                    record,
                    MigrationDisposition.REJECTED,
                    reason=str(exc),
                )
            self._record(entry)
            entries.append(entry)
        return self._report(source, entries)

    @staticmethod
    def _normalize(record: Mapping[str, Any]) -> _SourceRecord:
        namespace = str(record.get("namespace", "")).strip()
        raw = record.get("record", record.get("payload"))
        if not namespace:
            raise ValueError("migration record requires namespace")
        if not isinstance(raw, Mapping):
            raise ValueError("migration record requires mapping record/payload")
        source_id = str(record.get("id") or raw.get("id") or "").strip()
        if not source_id:
            raise ValueError("migration record requires stable source id")
        return _SourceRecord(namespace, source_id, dict(raw))

    @staticmethod
    def _index(records: tuple[_SourceRecord, ...]) -> dict[str, dict[str, _SourceRecord]]:
        result: dict[str, dict[str, _SourceRecord]] = {}
        for record in records:
            result.setdefault(record.namespace, {})[record.source_id] = record
        return result

    @staticmethod
    def _ordered(
        source: str, records: tuple[_SourceRecord, ...]
    ) -> tuple[_SourceRecord, ...]:
        if source == "agent-kernel":
            priority = {
                "responsibility": 0,
                "evidence": 1,
                "work": 2,
                "run": 3,
            }

            def agent_key(item: _SourceRecord) -> tuple[int, int, str]:
                responsibility_priority = 50
                if item.namespace == "responsibility":
                    object_type = str(item.value.get("object_type", ""))
                    responsibility_priority = {
                        "StandingResponsibility": 0,
                        "ResponsibilityAdmission": 1,
                    }.get(object_type, 10)
                return (
                    priority.get(item.namespace, 50),
                    responsibility_priority,
                    item.source_id,
                )

            return tuple(sorted(records, key=agent_key))

        if source == "world-state":
            priority = {
                "claim_revision": 0,
                "claim": 1,
                "evidence": 2,
                "assessment": 3,
                "unknown_revision": 4,
                "conflict_revision": 5,
                "revision": 6,
                "belief_verdict": 7,
            }

            def world_state_key(item: _SourceRecord) -> tuple[int, int, str]:
                sequence = 0
                if item.namespace == "claim_revision":
                    sequence = int(item.value.get("revisionNumber", 0))
                return (priority.get(item.namespace, 50), sequence, item.source_id)

            return tuple(sorted(records, key=world_state_key))

        return records

    def _existing_terminal(
        self, source: str, record: _SourceRecord
    ) -> ReconciliationEntry | None:
        key = self._migration_key(source, record)
        current = self.runtime.ledger.project_get("migration.reconciliation", key)
        if current is None:
            return None
        value = current[0]
        disposition = MigrationDisposition(str(value["disposition"]))
        if disposition not in {
            MigrationDisposition.MAPPED,
            MigrationDisposition.INTENTIONALLY_SKIPPED,
        }:
            return None
        return ReconciliationEntry(
            source=source,
            namespace=record.namespace,
            source_id=record.source_id,
            disposition=disposition,
            target_refs=tuple(str(item) for item in value.get("target_refs", [])),
            reason=str(value.get("reason", "")),
        )

    def _map_agent_kernel(
        self,
        record: _SourceRecord,
        index: dict[str, dict[str, _SourceRecord]],
    ) -> ReconciliationEntry:
        value = record.value
        if record.namespace == "responsibility":
            object_type = str(value.get("object_type", ""))
            if object_type == "StandingResponsibility":
                admissions = [
                    candidate
                    for candidate in index.get("responsibility", {}).values()
                    if candidate.value.get("object_type") == "ResponsibilityAdmission"
                    and candidate.value.get("responsibility_ref") == record.source_id
                ]
                if len(admissions) != 1:
                    return self._entry(
                        "agent-kernel",
                        record,
                        MigrationDisposition.UNRESOLVED,
                        reason=(
                            "StandingResponsibility requires exactly one ResponsibilityAdmission "
                            "to recover the authoritative principal"
                        ),
                    )
                admission = admissions[0].value
                principal = str(admission.get("principal_ref", "")).strip()
                statement = str(value.get("statement", "")).strip()
                if not principal or not statement:
                    raise ValueError("legacy responsibility has empty principal or statement")
                try:
                    current = self.runtime.responsibility.get(record.source_id)
                except KeyError:
                    current = self.runtime.responsibility.create(
                        Responsibility(
                            id=record.source_id,
                            principal=principal,
                            subject=statement,
                            scope={
                                **dict(value.get("scope", {})),
                                "legacy_responsibility_kind": str(
                                    value.get("responsibility_kind", "")
                                ),
                            },
                            metadata={
                                "migration_source": "agent-kernel",
                                "migration_source_id": record.source_id,
                            },
                        ),
                        domain=str(
                            dict(value.get("scope", {})).get("domain", "legacy")
                        ),
                    )
                else:
                    if current.principal != principal or current.subject != statement:
                        raise ValueError(
                            "legacy responsibility identity conflicts with Runtime state"
                        )
                target = f"responsibility:{current.id}"
                self._target_by_source[("responsibility", record.source_id)] = current.id
                return self._entry(
                    "agent-kernel",
                    record,
                    MigrationDisposition.MAPPED,
                    target_refs=(target,),
                )
            if object_type == "ResponsibilityAdmission":
                target_id = str(value.get("responsibility_ref", "")).strip()
                try:
                    self.runtime.responsibility.get(target_id)
                except KeyError:
                    return self._entry(
                        "agent-kernel",
                        record,
                        MigrationDisposition.UNRESOLVED,
                        reason="admission cannot be folded until responsibility is mapped",
                    )
                return self._entry(
                    "agent-kernel",
                    record,
                    MigrationDisposition.MAPPED,
                    target_refs=(f"responsibility:{target_id}",),
                    reason="principal admission folded into canonical responsibility identity",
                )
            return self._entry(
                "agent-kernel",
                record,
                MigrationDisposition.UNRESOLVED,
                reason=f"no canonical migration rule for responsibility object {object_type!r}",
            )

        if record.namespace == "evidence":
            subject_refs = value.get("subject_refs", [])
            if not isinstance(subject_refs, list) or not subject_refs:
                return self._entry(
                    "agent-kernel",
                    record,
                    MigrationDisposition.UNRESOLVED,
                    reason="legacy Evidence has no subject_ref to anchor canonical evidence",
                )
            evidence = Evidence(
                id=record.source_id,
                subject=str(subject_refs[0]),
                source=str(value.get("source", "agent-kernel")),
                observed_at=self._datetime(value.get("observed_at")),
                content={
                    "kind": value.get("kind"),
                    "artifact_refs": list(value.get("artifact_refs", [])),
                    "legacy_status": value.get("status"),
                },
                metadata={
                    "migration_source": "agent-kernel",
                    "legacy_subject_refs": list(subject_refs),
                },
            )
            current = self.runtime.ledger.project_get("epistemics.evidence", evidence.id)
            if current is None:
                self.runtime.epistemics.record_evidence(evidence)
            target = f"evidence:{evidence.id}"
            self._target_by_source[("evidence", record.source_id)] = evidence.id
            return self._entry(
                "agent-kernel",
                record,
                MigrationDisposition.MAPPED,
                target_refs=(target,),
            )

        if record.namespace == "work":
            metadata = dict(value.get("metadata", {}))
            responsibility_id = str(
                metadata.get("responsibility_ref")
                or metadata.get("standing_responsibility_ref")
                or value.get("responsibility_id")
                or ""
            ).strip()
            if not responsibility_id:
                return self._entry(
                    "agent-kernel",
                    record,
                    MigrationDisposition.UNRESOLVED,
                    reason="legacy Work does not identify its standing responsibility",
                )
            try:
                self.runtime.responsibility.get(responsibility_id)
            except KeyError:
                return self._entry(
                    "agent-kernel",
                    record,
                    MigrationDisposition.UNRESOLVED,
                    reason="legacy Work references an unmapped responsibility",
                )
            work = self.runtime.execution.admit_work(
                responsibility_id=responsibility_id,
                kind=str(value.get("kind", "legacy-work")),
                payload={
                    "title": value.get("title"),
                    "description": value.get("description"),
                    "constraints": dict(value.get("constraints", {})),
                    "acceptance_criteria": list(value.get("acceptance_criteria", [])),
                    "requested_capabilities": list(value.get("requested_capabilities", [])),
                    "metadata": {
                        **metadata,
                        "migration_source": "agent-kernel",
                        "migration_source_id": record.source_id,
                    },
                },
            )
            self._target_by_source[("work", record.source_id)] = work.id
            return self._entry(
                "agent-kernel",
                record,
                MigrationDisposition.MAPPED,
                target_refs=(f"work:{work.id}",),
            )

        if record.namespace == "run":
            legacy_work_id = str(value.get("work_id", "")).strip()
            target_work_id = self._target_by_source.get(("work", legacy_work_id))
            if not target_work_id:
                return self._entry(
                    "agent-kernel",
                    record,
                    MigrationDisposition.UNRESOLVED,
                    reason="legacy Run references Work that was not semantically mapped",
                )
            run = self.runtime.start_run(
                target_work_id,
                workflow_id=str(value.get("workflow_id", "legacy-run")),
            )
            status = str(value.get("status", "running"))
            if status not in {"queued", "running"}:
                mapped_status = "completed" if status == "succeeded" else status
                run = self.runtime.execution.update_run_status(run.id, mapped_status)
            self._target_by_source[("run", record.source_id)] = run.id
            return self._entry(
                "agent-kernel",
                record,
                MigrationDisposition.MAPPED,
                target_refs=(f"run:{run.id}",),
            )

        return self._entry(
            "agent-kernel",
            record,
            MigrationDisposition.UNRESOLVED,
            reason=f"no canonical migration rule for namespace {record.namespace!r}",
        )

    def _map_meta_controller(self, record: _SourceRecord) -> ReconciliationEntry:
        if record.namespace != "meta_policy_event":
            return self._entry(
                "meta-controller",
                record,
                MigrationDisposition.UNRESOLVED,
                reason=f"no canonical migration rule for namespace {record.namespace!r}",
            )
        value = record.value
        event_type = str(value.get("event_type", "")).strip()
        mapping = {
            "EpistemicAssessmentRecorded": "cognition.epistemic-assessment.recorded",
            "MetaControlIntentSelected": "cognition.meta-control-intent.selected",
        }
        target_kind = mapping.get(event_type)
        if target_kind is None:
            return self._entry(
                "meta-controller",
                record,
                MigrationDisposition.UNRESOLVED,
                reason=f"unknown meta-policy event type {event_type!r}",
            )
        controller_ref = str(value.get("controller_ref", "")).strip()
        policy_version = str(value.get("policy_version", "")).strip()
        if not controller_ref or not policy_version:
            raise ValueError("meta-policy event lacks controller_ref or policy_version")
        event = self.runtime.ledger.append(
            stream=f"cognition:{controller_ref}",
            kind=target_kind,
            payload={
                "controller_ref": controller_ref,
                "state_version": int(value.get("kernel_state_version", 0)),
                "policy_version": policy_version,
                "payload": dict(value.get("payload", {})),
                "basis_refs": list(value.get("basis_refs", [])),
                "migration_source_id": record.source_id,
            },
            valid_at=self._datetime(value.get("created_at")),
        )
        return self._entry(
            "meta-controller",
            record,
            MigrationDisposition.MAPPED,
            target_refs=(f"event:{event.id}",),
        )

    def _map_world_state(self, record: _SourceRecord) -> ReconciliationEntry:
        value = record.value

        if record.namespace == "claim_revision":
            claim_id = str(value.get("claimId", "")).strip()
            if not claim_id:
                raise ValueError("world-state ClaimRevision requires claimId")
            valid_time = dict(value.get("validTime", {}))
            source_claim = None
            for candidate in self._current_source_index.get("claim", {}).values():
                if candidate.source_id == claim_id:
                    source_claim = candidate.value
                    break
            requirements = tuple(
                self._world_state_requirement(item)
                for item in value.get("evidenceRequirements", [])
                if isinstance(item, Mapping)
            )
            falsifiers = tuple(
                self._world_state_falsifier(item)
                for item in value.get("falsificationConditions", [])
                if isinstance(item, Mapping)
            )
            proposition = json.dumps(
                {
                    "predicate": value.get("predicate"),
                    "value": value.get("value"),
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            metadata = {
                "migration_source": "world-state",
                "world_state_kind": value.get("kind"),
                "world_state_predicate": value.get("predicate"),
                "world_state_value": value.get("value"),
                "world_state_anchors": dict(value.get("anchors", {})),
            }
            if source_claim is not None:
                metadata.update(
                    {
                        "world_state_key": source_claim.get("key"),
                        "world_state_created_at": source_claim.get("createdAt"),
                        "world_state_created_by": source_claim.get("createdBy"),
                    }
                )
            revision = ClaimRevision(
                id=record.source_id,
                claim_id=claim_id,
                revision_number=int(value.get("revisionNumber", 0)),
                subject=str(value.get("subject", "")),
                proposition=proposition,
                scope=dict(value.get("scope", {})),
                declared_status=str(value.get("status", "unknown")),
                criticality=str(value.get("criticality", "material")),
                evidence_requirements=requirements,
                falsification_conditions=falsifiers,
                valid_from=self._required_datetime(
                    valid_time.get("from"),
                    "ClaimRevision.validTime.from",
                ),
                valid_to=self._datetime(valid_time.get("to")),
                previous_revision_id=(
                    str(value["previousRevisionId"])
                    if value.get("previousRevisionId")
                    else None
                ),
                cause_type=(
                    str(value["causeType"]) if value.get("causeType") else None
                ),
                cause_id=str(value["causeId"]) if value.get("causeId") else None,
                actor=str(value.get("actor", "world-state:migration")),
                recorded_at=self._required_datetime(
                    value.get("recordedAt"),
                    "ClaimRevision.recordedAt",
                ),
                metadata=metadata,
            )
            self.runtime.epistemics.import_claim_revision(revision)
            self._target_by_source[("claim_revision", record.source_id)] = revision.id
            self._target_by_source[("claim", claim_id)] = claim_id
            return self._entry(
                "world-state",
                record,
                MigrationDisposition.MAPPED,
                target_refs=(
                    f"claim:{claim_id}",
                    f"claim-revision:{revision.id}",
                ),
            )

        if record.namespace == "claim":
            claim_id = record.source_id
            if self.runtime.ledger.project_get("epistemics.claim", claim_id) is None:
                return self._entry(
                    "world-state",
                    record,
                    MigrationDisposition.UNRESOLVED,
                    reason="Claim has no migrated ClaimRevision",
                )
            return self._entry(
                "world-state",
                record,
                MigrationDisposition.MAPPED,
                target_refs=(f"claim:{claim_id}",),
                reason="claim identity metadata folded into canonical ClaimRevision",
            )

        if record.namespace == "evidence":
            valid_time = dict(value.get("validTime", {}))
            provenance = dict(value.get("provenance", {}))
            parent_ids = provenance.get("parentEvidenceIds", [])
            if not isinstance(parent_ids, list):
                parent_ids = []
            evidence = Evidence(
                id=record.source_id,
                subject=str(
                    dict(value.get("scope", {})).get("subject")
                    or value.get("locator")
                    or record.source_id
                ),
                source=str(value.get("source", "world-state")),
                observed_at=self._datetime(value.get("recordedAt")),
                valid_from=self._datetime(valid_time.get("from")),
                valid_to=self._datetime(valid_time.get("to")),
                derived_from=tuple(
                    SemanticRef(SemanticKind.EVIDENCE, str(item))
                    for item in parent_ids
                ),
                content={
                    "kind": value.get("kind"),
                    "locator": value.get("locator"),
                    "scope": dict(value.get("scope", {})),
                    "content_hash": value.get("contentHash"),
                    "data": dict(value.get("data", {})),
                    "provenance": provenance,
                },
                metadata={
                    "migration_source": "world-state",
                    "external_id": value.get("externalId"),
                    "idempotency_key": value.get("idempotencyKey"),
                    "kind": value.get("kind"),
                    "scope": dict(value.get("scope", {})),
                    "provenance_class": provenance.get("class"),
                    "content_hash": value.get("contentHash"),
                },
            )
            current = self.runtime.ledger.project_get("epistemics.evidence", evidence.id)
            if current is None:
                self.runtime.epistemics.record_evidence(evidence)
            return self._entry(
                "world-state",
                record,
                MigrationDisposition.MAPPED,
                target_refs=(f"evidence:{evidence.id}",),
            )

        if record.namespace == "assessment":
            claim_revision_id = str(value.get("claimRevisionId", "")).strip()
            evidence_id = str(value.get("evidenceId", "")).strip()
            revision_row = self.runtime.ledger.project_get(
                "epistemics.claim-revision",
                claim_revision_id,
            )
            if revision_row is None:
                return self._entry(
                    "world-state",
                    record,
                    MigrationDisposition.UNRESOLVED,
                    reason="Assessment references an unmapped ClaimRevision",
                )
            if self.runtime.ledger.project_get("epistemics.evidence", evidence_id) is None:
                return self._entry(
                    "world-state",
                    record,
                    MigrationDisposition.UNRESOLVED,
                    reason="Assessment references unmapped Evidence",
                )
            revision = self.runtime.epistemics._claim_revision_from_value(
                revision_row[0]
            )
            raw_relation = str(value.get("result", "inconclusive"))
            try:
                relation = EvidenceRelation(raw_relation)
            except ValueError as exc:
                raise ValueError(
                    f"unsupported world-state assessment result: {raw_relation}"
                ) from exc
            evaluator = dict(value.get("evaluator", {}))
            evaluator_name = str(evaluator.get("name", "")).strip()
            raw_evaluator_kind = str(evaluator.get("kind", "")).strip().lower()
            evaluator_version = str(evaluator.get("version", "")).strip()
            evaluator_kind = {
                "deterministic": EvaluatorKind.DETERMINISTIC,
                "human": EvaluatorKind.HUMAN,
                "model": EvaluatorKind.MODEL,
                "domain_verifier": EvaluatorKind.DOMAIN_VERIFIER,
                "domain-verifier": EvaluatorKind.DOMAIN_VERIFIER,
            }.get(raw_evaluator_kind, EvaluatorKind.MODEL)
            assessed_by = ":".join(
                item
                for item in (raw_evaluator_kind, evaluator_name, evaluator_version)
                if item
            ) or "world-state:migration"
            assessment = EvidenceAssessment(
                id=record.source_id,
                claim_ref=SemanticRef(SemanticKind.CLAIM, revision.claim_id),
                claim_revision_id=revision.id,
                evidence_ref=SemanticRef(SemanticKind.EVIDENCE, evidence_id),
                relation=relation,
                rationale=str(
                    value.get("reason")
                    or value.get("reasonCode")
                    or "world-state assessment"
                ),
                assessed_by=assessed_by,
                evaluator_kind=evaluator_kind,
                assessed_at=self._required_datetime(
                    value.get("recordedAt"),
                    "Assessment.recordedAt",
                ),
                evaluated_scope=dict(value.get("evaluatedScope", {})),
                unevaluated_scope=dict(value.get("unevaluatedScope", {})),
            )
            self.runtime.epistemics.import_assessment(assessment)
            return self._entry(
                "world-state",
                record,
                MigrationDisposition.MAPPED,
                target_refs=(f"assessment:{assessment.id}",),
            )

        if record.namespace == "unknown_revision":
            return self._map_world_state_unknown_revision(record)

        if record.namespace == "conflict_revision":
            return self._map_world_state_conflict_revision(record)

        if record.namespace == "revision":
            claim_id = str(value.get("claimId", "")).strip()
            claim_revision_id = str(value.get("claimRevisionId", "")).strip()
            if self.runtime.ledger.project_get(
                "epistemics.claim-revision",
                claim_revision_id,
            ) is None:
                return self._entry(
                    "world-state",
                    record,
                    MigrationDisposition.UNRESOLVED,
                    reason="Revision references an unmapped ClaimRevision",
                )
            payload = {
                "id": record.source_id,
                "claim_id": claim_id,
                "claim_revision_id": claim_revision_id,
                "from_status": value.get("fromStatus"),
                "to_status": value.get("toStatus"),
                "effective_at": value.get("effectiveAt"),
                "triggered_by": list(value.get("triggeredBy", [])),
                "actor": value.get("actor"),
                "migration_source": "world-state",
            }
            event = self.runtime.ledger.append(
                stream=f"claim:{claim_id}",
                kind="epistemics.belief.revision-recorded",
                payload=payload,
                event_id=f"world-state:{record.source_id}",
                valid_at=self._required_datetime(
                    value.get("effectiveAt"),
                    "Revision.effectiveAt",
                ),
                recorded_at=self._required_datetime(
                    value.get("recordedAt"),
                    "Revision.recordedAt",
                ),
            )
            return self._entry(
                "world-state",
                record,
                MigrationDisposition.MAPPED,
                target_refs=(f"event:{event.id}",),
                reason="historical belief transition preserved as append-only audit",
            )

        if record.namespace == "belief_verdict":
            claim_id = str(value.get("claimId", "")).strip()
            if claim_id and self.runtime.ledger.project_get(
                "epistemics.claim",
                claim_id,
            ) is None:
                return self._entry(
                    "world-state",
                    record,
                    MigrationDisposition.UNRESOLVED,
                    reason="BeliefVerdict references an unmapped Claim",
                )
            return self._entry(
                "world-state",
                record,
                MigrationDisposition.INTENTIONALLY_SKIPPED,
                target_refs=(f"belief:{claim_id}",) if claim_id else (),
                reason=(
                    "BeliefVerdict is a derived projection; World Runtime recomputes "
                    "belief from canonical revisions and assessments"
                ),
            )

        return self._entry(
            "world-state",
            record,
            MigrationDisposition.UNRESOLVED,
            reason=f"no canonical migration rule for namespace {record.namespace!r}",
        )

    def _map_world_state_unknown_revision(
        self,
        record: _SourceRecord,
    ) -> ReconciliationEntry:
        value = record.value
        unknown_id = str(value.get("unknownId", "")).strip()
        if not unknown_id:
            raise ValueError("UnknownRevision requires unknownId")
        blocks = [str(item) for item in value.get("blocks", [])]
        status = str(value.get("status", "open"))
        if status not in {"open", "resolved"}:
            raise ValueError("UnknownRevision status must be open or resolved")
        current = self.runtime.ledger.project_get("epistemics.unknown", unknown_id)
        projection = {
            "id": unknown_id,
            "subject": blocks[0] if blocks else "",
            "question": str(value.get("question", "")),
            "status": status,
            "blocks": [
                {"kind": SemanticKind.CLAIM.value, "id": item} for item in blocks
            ],
            "resolution_condition": value.get("resolutionCondition"),
            "suggested_evidence": list(value.get("suggestedEvidence", [])),
            "cause": dict(value.get("cause", {})),
            "resolution": value.get("resolution"),
            "actor": value.get("actor"),
            "current_revision_id": record.source_id,
            "migration_source": "world-state",
        }
        recorded_at = self._required_datetime(
            value.get("recordedAt"),
            "UnknownRevision.recordedAt",
        )
        kind = (
            "epistemics.unknown.resolved"
            if status == "resolved"
            else "epistemics.unknown.opened"
            if current is None
            else "epistemics.unknown.revised"
        )
        with self.runtime.ledger.transaction():
            self.runtime.ledger.project_put(
                "epistemics.unknown",
                unknown_id,
                projection,
                expected_version=current[1] if current is not None else None,
            )
            event = self.runtime.ledger.append(
                stream=f"unknown:{unknown_id}",
                kind=kind,
                payload=projection,
                event_id=f"world-state:{record.source_id}",
                valid_at=recorded_at,
                recorded_at=recorded_at,
            )
        return self._entry(
            "world-state",
            record,
            MigrationDisposition.MAPPED,
            target_refs=(f"unknown:{unknown_id}", f"event:{event.id}"),
        )

    def _map_world_state_conflict_revision(
        self,
        record: _SourceRecord,
    ) -> ReconciliationEntry:
        value = record.value
        conflict_id = str(value.get("conflictId", "")).strip()
        claim_id = str(value.get("claimId", "")).strip()
        assessment_ids = [str(item) for item in value.get("assessmentIds", [])]
        if not conflict_id or not claim_id:
            raise ValueError("ConflictRevision requires conflictId and claimId")
        missing = [
            item
            for item in assessment_ids
            if item not in self._current_source_index.get("assessment", {})
        ]
        if missing:
            return self._entry(
                "world-state",
                record,
                MigrationDisposition.UNRESOLVED,
                reason="ConflictRevision references unknown Assessment ids",
            )
        evidence_ids = [
            str(
                self._current_source_index["assessment"][assessment_id].value.get(
                    "evidenceId",
                    "",
                )
            )
            for assessment_id in assessment_ids
        ]
        members = [
            {"kind": SemanticKind.EVIDENCE.value, "id": item}
            for item in evidence_ids
            if item
        ]
        status = str(value.get("status", "open"))
        if status not in {"open", "resolved"}:
            raise ValueError("ConflictRevision status must be open or resolved")
        current = self.runtime.ledger.project_get("epistemics.conflict", conflict_id)
        projection = {
            "id": conflict_id,
            "subject": claim_id,
            "members": members,
            "description": f"world-state conflict severity={value.get('severity', 'material')}",
            "status": status,
            "claim_id": claim_id,
            "assessment_ids": assessment_ids,
            "severity": value.get("severity"),
            "resolution": value.get("resolution"),
            "resolved_by": value.get("actor") if status == "resolved" else None,
            "current_revision_id": record.source_id,
            "migration_source": "world-state",
        }
        recorded_at = self._required_datetime(
            value.get("recordedAt"),
            "ConflictRevision.recordedAt",
        )
        kind = (
            "epistemics.conflict.resolved"
            if status == "resolved"
            else "epistemics.conflict.opened"
            if current is None
            else "epistemics.conflict.revised"
        )
        with self.runtime.ledger.transaction():
            self.runtime.ledger.project_put(
                "epistemics.conflict",
                conflict_id,
                projection,
                expected_version=current[1] if current is not None else None,
            )
            event = self.runtime.ledger.append(
                stream=f"conflict:{conflict_id}",
                kind=kind,
                payload=projection,
                event_id=f"world-state:{record.source_id}",
                valid_at=recorded_at,
                recorded_at=recorded_at,
            )
        return self._entry(
            "world-state",
            record,
            MigrationDisposition.MAPPED,
            target_refs=(f"conflict:{conflict_id}", f"event:{event.id}"),
        )

    @staticmethod
    def _world_state_requirement(value: Mapping[str, Any]) -> EvidenceRequirement:
        raw = value.get("supportPredicate")
        predicate = (
            EvidencePredicate(
                path=str(raw.get("path", "")),
                op=str(raw.get("op", "")),
                value=raw.get("value"),
            )
            if isinstance(raw, Mapping)
            else None
        )
        return EvidenceRequirement(
            id=str(value.get("id", "")),
            kinds=tuple(str(item) for item in value.get("kinds", [])),
            provenance=tuple(str(item) for item in value.get("provenance", [])),
            scope=dict(value.get("scope", {})),
            freshness_seconds=(
                int(value["freshnessSeconds"])
                if value.get("freshnessSeconds") is not None
                else None
            ),
            mandatory=bool(value.get("mandatory", True)),
            support_predicate=predicate,
        )

    @staticmethod
    def _world_state_falsifier(value: Mapping[str, Any]) -> FalsificationCondition:
        raw = value.get("predicate")
        predicate = (
            EvidencePredicate(
                path=str(raw.get("path", "")),
                op=str(raw.get("op", "")),
                value=raw.get("value"),
            )
            if isinstance(raw, Mapping)
            else None
        )
        return FalsificationCondition(
            id=str(value.get("id", "")),
            description=str(value.get("description", "")),
            evidence_kind=(
                str(value["evidenceKind"])
                if value.get("evidenceKind") is not None
                else None
            ),
            predicate=predicate,
        )


    @classmethod
    def _required_datetime(cls, value: object, field_name: str) -> datetime:
        parsed = cls._datetime(value)
        if parsed is None:
            raise ValueError(f"{field_name} is required")
        return parsed

    @staticmethod
    def _datetime(value: object) -> datetime | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    @staticmethod
    def _migration_key(source: str, record: _SourceRecord) -> str:
        return f"{source}:{record.namespace}:{record.source_id}"

    def _record(self, entry: ReconciliationEntry) -> None:
        value = {
            "source": entry.source,
            "namespace": entry.namespace,
            "source_id": entry.source_id,
            "disposition": entry.disposition.value,
            "target_refs": list(entry.target_refs),
            "reason": entry.reason,
        }
        key = f"{entry.source}:{entry.namespace}:{entry.source_id}"
        current = self.runtime.ledger.project_get("migration.reconciliation", key)
        if current is None:
            self.runtime.ledger.project_put("migration.reconciliation", key, value)
        else:
            self.runtime.ledger.project_put(
                "migration.reconciliation",
                key,
                value,
                expected_version=current[1],
            )
        self.runtime.ledger.append(
            stream=f"migration:{entry.source}",
            kind=f"migration.record.{entry.disposition.value}",
            payload=value,
        )

    @staticmethod
    def _entry(
        source: str,
        record: _SourceRecord,
        disposition: MigrationDisposition,
        *,
        target_refs: tuple[str, ...] = (),
        reason: str = "",
    ) -> ReconciliationEntry:
        return ReconciliationEntry(
            source=source,
            namespace=record.namespace,
            source_id=record.source_id,
            disposition=disposition,
            target_refs=target_refs,
            reason=reason,
        )

    @staticmethod
    def _report(
        source: str, entries: list[ReconciliationEntry]
    ) -> MigrationReport:
        return MigrationReport(
            source=source,
            total=len(entries),
            mapped=sum(item.disposition is MigrationDisposition.MAPPED for item in entries),
            intentionally_skipped=sum(
                item.disposition is MigrationDisposition.INTENTIONALLY_SKIPPED
                for item in entries
            ),
            unresolved=sum(
                item.disposition is MigrationDisposition.UNRESOLVED for item in entries
            ),
            rejected=sum(
                item.disposition is MigrationDisposition.REJECTED for item in entries
            ),
            entries=tuple(entries),
        )


__all__ = [
    "MigrationDisposition",
    "MigrationReport",
    "ReconciliationEntry",
    "SemanticMigrator",
]
