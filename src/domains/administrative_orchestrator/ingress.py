from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from .persistence import Base, SqlStore, utcnow


class IngressReceiptRow(Base):
    __tablename__ = "administrative_ingress_receipt"

    source_event_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_request.request_id"), nullable=False
    )
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("administrative_case.case_id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


@dataclass(frozen=True)
class IngressReceipt:
    source_event_id: str
    request_id: UUID
    case_id: UUID
    created_at: datetime


class DuplicateIngressEvent(RuntimeError):
    def __init__(self, receipt: IngressReceipt) -> None:
        super().__init__(f"source event {receipt.source_event_id!r} already created a case")
        self.receipt = receipt


def persist_ingress_receipt(
    db: Session,
    *,
    source_event_id: str,
    request_id: UUID,
    case_id: UUID,
) -> None:
    source_event_id = source_event_id.strip()
    if not source_event_id:
        raise ValueError("source_event_id must not be blank")
    existing = db.get(IngressReceiptRow, source_event_id)
    if existing is not None:
        raise DuplicateIngressEvent(_receipt_from_row(existing))
    db.add(
        IngressReceiptRow(
            source_event_id=source_event_id,
            request_id=request_id,
            case_id=case_id,
            created_at=utcnow(),
        )
    )


def get_ingress_receipt(store: SqlStore, source_event_id: str) -> IngressReceipt | None:
    with store.sessions() as db:
        row = db.get(IngressReceiptRow, source_event_id.strip())
        return None if row is None else _receipt_from_row(row)


def _receipt_from_row(row: IngressReceiptRow) -> IngressReceipt:
    return IngressReceipt(
        source_event_id=row.source_event_id,
        request_id=row.request_id,
        case_id=row.case_id,
        created_at=row.created_at,
    )


__all__ = [
    "DuplicateIngressEvent",
    "IngressReceipt",
    "IngressReceiptRow",
    "get_ingress_receipt",
    "persist_ingress_receipt",
]
