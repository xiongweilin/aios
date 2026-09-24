from __future__ import annotations

from typing import Any

from ..config import get_settings


def configure_dbos() -> dict[str, Any]:
    """Build the DBOS 2.x configuration for the dedicated worker process."""
    settings = get_settings()
    system_database_url = settings.dbos_system_database_url
    if not system_database_url:
        raise RuntimeError("ADMIN_DBOS_SYSTEM_DATABASE_URL is required for the DBOS worker")
    application_database_url = settings.worker_database_url or settings.database_url
    return {
        "name": "administrative-orchestrator",
        "system_database_url": system_database_url,
        "application_database_url": application_database_url,
        "log_level": settings.log_level,
        "dbos_system_schema": "dbos",
    }


def start_dbos() -> None:
    """Register workflow definitions and launch DBOS; failures propagate."""
    from dbos import DBOS, DBOSConfig

    config = configure_dbos()
    from . import definitions  # noqa: F401

    DBOS(config=DBOSConfig(**config))
    DBOS.launch()


__all__ = ["configure_dbos", "start_dbos"]
