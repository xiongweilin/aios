from __future__ import annotations

import os
from datetime import datetime
from uuid import UUID

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query

from personal_world import (
    PERSONAL_WORLD_CONFORMANCE,
    PERSONAL_WORLD_CONTRACT,
    SEMANTIC_LANGUAGE_BASELINE,
    __version__,
)
from personal_world.api.auth import Caller, caller, require_admin
from personal_world.model.contracts import (
    ClaimCreate,
    ContextProjectionRequest,
    DataAccessProfile,
    DomainPersonalProjection,
    ErasureRequest,
    ObservationCreate,
    PersonalFactCreate,
    PersonalWorldBundle,
    PreferenceCreate,
    RedactionRequest,
    RelationshipCreate,
    ResourceLinkCreate,
    RevisionRequest,
    RevalidationRequest,
    SearchRequest,
    SourceDescriptorCreate,
)
from personal_world.persistence import (
    ConcurrencyError,
    NotFoundError,
    SqlAlchemyPersonalWorldStore,
    create_database_engine,
)
from personal_world.privacy import AccessDeniedError
from personal_world.service import AdmissionError, PersonalWorldService


def _service_from_environment() -> PersonalWorldService:
    url = os.getenv("PERSONAL_WORLD_DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("PERSONAL_WORLD_DATABASE_URL is required")
    engine = create_database_engine(url)
    store = SqlAlchemyPersonalWorldStore(engine)
    store.create_schema()
    return PersonalWorldService(store)


def _root_subject_from_environment() -> UUID | None:
    raw = os.getenv("PERSONAL_WORLD_ROOT_SUBJECT_ID", "").strip()
    profile = os.getenv("PERSONAL_WORLD_DEPLOYMENT_PROFILE", "local").strip().lower()
    if not raw:
        if profile == "production":
            raise RuntimeError("production Personal World requires PERSONAL_WORLD_ROOT_SUBJECT_ID")
        return None
    try:
        return UUID(raw)
    except ValueError as exc:
        raise RuntimeError("PERSONAL_WORLD_ROOT_SUBJECT_ID must be a UUID") from exc


def create_app(service: PersonalWorldService | None = None) -> FastAPI:
    runtime = service or _service_from_environment()
    root_subject = _root_subject_from_environment()
    app = FastAPI(
        title="Personal World",
        version=__version__,
        description="Durable user-owned personal context substrate",
    )

    def require_profile(value: Caller) -> Caller:
        profile = runtime.store.get_access_profile(value.service_identity)
        runtime.access.require_purpose(profile, value.purpose)
        return value

    def require_subject(subject_id: UUID) -> None:
        if root_subject is not None and subject_id != root_subject:
            raise HTTPException(
                status_code=403,
                detail="subject is outside this Personal World root-subject boundary",
            )

    def require_record_subject(record_id: UUID) -> None:
        require_subject(runtime.store.get_record(record_id).subject_id)

    def require_object_subject(object_type: str, object_id: UUID) -> None:
        if object_type == "record":
            return require_record_subject(object_id)
        if object_type == "observation":
            return require_subject(runtime.store.get_observation(object_id).subject_id)
        if object_type == "claim":
            return require_subject(runtime.store.get_claim(object_id).subject_id)
        # Sources may be shared provenance within the one-root store and have no subject_id.

    def require_bundle_subjects(bundle: PersonalWorldBundle) -> None:
        if root_subject is None:
            return
        for collection in (bundle.observations, bundle.claims, bundle.records, bundle.disclosures):
            for item in collection:
                raw = item.get("subject_id")
                if raw is not None:
                    try:
                        subject_id = UUID(str(raw))
                    except ValueError as exc:
                        raise HTTPException(status_code=400, detail="bundle subject_id is invalid") from exc
                    require_subject(subject_id)

    @app.exception_handler(NotFoundError)
    async def handle_not_found(_, exc: NotFoundError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConcurrencyError)
    async def handle_concurrency(_, exc: ConcurrencyError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(AdmissionError)
    async def handle_admission(_, exc: AdmissionError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(AccessDeniedError)
    async def handle_access(_, exc: AccessDeniedError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.get("/healthz")
    def healthz():
        return {
            "status": "ok",
            "package": __version__,
            "contract": PERSONAL_WORLD_CONTRACT,
            "conformance": PERSONAL_WORLD_CONFORMANCE,
            "semantic_language": SEMANTIC_LANGUAGE_BASELINE,
        }

    @app.get("/v1/contracts")
    def contracts(value: Caller = Depends(caller)):
        return {
            "manifest": PERSONAL_WORLD_CONTRACT,
            "conformance": PERSONAL_WORLD_CONFORMANCE,
            "package": __version__,
            "semantic_language": SEMANTIC_LANGUAGE_BASELINE,
            "caller": value.service_identity,
        }

    @app.put("/v1/access-profiles")
    def put_access_profile(
        profile: DataAccessProfile,
        value: Caller = Depends(caller),
    ):
        require_admin(value)
        runtime.put_access_profile(profile)
        return profile

    @app.post("/v1/sources")
    def create_source(
        command: SourceDescriptorCreate,
        value: Caller = Depends(caller),
    ):
        require_profile(value)
        return runtime.create_source(command)

    @app.get("/v1/sources/{source_id}")
    def get_source(source_id: UUID, value: Caller = Depends(caller)):
        require_admin(value)
        return runtime.store.get_source(source_id)

    @app.post("/v1/observations")
    def create_observation(
        command: ObservationCreate,
        value: Caller = Depends(caller),
    ):
        require_profile(value)
        require_subject(command.subject_id)
        return runtime.create_observation(command)

    @app.get("/v1/observations/{observation_id}")
    def get_observation(observation_id: UUID, value: Caller = Depends(caller)):
        require_admin(value)
        observation = runtime.store.get_observation(observation_id)
        require_subject(observation.subject_id)
        return observation

    @app.post("/v1/claims")
    def create_claim(command: ClaimCreate, value: Caller = Depends(caller)):
        require_profile(value)
        require_subject(command.subject_id)
        return runtime.create_claim(command)

    @app.get("/v1/claims/{claim_id}")
    def get_claim(claim_id: UUID, value: Caller = Depends(caller)):
        require_admin(value)
        claim = runtime.store.get_claim(claim_id)
        require_subject(claim.subject_id)
        return claim

    @app.post("/v1/facts")
    def create_fact(command: PersonalFactCreate, value: Caller = Depends(caller)):
        require_profile(value)
        require_subject(command.subject_id)
        return runtime.create_fact(command)

    @app.post("/v1/preferences")
    def create_preference(command: PreferenceCreate, value: Caller = Depends(caller)):
        require_profile(value)
        require_subject(command.subject_id)
        return runtime.create_preference(command)

    @app.post("/v1/relationships")
    def create_relationship(command: RelationshipCreate, value: Caller = Depends(caller)):
        require_profile(value)
        require_subject(command.subject_id)
        return runtime.create_relationship(command)

    @app.post("/v1/resource-links")
    def create_resource_link(command: ResourceLinkCreate, value: Caller = Depends(caller)):
        require_profile(value)
        require_subject(command.subject_id)
        return runtime.create_resource_link(command)

    @app.post("/v1/records/{record_id}/revise")
    def revise_record(
        record_id: UUID,
        command: RevisionRequest,
        value: Caller = Depends(caller),
    ):
        require_profile(value)
        require_record_subject(record_id)
        return runtime.revise(record_id, command)

    @app.post("/v1/records/{record_id}/revalidate")
    def revalidate_record(
        record_id: UUID,
        command: RevalidationRequest,
        value: Caller = Depends(caller),
    ):
        require_profile(value)
        require_record_subject(record_id)
        return runtime.revalidate(record_id, command)

    @app.get("/v1/subjects/{subject_id}/current")
    def current_records(
        subject_id: UUID,
        as_of: datetime | None = Query(default=None),
        value: Caller = Depends(caller),
    ):
        require_subject(subject_id)
        return runtime.current_for_subject(
            subject_id,
            service_identity=value.service_identity,
            purpose=value.purpose,
            as_of=as_of,
        )

    @app.get("/v1/subjects/{subject_id}/history")
    def history_records(subject_id: UUID, value: Caller = Depends(caller)):
        require_subject(subject_id)
        return runtime.history_for_subject(
            subject_id,
            service_identity=value.service_identity,
            purpose=value.purpose,
        )

    @app.post("/v1/context-projections")
    def context_projection(
        request: ContextProjectionRequest,
        value: Caller = Depends(caller),
    ):
        if request.purpose != value.purpose:
            raise HTTPException(status_code=400, detail="request purpose must match X-Purpose")
        require_subject(request.subject_id)
        return runtime.project(request, service_identity=value.service_identity)

    @app.post("/v1/model-context")
    def model_context(
        request: ContextProjectionRequest,
        value: Caller = Depends(caller),
    ):
        if request.purpose != value.purpose:
            raise HTTPException(status_code=400, detail="request purpose must match X-Purpose")
        require_subject(request.subject_id)
        return runtime.model_context(request, service_identity=value.service_identity)

    @app.post("/v1/search")
    def search(request: SearchRequest, value: Caller = Depends(caller)):
        if request.purpose != value.purpose:
            raise HTTPException(status_code=400, detail="request purpose must match X-Purpose")
        require_subject(request.subject_id)
        return runtime.search(request, service_identity=value.service_identity)

    @app.post("/v1/domain-projections")
    def ingest_domain_projection(
        projection: DomainPersonalProjection,
        value: Caller = Depends(caller),
    ):
        require_profile(value)
        require_subject(projection.subject_id)
        if projection.source_domain != value.service_identity:
            raise HTTPException(
                status_code=403,
                detail="domain projection source_domain must match authenticated service identity",
            )
        return runtime.ingest_domain_projection(
            projection,
            actor_ref=value.service_identity,
        )

    @app.post("/v1/redactions")
    def redact(command: RedactionRequest, value: Caller = Depends(caller)):
        require_admin(value)
        require_object_subject(command.object_type, command.object_id)
        runtime.redact(command.object_type, command.object_id)
        return {"status": "redacted"}

    @app.get("/v1/disclosure-audit")
    def disclosure_audit(
        subject_id: UUID | None = Query(default=None),
        value: Caller = Depends(caller),
    ):
        require_admin(value)
        if subject_id is not None:
            require_subject(subject_id)
        return runtime.list_disclosures(subject_id)

    @app.post("/v1/erasures")
    def erase(command: ErasureRequest, value: Caller = Depends(caller)):
        require_admin(value)
        require_subject(command.subject_id)
        return runtime.erase(command)

    @app.get("/v1/bundle")
    def export_bundle(value: Caller = Depends(caller)):
        require_admin(value)
        bundle = runtime.export_bundle()
        require_bundle_subjects(bundle)
        return bundle

    @app.post("/v1/bundle/import")
    def import_bundle(bundle: PersonalWorldBundle, value: Caller = Depends(caller)):
        require_admin(value)
        require_bundle_subjects(bundle)
        runtime.import_bundle(bundle)
        return {"status": "imported"}

    return app


def run() -> None:
    uvicorn.run(
        create_app(),
        host=os.getenv("PERSONAL_WORLD_HOST", "0.0.0.0"),
        port=int(os.getenv("PERSONAL_WORLD_PORT", "8080")),
        reload=False,
    )
