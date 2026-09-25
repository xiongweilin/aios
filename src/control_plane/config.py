from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigurationError(RuntimeError):
    pass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_text(name: str, fallback: object = "") -> str:
    raw = os.getenv(name)
    if raw is not None:
        return raw.strip()
    return str(fallback or "").strip()


def _resolve_codex_cli(explicit: str = "") -> Path | None:
    if explicit.strip():
        return Path(explicit).expanduser()
    found = shutil.which("codex.cmd") or shutil.which("codex")
    return Path(found) if found else None


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    return dict(value) if isinstance(value, dict) else {}


def _normalized(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _configured_path(name: str, fallback: object = "") -> Path:
    raw = _env_text(name, fallback)
    if not raw:
        raise ConfigurationError(f"{name} is required")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ConfigurationError(f"{name} must be an absolute path")
    return path.resolve()


def _optional_config_path(explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit.expanduser().resolve()
    raw = os.getenv("CONTROL_PLANE_CONFIG_PATH", "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ConfigurationError("CONTROL_PLANE_CONFIG_PATH must be an absolute path")
    return path.resolve()


@dataclass(frozen=True, slots=True)
class ControlPlaneConfig:
    """Control-plane deployment/profile configuration.

    Runtime paths are injected by deployment configuration. Direct construction
    remains available for tests and explicit embedding.
    """

    host: str = "127.0.0.1"
    port: int = 18083
    api_key: str = ""
    owner_principal: str = "human:owner"

    state_db: Path | None = None
    world_runtime_base_url: str = "http://world-runtime:8086"
    world_runtime_timeout_seconds: float = 3.0
    world_runtime_bearer_token: str = ""
    world_runtime_delegation_id: str = ""
    artifact_root: Path | None = None
    agent_session_dir: Path | None = None

    diagnosis_model: str = "gpt-5.6-luna"
    execution_model: str = "gpt-5.6-luna"
    codex_cli: Path | None = None
    gateway_base_url: str = ""
    codex_isolate_worktree: bool = True
    codex_disable_docker: bool = True
    codex_disable_ssh_credentials: bool = True
    codex_worktree_root: Path | None = None
    max_agent_output_bytes: int = 200_000

    prometheus_url: str = ""
    alertmanager_url: str = ""
    notification_enabled: bool = True
    cooldown_seconds: int = 600
    max_concurrent: int = 2

    environment_enabled: bool = True
    environment_cache_seconds: int = 60
    environment_probe_timeout_seconds: int = 30
    docker_build_cache_max_bytes: int = 5 * 1024**3
    docker_expected_exited_containers: tuple[str, ...] = ()
    line_ending_auto_discard_repos: tuple[str, ...] = ()
    recovery_paths: tuple[str, ...] = ()
    synchronization_paths: tuple[str, ...] = ()
    chezmoi_source_dir: str = ""
    known_garbage_paths: tuple[str, ...] = ()
    garbage_quarantine_dir: str = ""
    automatic_handling_enabled: bool = False
    auto_maintenance_alertnames: tuple[str, ...] = ("ControlPlaneGarbageDetected",)

    allowed_auto_projects: tuple[str, ...] = ()
    project_dirs: dict[str, str] = field(default_factory=dict)
    allowed_repo_roots: tuple[str, ...] = ()

    @property
    def model(self) -> str:
        return self.diagnosis_model

    def repo_allowed(self, repo: str | Path) -> bool:
        candidate = _normalized(repo)
        for root in self.allowed_repo_roots:
            normalized_root = _normalized(root)
            try:
                if os.path.commonpath([candidate, normalized_root]) == normalized_root:
                    return True
            except ValueError:
                continue
        return False

    def auto_project_for_repo(self, repo: str | Path) -> str | None:
        candidate = _normalized(repo)
        for project in self.allowed_auto_projects:
            project_dir = self.project_dirs.get(project)
            if project_dir and candidate == _normalized(project_dir):
                return project
        return None

    @classmethod
    def load(cls, path: Path | None = None) -> ControlPlaneConfig:
        base = cls()
        config_path = _optional_config_path(path)
        data: dict[str, Any] = {}
        if config_path is not None:
            if not config_path.is_file():
                raise ConfigurationError(f"Control Plane config not found: {config_path}")
            with config_path.open("rb") as handle:
                data = tomllib.load(handle)

        server = _section(data, "server")
        runtime = _section(data, "runtime")
        model = _section(data, "model")
        monitoring = _section(data, "monitoring")
        policy = _section(data, "policy")
        environment = _section(data, "environment")
        projects = _section(data, "projects")

        api_key = os.getenv("CONTROL_PLANE_API_KEY", "").strip()
        if not api_key:
            raise ConfigurationError("CONTROL_PLANE_API_KEY is required")

        raw_project_dirs = projects.get("project_dirs", base.project_dirs)
        project_dirs = (
            {str(k): str(v) for k, v in raw_project_dirs.items()}
            if isinstance(raw_project_dirs, dict)
            else dict(base.project_dirs)
        )
        legacy_model = str(model.get("name", "")).strip()

        return cls(
            host=_env_text("CONTROL_PLANE_HOST", server.get("host", base.host)),
            port=int(_env_text("CONTROL_PLANE_PORT", server.get("port", base.port))),
            api_key=api_key,
            owner_principal=_env_text(
                "CONTROL_PLANE_OWNER_PRINCIPAL",
                runtime.get("owner_principal", base.owner_principal),
            ),
            state_db=_configured_path(
                "CONTROL_PLANE_STATE_DB",
                runtime.get("state_db", ""),
            ),
            world_runtime_base_url=_env_text(
                "CONTROL_PLANE_WORLD_RUNTIME_BASE_URL",
                runtime.get("base_url", base.world_runtime_base_url),
            ),
            world_runtime_timeout_seconds=float(
                runtime.get("timeout_seconds", base.world_runtime_timeout_seconds)
            ),
            world_runtime_bearer_token=os.getenv(
                "CONTROL_PLANE_WORLD_RUNTIME_BEARER_TOKEN", ""
            ).strip(),
            world_runtime_delegation_id=os.getenv(
                "CONTROL_PLANE_WORLD_RUNTIME_DELEGATION_ID", ""
            ).strip(),
            artifact_root=_configured_path(
                "CONTROL_PLANE_ARTIFACT_ROOT",
                runtime.get("artifact_root", ""),
            ),
            agent_session_dir=_configured_path(
                "CONTROL_PLANE_AGENT_SESSION_DIR",
                model.get("session_dir", ""),
            ),
            diagnosis_model=str(model.get("diagnosis_model", legacy_model or base.diagnosis_model)),
            execution_model=str(model.get("execution_model", base.execution_model)),
            codex_cli=_resolve_codex_cli(
                _env_text("CONTROL_PLANE_AGENT_EXECUTABLE", model.get("codex_cli", ""))
            ),
            gateway_base_url=_env_text(
                "CONTROL_PLANE_AGENT_BASE_URL",
                model.get("gateway_base_url", base.gateway_base_url),
            ),
            codex_isolate_worktree=bool(model.get("isolate_worktree", base.codex_isolate_worktree)),
            codex_disable_docker=bool(model.get("disable_docker", base.codex_disable_docker)),
            codex_disable_ssh_credentials=bool(
                model.get("disable_ssh_credentials", base.codex_disable_ssh_credentials)
            ),
            codex_worktree_root=_configured_path(
                "CONTROL_PLANE_AGENT_WORKTREE_ROOT",
                model.get("worktree_root", ""),
            ),
            max_agent_output_bytes=int(model.get("max_output_bytes", base.max_agent_output_bytes)),
            prometheus_url=_env_text(
                "CONTROL_PLANE_PROMETHEUS_URL",
                monitoring.get("prometheus_url", policy.get("prometheus_url", base.prometheus_url)),
            ),
            alertmanager_url=_env_text(
                "CONTROL_PLANE_ALERTMANAGER_URL",
                monitoring.get(
                    "alertmanager_url",
                    policy.get("alertmanager_url", base.alertmanager_url),
                ),
            ),
            notification_enabled=_env_bool(
                "CONTROL_PLANE_NOTIFICATIONS",
                bool(
                    monitoring.get(
                        "notification_enabled",
                        _section(data, "notifications").get("enabled", base.notification_enabled),
                    )
                ),
            ),
            cooldown_seconds=int(policy.get("cooldown_seconds", base.cooldown_seconds)),
            max_concurrent=max(1, int(policy.get("max_concurrent", base.max_concurrent))),
            environment_enabled=_env_bool(
                "CONTROL_PLANE_ENVIRONMENT_CHECKS",
                bool(environment.get("enabled", base.environment_enabled)),
            ),
            environment_cache_seconds=int(
                environment.get("cache_seconds", base.environment_cache_seconds)
            ),
            environment_probe_timeout_seconds=int(
                environment.get("probe_timeout_seconds", base.environment_probe_timeout_seconds)
            ),
            docker_build_cache_max_bytes=int(
                environment.get("docker_build_cache_max_bytes", base.docker_build_cache_max_bytes)
            ),
            docker_expected_exited_containers=tuple(
                str(v)
                for v in environment.get(
                    "docker_expected_exited_containers",
                    base.docker_expected_exited_containers,
                )
            ),
            line_ending_auto_discard_repos=tuple(
                str(v)
                for v in environment.get(
                    "line_ending_auto_discard_repos",
                    base.line_ending_auto_discard_repos,
                )
            ),
            recovery_paths=tuple(
                str(v) for v in environment.get("recovery_paths", base.recovery_paths)
            ),
            synchronization_paths=tuple(
                str(v)
                for v in environment.get("synchronization_paths", base.synchronization_paths)
            ),
            chezmoi_source_dir=_env_text(
                "CONTROL_PLANE_CHEZMOI_SOURCE_DIR",
                environment.get("chezmoi_source_dir", base.chezmoi_source_dir),
            ),
            known_garbage_paths=tuple(
                str(v)
                for v in environment.get("known_garbage_paths", base.known_garbage_paths)
            ),
            garbage_quarantine_dir=_env_text(
                "CONTROL_PLANE_GARBAGE_QUARANTINE_DIR",
                environment.get("garbage_quarantine_dir", base.garbage_quarantine_dir),
            ),
            automatic_handling_enabled=_env_bool(
                "CONTROL_PLANE_AUTOMATIC_HANDLING",
                bool(
                    environment.get(
                        "automatic_handling_enabled",
                        base.automatic_handling_enabled,
                    )
                ),
            ),
            auto_maintenance_alertnames=tuple(
                str(v)
                for v in environment.get(
                    "auto_maintenance_alertnames",
                    base.auto_maintenance_alertnames,
                )
            ),
            allowed_auto_projects=tuple(
                str(v) for v in projects.get("allowed_auto", base.allowed_auto_projects)
            ),
            project_dirs=project_dirs,
            allowed_repo_roots=tuple(
                str(v) for v in projects.get("allowed_repo_roots", base.allowed_repo_roots)
            ),
        )
