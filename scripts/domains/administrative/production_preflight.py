from __future__ import annotations

import os
from pathlib import Path

from administrative_orchestrator.config import get_settings
from administrative_orchestrator.production_readiness import (
    ProductionReadinessError,
    validate_production_connector_isolation,
    validate_production_control_plane,
)


def main() -> int:
    settings = get_settings()
    try:
        validate_production_control_plane(settings)
        validate_production_connector_isolation(settings)
        state_path = _validate_world_runtime_state_path()
        _validate_secret_references(settings)
    except ProductionReadinessError as exc:
        raise SystemExit(f"production preflight failed: {exc}") from exc

    print(
        "production preflight ready: "
        f"world_runtime_state={state_path} auth=oidc hris=odoo iam=keycloak"
    )
    return 0


def _validate_world_runtime_state_path() -> Path:
    raw = os.getenv("WORLD_RUNTIME_ADMIN_PRODUCTION_STATE_PATH", "").strip()
    if not raw:
        raise ProductionReadinessError("WORLD_RUNTIME_ADMIN_PRODUCTION_STATE_PATH is required")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ProductionReadinessError("production World Runtime state path must be absolute")
    parent = path.parent
    if not parent.exists() or not parent.is_dir():
        raise ProductionReadinessError("production World Runtime state parent directory does not exist")
    if not os.access(parent, os.W_OK):
        raise ProductionReadinessError("production World Runtime state parent directory is not writable")
    return path


def _validate_secret_references(settings) -> None:
    names = (
        settings.odoo_reader_secret_env,
        settings.odoo_writer_secret_env,
        settings.odoo_verifier_secret_env,
        settings.odoo_financial_writer_secret_env,
        settings.odoo_financial_verifier_secret_env,
        settings.keycloak_reader_secret_env,
        settings.keycloak_writer_secret_env,
        settings.keycloak_verifier_secret_env,
    )
    missing = sorted({name for name in names if not os.getenv(name, "")})
    if missing:
        raise ProductionReadinessError(
            "configured credential environment variables are unavailable: " + ", ".join(missing)
        )


if __name__ == "__main__":
    raise SystemExit(main())
