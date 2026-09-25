from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from world_runtime import WorldRuntime
from world_runtime.service import create_app


def create_world_runtime() -> WorldRuntime:
    root_principal = os.getenv("WORLD_RUNTIME_ROOT_PRINCIPAL", "").strip() or None
    runtime_id = os.getenv("WORLD_RUNTIME_ID", "world-runtime").strip() or "world-runtime"
    postgres_dsn = os.getenv("WORLD_RUNTIME_POSTGRES_DSN", "").strip()

    if postgres_dsn:
        return WorldRuntime.postgres(
            postgres_dsn,
            schema=os.getenv("WORLD_RUNTIME_POSTGRES_SCHEMA", "public"),
            runtime_id=runtime_id,
            root_principal=root_principal,
        )

    raw_path = os.getenv("WORLD_RUNTIME_SQLITE_PATH", "").strip()
    if not raw_path:
        raise RuntimeError(
            "WORLD_RUNTIME_POSTGRES_DSN or WORLD_RUNTIME_SQLITE_PATH is required"
        )
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise RuntimeError("WORLD_RUNTIME_SQLITE_PATH must be an absolute path")
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return WorldRuntime.sqlite(path, runtime_id=runtime_id, root_principal=root_principal)


def create_world_runtime_app():
    return create_app(create_world_runtime())


def run_world_runtime() -> None:
    uvicorn.run(
        create_world_runtime_app(),
        host=os.getenv("WORLD_RUNTIME_HOST", "0.0.0.0"),
        port=int(os.getenv("WORLD_RUNTIME_PORT", "8086")),
        log_level=os.getenv("WORLD_RUNTIME_LOG_LEVEL", "info"),
    )
