from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from personal_world.model.contracts import (
    Claim,
    ClaimCreate,
    ContextProjection,
    ContextProjectionRequest,
    DataAccessProfile,
    DisclosureAudit,
    DomainPersonalProjection,
    ErasureRequest,
    ErasureResult,
    ModelContextBundle,
    Observation,
    ObservationCreate,
    PersonalFactCreate,
    PersonalRecord,
    PersonalWorldBundle,
    PreferenceCreate,
    PreferenceOrigin,
    QualificationStatus,
    RecordCreateBase,
    RecordKind,
    RelationshipCreate,
    ResourceLinkCreate,
    RevisionRequest,
    SearchHit,
    SearchRequest,
    SourceClass,
    SourceDescriptor,
    SourceDescriptorCreate,
    TemporalScope,
    RevalidationRequest,
    utc_now,
)
from personal_world.persistence.store import SqlAlchemyPersonalWorldStore
from personal_world.privacy import AccessController
from personal_world.retrieval import search_records


class AdmissionError(ValueError):
    pass


class PersonalWorldService:
    def __init__(self, store: SqlAlchemyPersonalWorldStore) -> None:
        self.store = store
        self.access = AccessController()

    def create_source(self, command: SourceDescriptorCreate) -> SourceDescriptor:
        return self.store.create_source(command)

    def create_observation(self, command: ObservationCreate) -> Observation:
        return self.store.create_observation(command)

    def create_claim(self, command: ClaimCreate) -> Claim:
        return self.store.create_claim(command)

    def create_fact(self, command: PersonalFactCreate) -> PersonalRecord:
        return self._create_record(RecordKind.FACT, command)

    def create_preference(self, command: PreferenceCreate) -> PersonalRecord:
        return self._create_record(RecordKind.PREFERENCE, command)

    def create_relationship(self, command: RelationshipCreate) -> PersonalRecord:
        return self._create_record(RecordKind.RELATIONSHIP, command)

    def create_resource_link(self, command: ResourceLinkCreate) -> PersonalRecord:
        return self._create_record(RecordKind.RESOURCE_LINK, command)

    def revise(self, record_id: UUID, command: RevisionRequest) -> PersonalRecord:
        current = self.store.get_record(record_id)
        head = self.store.current_record(current.lineage_id)
        if head.id != current.id:
            raise AdmissionError("revisions must target the current lineage head")
        if head.revision != command.expected_revision:
            raise AdmissionError(
                f"expected revision {command.expected_revision}, current revision is {head.revision}"
            )
        status = self._admission_status(
            kind=head.kind,
            source_refs=command.source_refs,
            preference_origin=head.preference_origin,
            admit_current=True,
        )
        if head.status == QualificationStatus.CURRENT and status != QualificationStatus.CURRENT:
            raise AdmissionError(
                "ineligible evidence cannot replace a current record; create a separate candidate"
            )
        now = utc_now()
        record = head.model_copy(
            update={
                "id": uuid4(),
                "revision": head.revision + 1,
                "value": command.value,
                "source_refs": command.source_refs,
                "claim_refs": command.claim_refs,
                "temporal": command.temporal,
                "sensitivity": command.sensitivity or head.sensitivity,
                "status": status,
                "context": head.context if command.context is None else command.context,
                "metadata": head.metadata if command.metadata is None else command.metadata,
                "supersedes_id": head.id,
                "qualified_at": now if status == QualificationStatus.CURRENT else None,
                "qualification_reason": command.qualification_reason,
                "deleted_at": None,
            }
        )
        return self.store.append_revision(
            lineage_id=head.lineage_id,
            expected_revision=command.expected_revision,
            record=record,
        )

    def revalidate(self, record_id: UUID, command: RevalidationRequest) -> PersonalRecord:
        current = self.store.get_record(record_id)
        head = self.store.current_record(current.lineage_id)
        if head.id != current.id:
            raise AdmissionError("revalidation must target the current lineage head")
        if head.revision != command.expected_revision:
            raise AdmissionError(
                f"expected revision {command.expected_revision}, current revision is {head.revision}"
            )
        if command.status == QualificationStatus.CURRENT:
            allowed = self._admission_status(
                kind=head.kind,
                source_refs=head.source_refs,
                preference_origin=head.preference_origin,
                admit_current=True,
            )
            if allowed != QualificationStatus.CURRENT:
                raise AdmissionError("record sources are not eligible for direct current qualification")
        now = utc_now()
        next_record = head.model_copy(
            update={
                "id": uuid4(),
                "revision": head.revision + 1,
                "status": command.status,
                "supersedes_id": head.id,
                "temporal": head.temporal.model_copy(update={"recorded_at": now}),
                "qualified_at": now,
                "qualification_reason": command.reason,
            }
        )
        return self.store.append_revision(
            lineage_id=head.lineage_id,
            expected_revision=head.revision,
            record=next_record,
        )

    def current_for_subject(
        self,
        subject_id: UUID,
        *,
        service_identity: str,
        purpose: str,
        as_of: datetime | None = None,
    ) -> list[PersonalRecord]:
        profile = self.access.require_purpose(
            self.store.get_access_profile(service_identity), purpose
        )
        all_records = self.store.list_records(subject_id, as_of=as_of)
        visible = [
            record
            for record in all_records
            if self.access.permits_record(profile, record)
        ]
        self._audit(
            service_identity=service_identity,
            purpose=purpose,
            subject_id=subject_id,
            action="current",
            records=visible,
            excluded_count=len(all_records) - len(visible),
        )
        return visible

    def history_for_subject(
        self,
        subject_id: UUID,
        *,
        service_identity: str,
        purpose: str,
    ) -> list[PersonalRecord]:
        profile = self.access.require_purpose(
            self.store.get_access_profile(service_identity), purpose
        )
        all_records = self.store.history(subject_id)
        visible = [
            record
            for record in all_records
            if self.access.permits_record(profile, record)
        ]
        self._audit(
            service_identity=service_identity,
            purpose=purpose,
            subject_id=subject_id,
            action="history",
            records=visible,
            excluded_count=len(all_records) - len(visible),
        )
        return visible

    def project(
        self,
        request: ContextProjectionRequest,
        *,
        service_identity: str,
    ) -> ContextProjection:
        profile = self.access.require_purpose(
            self.store.get_access_profile(service_identity), request.purpose
        )
        records = self.store.list_records(request.subject_id, as_of=request.as_of)
        visible = [
            record
            for record in records
            if record.kind in request.requested_kinds and self.access.permits_record(profile, record)
        ]
        if request.scope:
            visible = [
                record
                for record in visible
                if not record.context.get("scope")
                or record.context.get("scope") == request.scope
            ]
        excluded_count = len(records) - len(visible)
        if request.query:
            visible = [hit.record for hit in search_records(visible, request.query, request.limit)]
        else:
            visible = visible[: request.limit]

        included = tuple(r for r in visible if r.status == QualificationStatus.CURRENT)
        contested = tuple(r for r in visible if r.status == QualificationStatus.CONTESTED)
        stale = tuple(r for r in visible if r.status == QualificationStatus.REVALIDATION_REQUIRED)
        source_refs = tuple(
            sorted({source for record in visible for source in record.source_refs}, key=str)
        )
        projection = ContextProjection(
            subject_id=request.subject_id,
            purpose=request.purpose,
            scope=request.scope,
            included_items=included,
            contested_items=contested,
            stale_items=stale,
            excluded_count=excluded_count,
            source_refs=source_refs,
        )
        self._audit(
            service_identity=service_identity,
            purpose=request.purpose,
            subject_id=request.subject_id,
            action="projection",
            records=visible,
            excluded_count=excluded_count,
        )
        return projection

    def model_context(
        self,
        request: ContextProjectionRequest,
        *,
        service_identity: str,
    ) -> ModelContextBundle:
        projection = self.project(request, service_identity=service_identity)
        return ModelContextBundle(
            purpose=projection.purpose,
            query=request.query,
            projection_ref=projection.id,
            included_items=projection.included_items,
            unresolved_conflicts=projection.contested_items,
            stale_items=projection.stale_items,
            excluded_count=projection.excluded_count,
            source_refs=projection.source_refs,
        )

    def search(self, request: SearchRequest, *, service_identity: str) -> list[SearchHit]:
        profile = self.access.require_purpose(
            self.store.get_access_profile(service_identity), request.purpose
        )
        visible = [
            record
            for record in self.store.list_records(request.subject_id)
            if record.kind in request.kinds
            and record.status
            in {
                QualificationStatus.CURRENT,
                QualificationStatus.CONTESTED,
                QualificationStatus.REVALIDATION_REQUIRED,
            }
            and self.access.permits_record(profile, record)
        ]
        hits = search_records(visible, request.query, request.limit)
        self._audit(
            service_identity=service_identity,
            purpose=request.purpose,
            subject_id=request.subject_id,
            action="search",
            records=[hit.record for hit in hits],
            excluded_count=max(0, len(visible) - len(hits)),
        )
        return hits

    def ingest_domain_projection(
        self,
        projection: DomainPersonalProjection,
        *,
        actor_ref: str | None = None,
    ) -> list[PersonalRecord]:
        source = self.store.create_source(
            SourceDescriptorCreate(
                source_class=SourceClass.DOMAIN_CONTROLLER,
                external_ref=f"{projection.source_domain}:{projection.source_object_ref}",
                actor_ref=actor_ref,
                description="Domain-owned state projected into Personal World",
                metadata={
                    "source_domain": projection.source_domain,
                    "source_version": projection.source_version,
                    **projection.metadata,
                },
            )
        )
        records: list[PersonalRecord] = []
        for domain_claim in projection.claims:
            temporal = TemporalScope(
                observed_at=projection.observed_at,
                valid_from=domain_claim.valid_from,
                valid_until=domain_claim.valid_until,
            )
            observation = self.store.create_observation(
                ObservationCreate(
                    subject_id=projection.subject_id,
                    source_id=source.id,
                    semantic=domain_claim.semantic,
                    value=domain_claim.value,
                    temporal=temporal,
                    sensitivity=domain_claim.sensitivity,
                    metadata=domain_claim.metadata,
                )
            )
            claim = self.store.create_claim(
                ClaimCreate(
                    subject_id=projection.subject_id,
                    source_id=source.id,
                    semantic=domain_claim.semantic,
                    value=domain_claim.value,
                    observation_refs=(observation.id,),
                    temporal=temporal,
                    sensitivity=domain_claim.sensitivity,
                    metadata={
                        "domain_projection": True,
                        "source_domain": projection.source_domain,
                        "source_object_ref": projection.source_object_ref,
                        **domain_claim.metadata,
                    },
                )
            )
            record_metadata = {
                "domain_projection": True,
                "source_domain": projection.source_domain,
                "source_object_ref": projection.source_object_ref,
                "source_version": projection.source_version,
                **domain_claim.metadata,
            }
            common = {
                "subject_id": projection.subject_id,
                "semantic": domain_claim.semantic,
                "value": domain_claim.value,
                "source_refs": (source.id,),
                "claim_refs": (claim.id,),
                "temporal": temporal,
                "sensitivity": domain_claim.sensitivity,
                "context": domain_claim.context,
                "metadata": record_metadata,
                "admit_current": False,
            }

            if domain_claim.record_kind == RecordKind.FACT:
                record = self.create_fact(PersonalFactCreate(**common))
            elif domain_claim.record_kind == RecordKind.PREFERENCE:
                if domain_claim.preference_origin is None:
                    raise AdmissionError("preference domain claim is missing preference_origin")
                record = self.create_preference(
                    PreferenceCreate(
                        **common,
                        origin=domain_claim.preference_origin,
                        strength=domain_claim.strength,
                    )
                )
            elif domain_claim.record_kind == RecordKind.RELATIONSHIP:
                if not domain_claim.target_ref or not domain_claim.relation_namespace:
                    raise AdmissionError("relationship domain claim is incomplete")
                record = self.create_relationship(
                    RelationshipCreate(
                        **common,
                        target_ref=domain_claim.target_ref,
                        relation_namespace=domain_claim.relation_namespace,
                    )
                )
            else:
                if (
                    not domain_claim.resource_ref
                    or not domain_claim.domain
                    or not domain_claim.relation
                ):
                    raise AdmissionError("resource-link domain claim is incomplete")
                record = self.create_resource_link(
                    ResourceLinkCreate(
                        **common,
                        resource_ref=domain_claim.resource_ref,
                        domain=domain_claim.domain,
                        relation=domain_claim.relation,
                        credential_ref=domain_claim.credential_ref,
                    )
                )
            records.append(record)
        return records

    def list_disclosures(self, subject_id: UUID | None = None) -> list[DisclosureAudit]:
        return self.store.list_disclosures(subject_id)

    def _audit(
        self,
        *,
        service_identity: str,
        purpose: str,
        subject_id: UUID,
        action: Literal["current", "history", "projection", "search"],
        records: list[PersonalRecord],
        excluded_count: int,
    ) -> None:
        self.store.record_disclosure(
            DisclosureAudit(
                service_identity=service_identity,
                purpose=purpose,
                subject_id=subject_id,
                action=action,
                record_refs=tuple(record.id for record in records),
                excluded_count=excluded_count,
            )
        )

    def put_access_profile(self, profile: DataAccessProfile) -> None:
        self.store.put_access_profile(profile)

    def redact(self, object_type: str, object_id: UUID) -> None:
        self.store.redact(object_type, object_id, utc_now())

    def erase(self, command: ErasureRequest) -> ErasureResult:
        at = utc_now()
        sources, observations, claims, records = self.store.erase_subject(
            command.subject_id, command.kinds, at
        )
        return ErasureResult(
            subject_id=command.subject_id,
            redacted_sources=sources,
            redacted_observations=observations,
            redacted_claims=claims,
            redacted_records=records,
            completed_at=at,
        )

    def export_bundle(self) -> PersonalWorldBundle:
        return self.store.export_bundle()

    def import_bundle(self, bundle: PersonalWorldBundle) -> None:
        self.store.import_bundle(bundle)

    def _create_record(self, kind: RecordKind, command: RecordCreateBase) -> PersonalRecord:
        preference_origin = command.origin if isinstance(command, PreferenceCreate) else None
        status = self._admission_status(
            kind=kind,
            source_refs=command.source_refs,
            preference_origin=preference_origin,
            admit_current=command.admit_current,
        )
        now = utc_now()
        preference_value: PreferenceOrigin | None = None
        strength: float | None = None
        target_ref: str | None = None
        relation_namespace: str | None = None
        resource_ref: str | None = None
        domain: str | None = None
        relation: str | None = None
        credential_ref: str | None = None
        if isinstance(command, PreferenceCreate):
            preference_value = command.origin
            strength = command.strength
        elif isinstance(command, RelationshipCreate):
            target_ref = command.target_ref
            relation_namespace = command.relation_namespace
        elif isinstance(command, ResourceLinkCreate):
            resource_ref = command.resource_ref
            domain = command.domain
            relation = command.relation
            credential_ref = command.credential_ref

        record = PersonalRecord(
            id=uuid4(),
            lineage_id=uuid4(),
            revision=1,
            kind=kind,
            subject_id=command.subject_id,
            semantic=command.semantic,
            value=command.value,
            source_refs=command.source_refs,
            claim_refs=command.claim_refs,
            temporal=command.temporal,
            sensitivity=command.sensitivity,
            status=status,
            context=command.context,
            metadata=command.metadata,
            qualified_at=now if status == QualificationStatus.CURRENT else None,
            qualification_reason="initial-admission",
            preference_origin=preference_value,
            strength=strength,
            target_ref=target_ref,
            relation_namespace=relation_namespace,
            resource_ref=resource_ref,
            domain=domain,
            relation=relation,
            credential_ref=credential_ref,
        )
        return self.store.create_record(record)

    def _admission_status(
        self,
        *,
        kind: RecordKind,
        source_refs: tuple[UUID, ...],
        preference_origin: PreferenceOrigin | None,
        admit_current: bool,
    ) -> QualificationStatus:
        if not admit_current:
            return QualificationStatus.CANDIDATE
        if kind == RecordKind.PREFERENCE and preference_origin == PreferenceOrigin.UNACCEPTED_INFERENCE:
            return QualificationStatus.CANDIDATE
        sources = [self.store.get_source(source_id) for source_id in source_refs]
        if any(source.source_class == SourceClass.MODEL_INFERENCE for source in sources):
            if kind == RecordKind.PREFERENCE and preference_origin == PreferenceOrigin.ACCEPTED_INFERENCE:
                return QualificationStatus.CURRENT
            return QualificationStatus.CANDIDATE
        return QualificationStatus.CURRENT
