"""Control-plane-owned Codex CLI capability provider."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal, Protocol

from .provider_protocol import (
    CapabilityRequest,
    CapabilityResult,
    InvocationContext,
    ProviderDescriptor,
    ProviderHealth,
)

logger = logging.getLogger(__name__)
SandboxProfile = Literal["read-only", "workspace-write"]


class PreparedExecutionBoundary(Protocol):
    @property
    def cwd(self) -> Path: ...
    @property
    def env(self) -> Mapping[str, str]: ...
    def cleanup(self) -> None: ...


class ExecutionBoundary(Protocol):
    session_dir: Path

    def prepare(self, repo: str, sandbox: SandboxProfile) -> PreparedExecutionBoundary: ...
    def redact_transcript(self, text: str) -> str: ...


CODEX_SANDBOX_BY_CAPABILITY: Final[Mapping[str, SandboxProfile]] = MappingProxyType(
    {
        "reason.generate": "read-only",
        "code.read": "read-only",
        "git.diff": "read-only",
        "code.edit": "workspace-write",
        "code.test": "workspace-write",
        "shell.exec": "workspace-write",
    }
)


def _resolve_cli(explicit: str | Path | None) -> Path:
    if explicit:
        return Path(explicit)
    found = shutil.which("codex.cmd") or shutil.which("codex")
    return Path(found) if found else Path("codex")


class CodexProvider:
    """Codex CLI is a control-plane provider, not a World Runtime primitive."""

    def __init__(
        self,
        *,
        provider_id: str = "codex-primary",
        model: str = "gpt-5.6-luna",
        cli: str | Path | None = None,
        gateway_base_url: str | None = None,
        execution_boundary: ExecutionBoundary | None = None,
    ) -> None:
        self._cli = _resolve_cli(cli)
        self._model = model
        self._gateway_base_url = gateway_base_url
        self._execution_boundary = execution_boundary
        self._descriptor = ProviderDescriptor(
            id=provider_id,
            name="Control Plane Codex",
            version="2.0.0",
            capabilities=list(CODEX_SANDBOX_BY_CAPABILITY),
            priority=10,
            tags={"control-plane", "external-tool"},
            metadata={
                "model": model,
                "cli": str(self._cli),
                "gateway_base_url": gateway_base_url or "",
            },
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    async def health(self) -> ProviderHealth:
        try:
            proc = await asyncio.create_subprocess_exec(
                str(self._cli),
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        except (FileNotFoundError, TimeoutError, OSError) as exc:
            return ProviderHealth(provider_id=self.descriptor.id, available=False, detail=str(exc))
        out = (stdout or b"").decode("utf-8", errors="replace").strip()
        err = (stderr or b"").decode("utf-8", errors="replace").strip()
        return ProviderHealth(
            provider_id=self.descriptor.id,
            available=proc.returncode == 0,
            detail=(out or err)[:300],
        )

    async def invoke(
        self, request: CapabilityRequest, context: InvocationContext
    ) -> CapabilityResult:
        prompt = request.instruction or str(request.parameters.get("prompt", "") or "")
        if not prompt:
            return CapabilityResult(
                request_id=request.id,
                provider_id=self.descriptor.id,
                status="failed",
                error={"type": "invalid_request", "message": "prompt required"},
            )
        sandbox = CODEX_SANDBOX_BY_CAPABILITY.get(request.capability, "read-only")
        repo = str(request.parameters.get("repo", "") or "")
        cwd = Path(repo) if repo else Path.cwd()
        boundary = None
        if self._execution_boundary is not None:
            boundary = self._execution_boundary.prepare(str(cwd), sandbox)
            cwd = boundary.cwd
        env = dict(boundary.env) if boundary is not None else None
        model = str(request.parameters.get("model", self._model))
        argv = [
            str(self._cli),
            "exec",
            "--model",
            model,
            "--sandbox",
            sandbox,
            "--skip-git-repo-check",
            "--json",
            prompt,
        ]
        started = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(cwd),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=request.timeout_seconds or 900
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                return CapabilityResult(
                    request_id=request.id,
                    provider_id=self.descriptor.id,
                    status="failed",
                    error={"type": "timeout", "message": "codex session timed out"},
                    metadata={"sandbox": sandbox},
                )
        except OSError as exc:
            return CapabilityResult(
                request_id=request.id,
                provider_id=self.descriptor.id,
                status="failed",
                error={"type": "process_start", "message": str(exc)},
            )
        finally:
            if boundary is not None:
                boundary.cleanup()

        out = (stdout or b"").decode("utf-8", errors="replace")
        err = (stderr or b"").decode("utf-8", errors="replace")
        duration_ms = int((time.monotonic() - started) * 1000)
        if self._execution_boundary is not None and out:
            try:
                stored = self._execution_boundary.redact_transcript(out)
                self._execution_boundary.session_dir.mkdir(parents=True, exist_ok=True)
                path = self._execution_boundary.session_dir / f"{request.id}.jsonl"
                header = json.dumps(
                    {
                        "type": "control_plane_meta",
                        "run_id": request.run_id or context.run_id,
                        "request_id": request.id,
                    },
                    ensure_ascii=False,
                )
                path.write_text(header + "\n" + stored[:200_000], encoding="utf-8")
            except OSError:
                logger.debug("unable to persist codex transcript", exc_info=True)
        status = "succeeded" if proc.returncode == 0 else "failed"
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status=status,
            message=(out if out else err)[:20_000],
            error=(
                None
                if status == "succeeded"
                else {"type": "codex_exit", "exit_code": proc.returncode}
            ),
            metadata={
                "duration_ms": duration_ms,
                "model": model,
                "sandbox": sandbox,
                "capability": request.capability,
            },
        )

    async def cancel(self, request_id: str) -> None:
        del request_id

    async def reconcile(self, request_id: str) -> CapabilityResult | None:
        del request_id
        return None
