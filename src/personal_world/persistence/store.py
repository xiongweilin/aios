from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast
from uuid import UUID

from semantic_language import SemanticRef
from sqlalchemy import Select, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from personal_world.model.contracts import (
    Claim,
    ClaimCreate,
    DataAccessProfile,
    DisclosureAudit,
    Observation,
    ObservationCreate,
    PersonalRecord,
    PersonalWorldBundle,
    PreferenceOrigin,
    QualificationStatus,
    RecordKind,
    SensitivityClass,
    SourceClass,
    SourceDescriptor,
    SourceDescriptorCreate,
    TemporalScope,
)
from personal_world.persistence.database import (
    AccessProfileRow,
    Base,
    ClaimRow,
    DisclosureAuditRow,
    ObservationRow,
    RecordRow,
    SourceRow,
)


class NotFoundError(LookupError):
    pass


class ConcurrencyError(RuntimeError):
    pass


class PersonalWorldStore(Protocol):
    def create_schema(self) -> None: ...
    def create_source(self, value: SourceDescriptorCreate) -> SourceDescriptor: ...
    def get_source(self, source_id: UUID) -> SourceDescriptor: ...
    def create_observation(self, value: ObservationCreate) -> Observation: ...
    def create_claim(self, value: ClaimCreate) -> Claim: ...
    def list_records(
        self,
        subject_id: UUID,
        *,
        as_of: datetime | None = None,
    ) -> list[PersonalRecord]: ...


def _dump(value: object) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _load(value: str) -> Any:
    return json.loads(value)


def _dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _semantic_kwargs(ref: SemanticRef) -> dict[str, str]:
    return {
        "semantic_namespace": ref.namespace,
        "semantic_kind": ref.kind_value,
        "semantic_id": ref.id,
        "semantic_version": ref.version,
    }


def _semantic_from_row(row: ObservationRow | ClaimRow | RecordRow) -> SemanticRef:
    return SemanticRef(
        kind=row.semantic_kind,
        id=row.semantic_id,
        namespace=row.semantic_namespace,
        version=row.semantic_version,
    )


class SqlAlchemyPersonalWorldStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.sessions = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def create_source(self, value: SourceDescriptorCreate) -> SourceDescriptor:
        item = SourceDescriptor(**value.model_dump())
        with self.sessions.begin() as session:
            session.add(
                SourceRow(
                    id=str(item.id),
                    source_class=item.source_class.value,
                    external_ref=item.external_ref,
                    actor_ref=item.actor_ref,
                    description=item.description,
                    metadata_json=_dump(item.metadata),
                    created_at=item.created_at,
                )
            )
        return item

    def get_source(self, source_id: UUID) -> SourceDescriptor:
        with self.sessions() as session:
            row = session.get(SourceRow, str(source_id))
            if row is None or row.deleted_at is not None:
                raise NotFoundError(f"source {source_id} not found")
            return self._source(row)

    def create_observation(self, value: ObservationCreate) -> Observation:
        self.get_source(value.source_id)
        item = Observation(**value.model_dump())
        with self.sessions.begin() as session:
            session.add(
                ObservationRow(
                    id=str(item.id),
                    subject_id=str(item.subject_id),
                    source_id=str(item.source_id),
                    **_semantic_kwargs(item.semantic),
                    value_json=_dump(item.value),
                    temporal_json=_dump(item.temporal),
                    sensitivity=int(item.sensitivity),
                    metadata_json=_dump(item.metadata),
                )
            )
        return item

    def get_observation(self, observation_id: UUID) -> Observation:
        with self.sessions() as session:
            row = session.get(ObservationRow, str(observation_id))
            if row is None or row.deleted_at is not None:
                raise NotFoundError(f"observation {observation_id} not found")
            return self._observation(row)

    def create_claim(self, value: ClaimCreate) -> Claim:
        self.get_source(value.source_id)
        for ref in value.observation_refs:
            observation = self.get_observation(ref)
            if observation.subject_id != value.subject_id:
                raise ValueError("claim observation subject mismatch")
        item = Claim(**value.model_dump())
        with self.sessions.begin() as session:
            session.add(
                ClaimRow(
                    id=str(item.id),
                    subject_id=str(item.subject_id),
                    source_id=str(item.source_id),
                    **_semantic_kwargs(item.semantic),
                    value_json=_dump(item.value),
                    observation_refs_json=_dump([str(item) for item in item.observation_refs]),
                    temporal_json=_dump(item.temporal),
                    confidence=None if item.confidence is None else str(item.confidence),
                    sensitivity=int(item.sensitivity),
                    metadata_json=_dump(item.metadata),
                )
            )
        return item

    def get_claim(self, claim_id: UUID) -> Claim:
        with self.sessions() as session:
            row = session.get(ClaimRow, str(claim_id))
            if row is None or row.deleted_at is not None:
                raise NotFoundError(f"claim {claim_id} not found")
            return self._claim(row)

    def create_record(self, record: PersonalRecord) -> PersonalRecord:
        self._validate_refs(record)
        with self.sessions.begin() as session:
            session.add(self._record_row(record))
        return record

    def current_record(self, lineage_id: UUID) -> PersonalRecord:
        with self.sessions() as session:
            row = session.scalar(
                select(RecordRow)
                .where(RecordRow.lineage_id == str(lineage_id))
                .order_by(RecordRow.revision.desc())
                .limit(1)
            )
            if row is None or row.deleted_at is not None:
                raise NotFoundError(f"lineage {lineage_id} not found")
            return self._record(row)

    def get_record(self, record_id: UUID) -> PersonalRecord:
        with self.sessions() as session:
            row = session.get(RecordRow, str(record_id))
            if row is None or row.deleted_at is not None:
                raise NotFoundError(f"record {record_id} not found")
            return self._record(row)

    def append_revision(
        self,
        *,
        lineage_id: UUID,
        expected_revision: int,
        record: PersonalRecord,
    ) -> PersonalRecord:
        self._validate_refs(record)
        try:
            with self.sessions.begin() as session:
                stmt: Select[tuple[RecordRow]] = (
                    select(RecordRow)
                    .where(RecordRow.lineage_id == str(lineage_id))
                    .order_by(RecordRow.revision.desc())
                    .limit(1)
                )
                if self.engine.dialect.name != "sqlite":
                    stmt = stmt.with_for_update()
                current = session.scalar(stmt)
                if current is None or current.deleted_at is not None:
                    raise NotFoundError(f"lineage {lineage_id} not found")
                if current.revision != expected_revision:
                    raise ConcurrencyError(
                        f"expected revision {expected_revision}, current revision is {current.revision}"
                    )
                if record.revision != expected_revision + 1:
                    raise ValueError("new revision must increment by one")
                session.add(self._record_row(record))
        except IntegrityError as exc:
            raise ConcurrencyError("concurrent revision conflict") from exc
        return record

    def list_records(
        self,
        subject_id: UUID,
        *,
        as_of: datetime | None = None,
    ) -> list[PersonalRecord]:
        with self.sessions() as session:
            rows = list(
                session.scalars(
                    select(RecordRow).where(RecordRow.subject_id == str(subject_id))
                )
            )

        erased_lineages = {UUID(row.lineage_id) for row in rows if row.deleted_at is not None}
        records = [
            self._record(row)
            for row in rows
            if row.deleted_at is None and UUID(row.lineage_id) not in erased_lineages
        ]

        if as_of is None:
            heads: dict[UUID, PersonalRecord] = {}
            for record in records:
                previous = heads.get(record.lineage_id)
                if previous is None or record.revision > previous.revision:
                    heads[record.lineage_id] = record
            return list(heads.values())

        moment = _dt(as_of)
        if moment is None:
            raise ValueError("as_of is required for historical reconstruction")
        heads_at_time: dict[UUID, PersonalRecord] = {}
        for record in records:
            recorded = _dt(record.temporal.recorded_at)
            valid_from = _dt(record.temporal.valid_from)
            valid_until = _dt(record.temporal.valid_until)
            if recorded is not None and recorded > moment:
                continue
            if valid_from is not None and valid_from > moment:
                continue
            if valid_until is not None and valid_until <= moment:
                continue
            previous = heads_at_time.get(record.lineage_id)
            if previous is None or record.revision > previous.revision:
                heads_at_time[record.lineage_id] = record
        return list(heads_at_time.values())

    def history(self, subject_id: UUID) -> list[PersonalRecord]:
        with self.sessions() as session:
            rows = list(
                session.scalars(
                    select(RecordRow)
                    .where(RecordRow.subject_id == str(subject_id))
                    .order_by(RecordRow.lineage_id, RecordRow.revision)
                )
            )
        erased_lineages = {row.lineage_id for row in rows if row.deleted_at is not None}
        return [
            self._record(row)
            for row in rows
            if row.deleted_at is None and row.lineage_id not in erased_lineages
        ]

    def put_access_profile(self, profile: DataAccessProfile) -> None:
        with self.sessions.begin() as session:
            row = session.get(AccessProfileRow, profile.service_identity)
            if row is None:
                session.add(
                    AccessProfileRow(
                        service_identity=profile.service_identity,
                        allowed_purposes_json=_dump(profile.allowed_purposes),
                        allowed_kinds_json=_dump([item.value for item in profile.allowed_kinds]),
                        max_sensitivity=int(profile.max_sensitivity),
                    )
                )
            else:
                row.allowed_purposes_json = _dump(profile.allowed_purposes)
                row.allowed_kinds_json = _dump([item.value for item in profile.allowed_kinds])
                row.max_sensitivity = int(profile.max_sensitivity)

    def get_access_profile(self, service_identity: str) -> DataAccessProfile | None:
        with self.sessions() as session:
            row = session.get(AccessProfileRow, service_identity)
            if row is None:
                return None
            return DataAccessProfile(
                service_identity=row.service_identity,
                allowed_purposes=tuple(_load(row.allowed_purposes_json)),
                allowed_kinds=tuple(RecordKind(item) for item in _load(row.allowed_kinds_json)),
                max_sensitivity=SensitivityClass(row.max_sensitivity),
            )

    def record_disclosure(self, audit: DisclosureAudit) -> DisclosureAudit:
        with self.sessions.begin() as session:
            session.add(
                DisclosureAuditRow(
                    id=str(audit.id),
                    service_identity=audit.service_identity,
                    purpose=audit.purpose,
                    subject_id=str(audit.subject_id),
                    action=audit.action,
                    record_refs_json=_dump([str(item) for item in audit.record_refs]),
                    excluded_count=audit.excluded_count,
                    occurred_at=audit.occurred_at,
                )
            )
        return audit

    def list_disclosures(self, subject_id: UUID | None = None) -> list[DisclosureAudit]:
        with self.sessions() as session:
            stmt = select(DisclosureAuditRow).order_by(DisclosureAuditRow.occurred_at)
            if subject_id is not None:
                stmt = stmt.where(DisclosureAuditRow.subject_id == str(subject_id))
            rows = list(session.scalars(stmt))
        return [
            DisclosureAudit(
                id=UUID(row.id),
                service_identity=row.service_identity,
                purpose=row.purpose,
                subject_id=UUID(row.subject_id),
                action=cast(
                    Literal["current", "history", "projection", "search"],
                    row.action,
                ),
                record_refs=tuple(UUID(item) for item in _load(row.record_refs_json)),
                excluded_count=row.excluded_count,
                occurred_at=_dt(row.occurred_at) or datetime.now(UTC),
            )
            for row in rows
        ]

    def redact(self, object_type: str, object_id: UUID, at: datetime) -> None:
        key = str(object_id)
        with self.sessions.begin() as session:
            if object_type == "record":
                record = session.get(RecordRow, key)
                if record is None:
                    raise NotFoundError(f"record {object_id} not found")
                record_targets = list(
                    session.scalars(
                        select(RecordRow).where(RecordRow.lineage_id == record.lineage_id)
                    )
                )
                for record_target in record_targets:
                    record_target.deleted_at = at
                    record_target.value_json = _dump({"redacted": True})
                    record_target.metadata_json = "{}"
                    record_target.context_json = "{}"
                return

            if object_type == "observation":
                observation = session.get(ObservationRow, key)
                if observation is None:
                    raise NotFoundError(f"observation {object_id} not found")
                observation.deleted_at = at
                observation.value_json = _dump({"redacted": True})
                observation.metadata_json = "{}"
                return

            if object_type == "claim":
                claim = session.get(ClaimRow, key)
                if claim is None:
                    raise NotFoundError(f"claim {object_id} not found")
                claim.deleted_at = at
                claim.value_json = _dump({"redacted": True})
                claim.metadata_json = "{}"
                return

            if object_type != "source":
                raise ValueError(f"unsupported redaction object type: {object_type}")
            source = session.get(SourceRow, key)
            if source is None:
                raise NotFoundError(f"source {object_id} not found")
            source.deleted_at = at
            source.metadata_json = "{}"
            source.external_ref = None
            source.actor_ref = None
            source.description = None

    def erase_subject(
        self,
        subject_id: UUID,
        kinds: tuple[RecordKind, ...] | None,
        at: datetime,
    ) -> tuple[int, int, int, int]:
        kind_values = None if kinds is None else {item.value for item in kinds}
        subject_key = str(subject_id)

        with self.sessions.begin() as session:
            all_subject_records = list(
                session.scalars(select(RecordRow).where(RecordRow.subject_id == subject_key))
            )
            record_rows = all_subject_records
            if kind_values is not None:
                record_rows = [row for row in all_subject_records if row.kind in kind_values]

            selected_claim_ids = {
                claim_id
                for row in record_rows
                for claim_id in _load(row.claim_refs_json)
            }
            candidate_source_ids = {
                source_id
                for row in record_rows
                for source_id in _load(row.source_refs_json)
            }

            if kind_values is None:
                claim_rows = list(
                    session.scalars(select(ClaimRow).where(ClaimRow.subject_id == subject_key))
                )
                observation_rows = list(
                    session.scalars(
                        select(ObservationRow).where(ObservationRow.subject_id == subject_key)
                    )
                )
            else:
                claim_rows = []
                if selected_claim_ids:
                    claim_rows = list(
                        session.scalars(
                            select(ClaimRow).where(
                                ClaimRow.subject_id == subject_key,
                                ClaimRow.id.in_(selected_claim_ids),
                            )
                        )
                    )
                selected_observation_ids = {
                    observation_id
                    for row in claim_rows
                    for observation_id in _load(row.observation_refs_json)
                }
                observation_rows = []
                if selected_observation_ids:
                    observation_rows = list(
                        session.scalars(
                            select(ObservationRow).where(
                                ObservationRow.subject_id == subject_key,
                                ObservationRow.id.in_(selected_observation_ids),
                            )
                        )
                    )

            candidate_source_ids.update(row.source_id for row in claim_rows)
            candidate_source_ids.update(row.source_id for row in observation_rows)

            for record_row in record_rows:
                record_row.deleted_at = at
                record_row.value_json = _dump({"redacted": True})
                record_row.metadata_json = "{}"
                record_row.context_json = "{}"
            for observation_row in observation_rows:
                observation_row.deleted_at = at
                observation_row.value_json = _dump({"redacted": True})
                observation_row.metadata_json = "{}"
            for claim_row in claim_rows:
                claim_row.deleted_at = at
                claim_row.value_json = _dump({"redacted": True})
                claim_row.metadata_json = "{}"

            surviving_record_source_ids = {
                source_id
                for row in session.scalars(
                    select(RecordRow).where(RecordRow.deleted_at.is_(None))
                )
                for source_id in _load(row.source_refs_json)
            }

            source_count = 0
            for source_id in candidate_source_ids:
                surviving_observations = session.scalar(
                    select(func.count()).select_from(ObservationRow).where(
                        ObservationRow.source_id == source_id,
                        ObservationRow.deleted_at.is_(None),
                    )
                )
                surviving_claims = session.scalar(
                    select(func.count()).select_from(ClaimRow).where(
                        ClaimRow.source_id == source_id,
                        ClaimRow.deleted_at.is_(None),
                    )
                )
                if (
                    not surviving_observations
                    and not surviving_claims
                    and source_id not in surviving_record_source_ids
                ):
                    source = session.get(SourceRow, source_id)
                    if source is not None and source.deleted_at is None:
                        source.deleted_at = at
                        source.external_ref = None
                        source.actor_ref = None
                        source.description = None
                        source.metadata_json = "{}"
                        source_count += 1

        return source_count, len(observation_rows), len(claim_rows), len(record_rows)

    def export_bundle(self) -> PersonalWorldBundle:
        with self.sessions() as session:
            sources = [self._source_dict(row) for row in session.scalars(select(SourceRow))]
            observations = [
                self._observation_dict(row) for row in session.scalars(select(ObservationRow))
            ]
            claims = [self._claim_dict(row) for row in session.scalars(select(ClaimRow))]
            records = [self._record_dict(row) for row in session.scalars(select(RecordRow))]
            profiles = [
                {
                    "service_identity": row.service_identity,
                    "allowed_purposes": _load(row.allowed_purposes_json),
                    "allowed_kinds": _load(row.allowed_kinds_json),
                    "max_sensitivity": row.max_sensitivity,
                }
                for row in session.scalars(select(AccessProfileRow))
            ]
            disclosures = [
                {
                    "id": row.id,
                    "service_identity": row.service_identity,
                    "purpose": row.purpose,
                    "subject_id": row.subject_id,
                    "action": row.action,
                    "record_refs_json": row.record_refs_json,
                    "excluded_count": row.excluded_count,
                    "occurred_at": row.occurred_at,
                }
                for row in session.scalars(select(DisclosureAuditRow))
            ]
        return PersonalWorldBundle(
            sources=tuple(sources),
            observations=tuple(observations),
            claims=tuple(claims),
            records=tuple(records),
            access_profiles=tuple(profiles),
            disclosures=tuple(disclosures),
        )

    def import_bundle(self, bundle: PersonalWorldBundle) -> None:
        with self.sessions.begin() as session:
            existing = sum(
                int(session.scalar(select(func.count()).select_from(table)) or 0)
                for table in (
                    RecordRow,
                    ClaimRow,
                    ObservationRow,
                    SourceRow,
                    AccessProfileRow,
                    DisclosureAuditRow,
                )
            )
            if existing:
                raise ValueError("bundle import requires an empty store")
            for item in bundle.sources:
                session.add(SourceRow(**item))
            for item in bundle.observations:
                session.add(ObservationRow(**item))
            for item in bundle.claims:
                session.add(ClaimRow(**item))
            for item in bundle.records:
                session.add(RecordRow(**item))
            for item in bundle.access_profiles:
                session.add(
                    AccessProfileRow(
                        service_identity=item["service_identity"],
                        allowed_purposes_json=_dump(item["allowed_purposes"]),
                        allowed_kinds_json=_dump(item["allowed_kinds"]),
                        max_sensitivity=item["max_sensitivity"],
                    )
                )
            for item in bundle.disclosures:
                session.add(DisclosureAuditRow(**item))

    def _validate_refs(self, record: PersonalRecord) -> None:
        for source_id in record.source_refs:
            self.get_source(source_id)
        for claim_id in record.claim_refs:
            claim = self.get_claim(claim_id)
            if claim.subject_id != record.subject_id:
                raise ValueError("record claim subject mismatch")

    @staticmethod
    def _source(row: SourceRow) -> SourceDescriptor:
        created_at = _dt(row.created_at)
        if created_at is None:
            raise ValueError("source created_at must not be null")
        return SourceDescriptor(
            id=UUID(row.id),
            source_class=SourceClass(row.source_class),
            external_ref=row.external_ref,
            actor_ref=row.actor_ref,
            description=row.description,
            metadata=_load(row.metadata_json),
            created_at=created_at,
        )

    @staticmethod
    def _observation(row: ObservationRow) -> Observation:
        return Observation(
            id=UUID(row.id),
            subject_id=UUID(row.subject_id),
            source_id=UUID(row.source_id),
            semantic=_semantic_from_row(row),
            value=_load(row.value_json),
            temporal=TemporalScope.model_validate(_load(row.temporal_json)),
            sensitivity=SensitivityClass(row.sensitivity),
            metadata=_load(row.metadata_json),
        )

    @staticmethod
    def _claim(row: ClaimRow) -> Claim:
        return Claim(
            id=UUID(row.id),
            subject_id=UUID(row.subject_id),
            source_id=UUID(row.source_id),
            semantic=_semantic_from_row(row),
            value=_load(row.value_json),
            observation_refs=tuple(UUID(item) for item in _load(row.observation_refs_json)),
            temporal=TemporalScope.model_validate(_load(row.temporal_json)),
            confidence=None if row.confidence is None else float(row.confidence),
            sensitivity=SensitivityClass(row.sensitivity),
            metadata=_load(row.metadata_json),
        )

    @staticmethod
    def _record(row: RecordRow) -> PersonalRecord:
        return PersonalRecord(
            id=UUID(row.id),
            lineage_id=UUID(row.lineage_id),
            revision=row.revision,
            kind=RecordKind(row.kind),
            subject_id=UUID(row.subject_id),
            semantic=_semantic_from_row(row),
            value=_load(row.value_json),
            source_refs=tuple(UUID(item) for item in _load(row.source_refs_json)),
            claim_refs=tuple(UUID(item) for item in _load(row.claim_refs_json)),
            temporal=TemporalScope.model_validate(_load(row.temporal_json)),
            sensitivity=SensitivityClass(row.sensitivity),
            status=QualificationStatus(row.status),
            context=_load(row.context_json),
            metadata=_load(row.metadata_json),
            supersedes_id=None if row.supersedes_id is None else UUID(row.supersedes_id),
            preference_origin=(
                None if row.preference_origin is None else PreferenceOrigin(row.preference_origin)
            ),
            strength=None if row.strength is None else float(row.strength),
            target_ref=row.target_ref,
            relation_namespace=row.relation_namespace,
            resource_ref=row.resource_ref,
            domain=row.domain,
            relation=row.relation,
            credential_ref=row.credential_ref,
            qualified_at=_dt(row.qualified_at),
            qualification_reason=row.qualification_reason,
            deleted_at=_dt(row.deleted_at),
        )

    @staticmethod
    def _record_row(record: PersonalRecord) -> RecordRow:
        return RecordRow(
            id=str(record.id),
            lineage_id=str(record.lineage_id),
            revision=record.revision,
            kind=record.kind.value,
            subject_id=str(record.subject_id),
            **_semantic_kwargs(record.semantic),
            value_json=_dump(record.value),
            source_refs_json=_dump([str(item) for item in record.source_refs]),
            claim_refs_json=_dump([str(item) for item in record.claim_refs]),
            temporal_json=_dump(record.temporal),
            sensitivity=int(record.sensitivity),
            status=record.status.value,
            context_json=_dump(record.context),
            metadata_json=_dump(record.metadata),
            supersedes_id=None if record.supersedes_id is None else str(record.supersedes_id),
            preference_origin=(
                None if record.preference_origin is None else record.preference_origin.value
            ),
            strength=None if record.strength is None else str(record.strength),
            target_ref=record.target_ref,
            relation_namespace=record.relation_namespace,
            resource_ref=record.resource_ref,
            domain=record.domain,
            relation=record.relation,
            credential_ref=record.credential_ref,
            qualified_at=record.qualified_at,
            qualification_reason=record.qualification_reason,
            deleted_at=record.deleted_at,
        )

    @staticmethod
    def _source_dict(row: SourceRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "source_class": row.source_class,
            "external_ref": row.external_ref,
            "actor_ref": row.actor_ref,
            "description": row.description,
            "metadata_json": row.metadata_json,
            "created_at": row.created_at,
            "deleted_at": row.deleted_at,
        }

    @staticmethod
    def _observation_dict(row: ObservationRow) -> dict[str, Any]:
        return {
            column.name: getattr(row, column.name)
            for column in ObservationRow.__table__.columns
        }

    @staticmethod
    def _claim_dict(row: ClaimRow) -> dict[str, Any]:
        return {column.name: getattr(row, column.name) for column in ClaimRow.__table__.columns}

    @staticmethod
    def _record_dict(row: RecordRow) -> dict[str, Any]:
        return {column.name: getattr(row, column.name) for column in RecordRow.__table__.columns}
