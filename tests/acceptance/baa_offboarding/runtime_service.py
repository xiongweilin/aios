from __future__ import annotations

import os

import uvicorn
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
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=18086,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
