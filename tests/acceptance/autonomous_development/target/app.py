from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

_TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class TaskSubmission(BaseModel):
    task_id: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=4096)


def create_app(state_root: Path | None = None) -> FastAPI:
    root = state_root or Path(os.environ.get("AIOS_ACCEPTANCE_STATE_ROOT", "/state"))
    app = FastAPI(title="Autonomous Development Acceptance Target")

    def task_path(task_id: str) -> Path:
        if not _TASK_ID_PATTERN.fullmatch(task_id):
            raise HTTPException(status_code=422, detail="invalid task id")
        return root / f"{task_id}.json"

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> dict[str, str]:
        try:
            root.mkdir(parents=True, exist_ok=True)
            descriptor, probe = tempfile.mkstemp(prefix=".readiness-", dir=root)
            os.close(descriptor)
            Path(probe).unlink()
        except OSError as exc:
            raise HTTPException(status_code=503, detail="state root is not writable") from exc
        return {"status": "ready"}

    @app.get("/answer")
    def answer(value: str = "hello") -> dict[str, str]:
        return {"answer": value.strip().lower()}

    @app.post("/tasks", status_code=201)
    def execute_task(submission: TaskSubmission) -> dict[str, str]:
        root.mkdir(parents=True, exist_ok=True)
        destination = task_path(submission.task_id)
        record = {
            "task_id": submission.task_id,
            "status": "completed",
            "value": submission.value,
            "result": submission.value.strip().lower(),
        }
        try:
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail="task id already exists") from exc
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(record, stream, ensure_ascii=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail="task state could not be persisted") from exc
        return record

    @app.get("/reality/{task_id}")
    def reality_readback(task_id: str) -> dict[str, str]:
        source = task_path(task_id)
        try:
            record = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="task reality not found") from exc
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail="task reality is malformed") from exc
        return record

    return app


app = create_app()
