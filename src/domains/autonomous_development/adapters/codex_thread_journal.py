from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from autonomous_development.ports.codex import CodexProviderError


class CodexThreadJournal:
    def __init__(self, root: Path | None, namespace: str) -> None:
        self._root = root
        self._namespace = namespace

    def path(self, resume_key: str | None) -> Path | None:
        if resume_key is None or self._root is None:
            return None
        digest = hashlib.sha256(resume_key.encode("utf-8")).hexdigest()
        directory = self._root / self._namespace if self._namespace else self._root
        return directory / f"{digest}.json"

    def resolve(self, explicit_thread_id: str | None, resume_key: str | None) -> str | None:
        journaled = self.load(resume_key)
        if (
            explicit_thread_id is not None
            and journaled is not None
            and explicit_thread_id != journaled
        ):
            raise CodexProviderError(
                "explicit Codex thread id conflicts with durable thread journal"
            )
        return explicit_thread_id or journaled

    def load(self, resume_key: str | None) -> str | None:
        path = self.path(resume_key)
        if path is None or not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CodexProviderError("Codex thread journal is unreadable") from exc
        if not isinstance(payload, dict):
            raise CodexProviderError("Codex thread journal is malformed")
        thread_id = payload.get("thread_id")
        if not isinstance(thread_id, str) or not thread_id:
            raise CodexProviderError("Codex thread journal thread_id is invalid")
        return thread_id

    def record(self, resume_key: str | None, thread_id: str) -> None:
        path = self.path(resume_key)
        if path is None:
            return
        existing = self.load(resume_key)
        if existing is not None:
            if existing != thread_id:
                raise CodexProviderError(
                    "Codex resume key is already bound to a different thread"
                )
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
        try:
            temporary.write_text(
                json.dumps({"thread_id": thread_id}, separators=(",", ":")),
                encoding="utf-8",
            )
            temporary.replace(path)
        except OSError as exc:
            raise CodexProviderError("Codex thread journal could not be persisted") from exc
        finally:
            temporary.unlink(missing_ok=True)
