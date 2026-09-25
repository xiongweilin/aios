from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from ..access_policy import AdministrativePermission
from ..domain import CaseStatus
from ..persistence import CaseRow
from ..production_readiness import (
    ProductionReadinessError,
    validate_world_runtime_compatibility,
)
from .models import QueueItem
from .projection import assemble_case_detail
from .runtime import OperationsRuntime


def build_case_router(runtime: OperationsRuntime) -> APIRouter:
    router = APIRouter()

    @router.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/readyz")
    def readyz() -> dict[str, str]:
        settings = runtime.settings
        if (
            settings.runtime_profile in {"staging", "production"}
            and settings.world_runtime_mode != "disabled"
        ):
            try:
                validate_world_runtime_compatibility(settings)
            except ProductionReadinessError as exc:
                raise HTTPException(
                    status_code=503,
                    detail="World Runtime compatibility/readiness check failed",
                ) from exc
        return {
            "status": "ready",
            "auth_mode": settings.auth_mode,
            "runtime_profile": settings.runtime_profile,
            "hris_source": settings.hris_source_kind,
            "iam_source": settings.iam_source_kind,
            "authority_mutation_shortcuts": "forbidden",
            "world_runtime": (
                settings.world_runtime_mode
                if settings.runtime_profile in {"staging", "production"}
                else "not-required"
            ),
        }

    @router.get("/v1/operations/cases", response_model=list[QueueItem])
    def case_queue(
        request: Request,
        status_filter: Annotated[list[CaseStatus] | None, Query(alias="status")] = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    ) -> list[QueueItem]:
        actor = runtime.actor(request)
        runtime.require(actor, AdministrativePermission.OPERATIONS_READ)
        with runtime.store.sessions() as db:
            statement = select(CaseRow).order_by(CaseRow.updated_at.desc()).limit(limit)
            if status_filter:
                statement = statement.where(
                    CaseRow.status.in_([item.value for item in status_filter])
                )
            rows = db.execute(statement).scalars().all()
        return [
            QueueItem(
                case_id=row.case_id,
                case_kind=row.case_kind,
                status=CaseStatus(row.status),
                subject_ref=row.subject_ref,
                requester_principal_id=row.requester_principal_id,
                version=row.version,
                authority_epoch=row.authority_epoch,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    @router.get("/v1/operations/cases/{case_id}")
    def case_detail(case_id: UUID, request: Request) -> dict:
        actor = runtime.actor(request)
        case = runtime.store.get_case(case_id)
        if case is None:
            raise HTTPException(status_code=404, detail="case not found")
        runtime.require(actor, AdministrativePermission.OPERATIONS_READ)
        include_audit = runtime.access.allows(
            actor.principal_id,
            AdministrativePermission.AUDIT_READ,
            case=case,
        )
        return assemble_case_detail(runtime, case, include_audit=include_audit)

    return router


__all__ = ["build_case_router"]
