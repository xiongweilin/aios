from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Uuid, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import AdministrativeCase, FactAssertion, FactAuthority, FactSnapshot
from .persistence import Base, SqlStore, utcnow


class FactSnapshotHistoryRow(Base):
    __tablename__ = "administrative_fact_snapshot_history"

    snapshot_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    case_version: Mapped[int] = mapped_column(Integer, nullable=False)
    authority_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(255), nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    authority: Mapped[str] = mapped_column(String(32), nullable=False, default=FactAuthority.CLAIM.value)
    source_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_version: Mapped[str | None] = mapped_column(String(512), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    facts_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    assertions_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


def persist_fact_snapshot(db: Session, case: AdministrativeCase) -> None:
    snapshot = case.fact_snapshot
    if snapshot is None:
        return
    existing = db.get(FactSnapshotHistoryRow, snapshot.snapshot_id)
    if existing is not None:
        restored = _snapshot_from_row(existing)
        if restored != snapshot or existing.case_id != case.case_id:
            raise ValueError("fact snapshot id already exists with different semantics")
        return
    db.add(
        FactSnapshotHistoryRow(
            snapshot_id=snapshot.snapshot_id,
            case_id=case.case_id,
            case_version=case.version,
            authority_epoch=case.authority_epoch,
            source=snapshot.source,
            owner=snapshot.owner,
            authority=snapshot.authority.value,
            source_ref=snapshot.source_ref,
            source_version=snapshot.source_version,
            observed_at=snapshot.observed_at,
            digest=snapshot.digest,
            facts_json=dict(snapshot.facts),
            assertions_json={
                key: assertion.model_dump(mode="json")
                for key, assertion in snapshot.assertions.items()
            },
            recorded_at=utcnow(),
        )
    )


def list_fact_snapshots(store: SqlStore, case_id: UUID) -> list[FactSnapshot]:
    with store.sessions() as db:
        rows = (
            db.execute(
                select(FactSnapshotHistoryRow)
                .where(FactSnapshotHistoryRow.case_id == case_id)
                .order_by(
                    FactSnapshotHistoryRow.case_version,
                    FactSnapshotHistoryRow.recorded_at,
                    FactSnapshotHistoryRow.snapshot_id,
                )
            )
            .scalars()
            .all()
        )
        return [_snapshot_from_row(row) for row in rows]


def _snapshot_from_row(row: FactSnapshotHistoryRow) -> FactSnapshot:
    raw_assertions = dict(row.assertions_json or {})
    return FactSnapshot(
        snapshot_id=row.snapshot_id,
        source=row.source,
        owner=row.owner,
        authority=FactAuthority(row.authority),
        source_ref=row.source_ref,
        source_version=row.source_version,
        observed_at=row.observed_at,
        facts=dict(row.facts_json),
        assertions={
            key: FactAssertion.model_validate(value) for key, value in raw_assertions.items()
        },
        digest=row.digest,
    )


__all__ = ["FactSnapshotHistoryRow", "list_fact_snapshots", "persist_fact_snapshot"]
