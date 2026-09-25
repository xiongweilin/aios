from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, Integer, String, Uuid, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


def canonical_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


class SandboxBase(DeclarativeBase):
    pass


class RealizedEffectRow(SandboxBase):
    __tablename__ = "realized_effect"

    effect_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    target_system: Mapped[str] = mapped_column(String(255), nullable=False)
    operation: Mapped[str] = mapped_column(String(255), nullable=False)
    subject_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    apply_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    realized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EffectRequestBindingRow(SandboxBase):
    """Provider-owned durable request/idempotency identity for reconciliation."""

    __tablename__ = "effect_request_binding"

    request_ref: Mapped[str] = mapped_column(String(512), primary_key=True)
    effect_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, unique=True)
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SandboxStore:
    def __init__(self, database_url: str) -> None:
        if database_url.startswith("sqlite"):
            path_text = database_url.split("///", 1)[-1]
            if path_text and path_text != ":memory:":
                Path(path_text).parent.mkdir(parents=True, exist_ok=True)
            self.engine = create_engine(
                database_url,
                future=True,
                connect_args={"check_same_thread": False},
            )
        else:
            self.engine = create_engine(database_url, future=True, pool_pre_ping=True)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def init_schema(self) -> None:
        SandboxBase.metadata.create_all(self.engine)


class ApplyEffectBody(BaseModel):
    target_system: str
    operation: str
    subject_ref: str
    payload: dict[str, Any] = Field(default_factory=dict)
    request_ref: str | None = None


class ApplyEffectResponse(BaseModel):
    status: str = "succeeded"
    provider_ref: str


class ObservationResponse(BaseModel):
    found: bool = True
    target_system: str
    operation: str
    subject_ref: str
    provider_ref: str
    state: dict[str, Any]
    digest: str
    apply_attempts: int
    observed_at: datetime
    request_ref: str | None = None


settings = get_settings()
store = SandboxStore(settings.sandbox_database_url)
store.init_schema()
app = FastAPI(title="Administrative Authoritative Sandbox", version="0.1.0")


def _bind_request(db: Session, request_ref: str | None, effect_id: UUID) -> None:
    if request_ref is None:
        return
    request_ref = request_ref.strip()
    if not request_ref:
        raise HTTPException(status_code=422, detail="request_ref must not be blank")
    by_request = db.get(EffectRequestBindingRow, request_ref)
    if by_request is not None:
        if by_request.effect_id != effect_id:
            raise HTTPException(
                status_code=409,
                detail="request ref already bound to a different realized effect",
            )
        return
    by_effect = db.execute(
        select(EffectRequestBindingRow).where(EffectRequestBindingRow.effect_id == effect_id)
    ).scalar_one_or_none()
    if by_effect is not None and by_effect.request_ref != request_ref:
        raise HTTPException(
            status_code=409,
            detail="realized effect already bound to a different request ref",
        )
    db.add(
        EffectRequestBindingRow(
            request_ref=request_ref,
            effect_id=effect_id,
            bound_at=utcnow(),
        )
    )


def _request_ref_for_effect(db: Session, effect_id: UUID) -> str | None:
    binding = db.execute(
        select(EffectRequestBindingRow).where(EffectRequestBindingRow.effect_id == effect_id)
    ).scalar_one_or_none()
    return binding.request_ref if binding is not None else None


def _observation(db: Session, row: RealizedEffectRow) -> ObservationResponse:
    return ObservationResponse(
        target_system=row.target_system,
        operation=row.operation,
        subject_ref=row.subject_ref,
        provider_ref=f"sandbox:{row.effect_id}",
        state=row.state_json,
        digest=row.digest,
        apply_attempts=row.apply_attempts,
        observed_at=row.realized_at,
        request_ref=_request_ref_for_effect(db, row.effect_id),
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.put("/v1/effects/{effect_id}", response_model=ApplyEffectResponse)
def apply_effect(effect_id: UUID, body: ApplyEffectBody) -> ApplyEffectResponse:
    provider_ref = f"sandbox:{effect_id}"
    state = {
        "target_system": body.target_system,
        "operation": body.operation,
        "subject_ref": body.subject_ref,
        "payload": body.payload,
        "active": True,
    }
    digest = canonical_digest(state)
    with store.sessions.begin() as db:
        existing = db.get(RealizedEffectRow, effect_id)
        if existing is not None:
            if (
                existing.target_system != body.target_system
                or existing.operation != body.operation
                or existing.subject_ref != body.subject_ref
                or existing.payload_json != body.payload
            ):
                raise HTTPException(
                    status_code=409,
                    detail="effect id already realized with different semantics",
                )
            _bind_request(db, body.request_ref, effect_id)
            existing.apply_attempts += 1
            return ApplyEffectResponse(provider_ref=provider_ref)
        db.add(
            RealizedEffectRow(
                effect_id=effect_id,
                target_system=body.target_system,
                operation=body.operation,
                subject_ref=body.subject_ref,
                payload_json=body.payload,
                state_json=state,
                digest=digest,
                apply_attempts=1,
                realized_at=utcnow(),
            )
        )
        _bind_request(db, body.request_ref, effect_id)
    return ApplyEffectResponse(provider_ref=provider_ref)


@app.get("/v1/reconciliation/effects/{request_ref}", response_model=ObservationResponse)
def reconcile_effect(request_ref: str) -> ObservationResponse:
    with store.sessions() as db:
        binding = db.get(EffectRequestBindingRow, request_ref)
        if binding is None:
            raise HTTPException(status_code=404, detail="request ref not found")
        row = db.get(RealizedEffectRow, binding.effect_id)
        if row is None:
            raise HTTPException(status_code=409, detail="request binding has no realized effect")
        return _observation(db, row)


@app.get("/v1/effects/{effect_id}", response_model=ObservationResponse)
def observe_effect(effect_id: UUID) -> ObservationResponse:
    with store.sessions() as db:
        row = db.get(RealizedEffectRow, effect_id)
        if row is None:
            raise HTTPException(status_code=404, detail="effect not found")
        return _observation(db, row)
