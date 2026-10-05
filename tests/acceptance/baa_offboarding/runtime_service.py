from __future__ import annotations

import os

import uvicorn
from fastapi import HTTPException, Request
from world_runtime.service import create_app

from scripts.domains.administrative.production_world_runtime_stack import build


def main() -> None:
    runtime = build()
    token = os.environ["BAA_RUNTIME_BEARER_TOKEN"]
    principal = os.environ.get(
        "ADMIN_WORLD_RUNTIME_PRINCIPAL",
        "service:administrative-orchestrator",
    )
    runtime.identity.bind_bearer_token(
        principal=principal,
        token=token,
        credential_id="credential:baa-network-experiment",
    )
    app = create_app(runtime)

    @app.get("/acceptance/provider-state")
    async def acceptance_provider_state(request: Request) -> dict[str, object]:
        if request.headers.get("authorization") != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="acceptance token required")
        attempts: dict[str, object] = {}
        idempotency: dict[str, object] = {}
        for row in runtime.ledger.export_projection_rows():
            namespace = str(row.get("namespace") or "")
            key = str(row.get("key") or "")
            value = dict(row.get("value") or {})
            if namespace == "execution.provider-attempt":
                attempts[key] = {
                    "request_id": value.get("request_id"),
                    "provider_id": value.get("provider_id"),
                    "capability": value.get("capability"),
                    "status": value.get("status"),
                }
            elif namespace == "execution.provider-idempotency":
                idempotency[key] = {
                    "request_id": value.get("request_id"),
                    "provider_id": value.get("provider_id"),
                    "status": value.get("status"),
                    "error": value.get("error"),
                }
        return {
            "provider_attempts": attempts,
            "provider_idempotency": idempotency,
        }

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=18086,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
