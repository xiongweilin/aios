from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from autonomous_development.ports.codex import (
    CodexEvent,
    CodexOutcomeUnknown,
    CodexProvider,
    CodexProviderError,
    CodexTurnRequest,
    CodexTurnResult,
)
from ..codex_thread_journal import CodexThreadJournal
from integrations.codex_app_server import CodexBridgeError, RemoteCodexAppServer


class CodexExecProvider(CodexProvider):
    """Run a bounded implementation turn through the non-interactive Codex CLI."""

    def __init__(
        self,
        *,
        command: Sequence[str] = ("codex",),
        thread_journal_root: Path | None = None,
        remote_app_server: RemoteCodexAppServer | None = None,
    ) -> None:
        if not command:
            raise ValueError("Codex CLI command must be non-empty")
        if thread_journal_root is not None and not thread_journal_root.is_absolute():
            raise ValueError("Codex thread journal root must be absolute")
        self._command = tuple(command)
        self._thread_journal = CodexThreadJournal(thread_journal_root, "exec")
        self._remote_app_server = remote_app_server

    def run_turn(self, request: CodexTurnRequest) -> CodexTurnResult:
        if self._remote_app_server is not None:
            return self._run_remote_turn(request)
        if request.output_schema is not None:
            raise CodexProviderError("Codex CLI provider does not support output schemas")
        thread_id = self._resolve_thread_id(request)
        args = [*self._command, "exec"]
        if thread_id is None:
            args.extend(("--sandbox", request.sandbox.value))
        else:
            args.append("resume")
        if request.model:
            args.extend(("--model", request.model))
        args.extend(("--skip-git-repo-check", "--json"))
        if thread_id is not None:
            args.append(thread_id)
        args.append(request.prompt)

        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        existing_pytest_options = environment.get("PYTEST_ADDOPTS", "").split()
        if (
            "-p" not in existing_pytest_options
            or "no:cacheprovider" not in existing_pytest_options
        ):
            environment["PYTEST_ADDOPTS"] = " ".join(
                (*existing_pytest_options, "-p", "no:cacheprovider")
            )
        process = subprocess.Popen(
            args,
            cwd=request.cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            stdout, _stderr = process.communicate(timeout=request.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            _terminate(process)
            raise CodexProviderError("Codex CLI turn timed out") from exc

        if process.returncode != 0:
            raise CodexProviderError(f"Codex CLI exited with code {process.returncode}")
        return self._result(stdout, request, thread_id)

    def _run_remote_turn(self, request: CodexTurnRequest) -> CodexTurnResult:
        if request.output_schema is not None:
            raise CodexProviderError("Codex CLI provider does not support output schemas")
        prompt_digest = hashlib.sha256(request.prompt.encode("utf-8")).hexdigest()[:24]
        request_id = request.request_id or f"autodev-engineering:{request.resume_key or 'turn'}:{prompt_digest}"
        try:
            result = self._remote_app_server.run_turn(
                request_id=request_id,
                prompt=request.prompt,
                cwd=request.cwd.resolve(strict=True),
                sandbox=request.sandbox.value,
                thread_id=self._resolve_thread_id(request),
                resume_key=request.resume_key,
                model=request.model,
                timeout_seconds=request.timeout_seconds,
            )
        except CodexBridgeError as exc:
            if exc.outcome == "unknown":
                raise CodexOutcomeUnknown(
                    exc.request_id or request_id,
                    f"remote Codex turn outcome is unknown: {exc}",
                ) from exc
            raise CodexProviderError(f"remote Codex turn failed: {exc}") from exc
        self._record_thread(request.resume_key, result.thread_id)
        events = tuple(
            CodexEvent(
                method=str(event["method"]),
                params=(event.get("params") if isinstance(event.get("params"), Mapping) else {}),
            )
            for event in result.events
            if isinstance(event.get("method"), str)
        )
        return CodexTurnResult(
            thread_id=result.thread_id,
            turn_id=result.turn_id,
            status=result.status,
            events=events,
            agent_messages=result.agent_messages,
        )

    def _result(
        self,
        stdout: str,
        request: CodexTurnRequest,
        requested_thread_id: str | None,
    ) -> CodexTurnResult:
        events: list[CodexEvent] = []
        agent_messages: list[str] = []
        thread_id = requested_thread_id
        completed = False
        for line in stdout.splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            event_type = payload.get("type")
            if not isinstance(event_type, str):
                continue
            events.append(CodexEvent(method=event_type, params=dict(payload)))
            if event_type == "thread.started":
                started = payload.get("thread_id")
                if isinstance(started, str) and started:
                    thread_id = started
                    self._record_thread(request.resume_key, started)
            elif event_type == "item.completed":
                item = payload.get("item")
                if isinstance(item, Mapping) and item.get("type") in {
                    "agent_message",
                    "agentMessage",
                }:
                    text = item.get("text")
                    if isinstance(text, str) and text:
                        agent_messages.append(text)
            elif event_type == "turn.completed":
                completed = True

        if thread_id is None:
            raise CodexProviderError("Codex CLI did not return a thread identity")
        if not completed:
            raise CodexProviderError("Codex CLI did not complete the turn")
        return CodexTurnResult(
            thread_id=thread_id,
            turn_id=f"{thread_id}:turn",
            status="completed",
            events=tuple(events),
            agent_messages=tuple(agent_messages),
        )

    def _resolve_thread_id(self, request: CodexTurnRequest) -> str | None:
        return self._thread_journal.resolve(request.thread_id, request.resume_key)

    def _load_thread(self, resume_key: str | None) -> str | None:
        return self._thread_journal.load(resume_key)

    def _record_thread(self, resume_key: str | None, thread_id: str) -> None:
        self._thread_journal.record(resume_key, thread_id)

    def _journal_path(self, resume_key: str | None) -> Path | None:
        return self._thread_journal.path(resume_key)


def _terminate(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
