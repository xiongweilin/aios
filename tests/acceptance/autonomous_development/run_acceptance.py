from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

Report = dict[str, Any]
LOCAL_HTTP = build_opener(ProxyHandler({}))
_CONFIG_PREFIXES = (
    "ADMIN_",
    "AIOS_",
    "AUTODEV_",
    "CONTROL_PLANE_",
    "PERSONAL_WORLD_",
    "WORLD_RUNTIME_",
)
_COMPOSE_ENV_KEYS = {
    "COMPOSE_DOCKER_CLI_BUILD",
    "COMPOSE_ENV_FILES",
    "COMPOSE_FILE",
    "COMPOSE_PROFILES",
    "COMPOSE_PROJECT_NAME",
}


def _redact(value: str, secrets_to_redact: Sequence[str]) -> str:
    for secret in secrets_to_redact:
        if secret:
            value = value.replace(secret, "[redacted]")
    value = re.sub(
        r"(?i)(postgres(?:ql)?(?:\+\w+)?://[^:/@\s]+:)[^@\s]+@",
        r"\1[redacted]@",
        value,
    )
    value = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[redacted]", value)
    value = re.sub(
        r"(?i)((?:password|token|secret)(?:[\"'\s:=]+))[^,\s\"'}]+",
        r"\1[redacted]",
        value,
    )
    return value


def _run(
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    capture_output: bool = True,
    secrets_to_redact: Sequence[str] = (),
) -> str:
    result = subprocess.run(
        list(command),
        cwd=cwd,
        env=None if env is None else dict(env),
        check=False,
        capture_output=capture_output,
        text=True,
    )
    if result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        output = _redact(output, secrets_to_redact)
        raise RuntimeError(
            f"{Path(command[0]).name} failed with exit {result.returncode}: {output[-1600:]}"
        )
    return (result.stdout or "").strip()


def _resource_exists(kind: str, name: str) -> bool:
    result = subprocess.run(
        ["docker", kind, "inspect", name],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True
    error = f"{result.stdout}\n{result.stderr}".lower()
    if "no such" in error or "not found" in error:
        return False
    raise RuntimeError(f"Could not inspect temporary Docker {kind} {name}.")


def _http_json(url: str, *, method: str = "GET", payload: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        response = LOCAL_HTTP.open(request, timeout=5)
    except HTTPError as error:
        raw_body = error.read()
        try:
            body = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            body = {}
        return error.code, body
    with response:
        raw_body = response.read()
        body = json.loads(raw_body) if raw_body else {}
        return response.status, body


def _wait_for_status(
    base_url: str,
    path: str,
    *,
    expected_status: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_failure = "no response"
    while time.monotonic() < deadline:
        try:
            status_code, body = _http_json(f"{base_url}{path}")
        except (OSError, TimeoutError, URLError, ValueError) as error:
            last_failure = type(error).__name__
        else:
            if status_code == 200 and body.get("status") == expected_status:
                return body
            checks = body.get("checks", [])
            failed_checks = [
                str(check.get("name", "unknown"))
                for check in checks
                if isinstance(check, dict) and check.get("ready") is False
            ]
            last_failure = f"HTTP {status_code}"
            if failed_checks:
                last_failure += ", checks=" + ",".join(sorted(failed_checks))
        time.sleep(1)
    raise RuntimeError(f"{path} did not reach {expected_status}: {last_failure}")


def _wait_for_service(base_url: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_failure = "health/readiness not yet successful"
    while time.monotonic() < deadline:
        try:
            health_code, health = _http_json(f"{base_url}/health")
            ready_code, ready = _http_json(f"{base_url}/ready")
        except (OSError, TimeoutError, URLError, ValueError) as error:
            last_failure = type(error).__name__
        else:
            if (
                health_code == 200
                and health.get("status") == "ok"
                and ready_code == 200
                and ready.get("status") == "ready"
            ):
                return
            last_failure = f"health={health_code}, readiness={ready_code}"
        time.sleep(1)
    raise RuntimeError(f"Target did not become ready: {last_failure}")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _clean_subprocess_environment() -> dict[str, str]:
    allowed = {
        "APPDATA",
        "DOCKER_CONFIG",
        "DOCKER_CONTEXT",
        "HOME",
        "LOCALAPPDATA",
        "PATH",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "RUNNER_TEMP",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "WINDIR",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _compose_prefix(repo_root: Path, project_name: str, override_file: Path) -> list[str]:
    if os.name == "nt":
        compose_executable = shutil.which("docker-compose.exe") or shutil.which("docker-compose")
        if compose_executable is None:
            raise RuntimeError("Docker Compose executable was not found on PATH.")
        command = [compose_executable]
    else:
        command = ["docker", "compose"]
    return [
        *command,
        "--project-name",
        project_name,
        "--project-directory",
        str(repo_root),
        "--env-file",
        str(repo_root / ".env.example"),
        "-f",
        str(repo_root / "compose.yaml"),
        "-f",
        str(override_file),
    ]


def _windows_buildx_executable() -> str:
    docker_executable = shutil.which("docker.exe") or shutil.which("docker")
    if docker_executable is None:
        raise RuntimeError("Docker CLI was not found on PATH.")
    buildx = Path(docker_executable).resolve().parent.parent / "cli-plugins" / "docker-buildx.exe"
    if not buildx.is_file():
        raise RuntimeError("Docker Buildx executable was not found next to the Docker CLI.")
    return str(buildx)


def _prepare_target_repository(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".ruff_cache"),
    )
    (destination / ".dockerignore").write_text(".git\n__pycache__\n.pytest_cache\n", encoding="utf-8")
    git_env = _clean_subprocess_environment()
    _run(["git", "init", "--initial-branch=main"], cwd=destination, env=git_env)
    _run(["git", "config", "user.name", "AIOS Acceptance"], cwd=destination, env=git_env)
    _run(
        ["git", "config", "user.email", "aios-acceptance@example.invalid"],
        cwd=destination,
        env=git_env,
    )
    _run(["git", "config", "core.filemode", "false"], cwd=destination, env=git_env)
    _run(["git", "config", "core.autocrlf", "false"], cwd=destination, env=git_env)
    hooks = destination / ".git" / "acceptance-hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    _run(["git", "config", "core.hooksPath", str(hooks)], cwd=destination, env=git_env)
    _run(["git", "config", "commit.gpgsign", "false"], cwd=destination, env=git_env)
    _run(["git", "add", "--all"], cwd=destination, env=git_env)
    _run(["git", "commit", "--message", "acceptance baseline"], cwd=destination, env=git_env)
    if _run(["git", "status", "--porcelain"], cwd=destination, env=git_env):
        raise RuntimeError("Temporary acceptance target repository is not clean.")


def _host_build_root_image(
    repo_root: Path,
    image_tag: str,
    env: Mapping[str, str],
    secrets_to_redact: Sequence[str],
) -> None:
    if os.name != "nt":
        return
    app_root_line = next(
        (
            line
            for line in (repo_root / ".env.example").read_text(encoding="utf-8").splitlines()
            if line.startswith("AIOS_CONTAINER_APP_ROOT=")
        ),
        None,
    )
    if app_root_line is None:
        raise RuntimeError("AIOS_CONTAINER_APP_ROOT is missing from .env.example.")
    app_root = app_root_line.split("=", maxsplit=1)[1]
    _run(
        [
            _windows_buildx_executable(),
            "build",
            "--network=host",
            "--allow",
            "network.host",
            "--load",
            "--tag",
            image_tag,
            "--build-arg",
            f"AIOS_APP_ROOT={app_root}",
            str(repo_root),
        ],
        cwd=repo_root,
        env=env,
        capture_output=False,
        secrets_to_redact=secrets_to_redact,
    )


def _build_target_image(
    target_repo: Path,
    image_tag: str,
    env: Mapping[str, str],
    secrets_to_redact: Sequence[str],
) -> None:
    if os.name == "nt":
        command = [
            _windows_buildx_executable(),
            "build",
            "--network=host",
            "--allow",
            "network.host",
            "--load",
            "--platform=linux/amd64",
            "--tag",
            image_tag,
            "--file",
            "Dockerfile",
            ".",
        ]
    else:
        command = [
            "docker",
            "build",
            "--progress=plain",
            "--platform=linux/amd64",
            "--tag",
            image_tag,
            "--file",
            "Dockerfile",
            ".",
        ]
    _run(
        command,
        cwd=target_repo,
        env=env,
        capture_output=False,
        secrets_to_redact=secrets_to_redact,
    )


def _scan_target_image(
    root_image: str,
    target_image: str,
    evidence_dir: Path,
    env: Mapping[str, str],
    secrets_to_redact: Sequence[str],
) -> dict[str, str]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    sbom_path = evidence_dir / "acceptance-sbom.cyclonedx.json"
    grype_path = evidence_dir / "acceptance-grype.txt"
    host_network = ["--network", "host"] if os.name == "nt" else []
    docker_socket = [
        "--mount",
        "type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock",
        "--env",
        "DOCKER_HOST=unix:///var/run/docker.sock",
    ]
    syft_command = [
        "docker",
        "run",
        "--rm",
        *host_network,
        *docker_socket,
        "--entrypoint",
        "/usr/local/bin/syft",
        root_image,
        f"docker:{target_image}",
        "-o",
        "cyclonedx-json",
    ]
    sbom_text = _run(
        syft_command,
        env=env,
        secrets_to_redact=secrets_to_redact,
    )
    sbom_path.write_text(sbom_text + "\n", encoding="utf-8")
    sbom = json.loads(sbom_text)
    components = sbom.get("components", [])
    observed: dict[str, set[str]] = {}
    for component in components:
        if not isinstance(component, dict):
            continue
        name = str(component.get("name", "")).lower().replace("_", "-")
        version = str(component.get("version", ""))
        observed.setdefault(name, set()).add(version)
    expected = {
        "zlib": "1.3.2.1-r0",
        "fastapi": "0.141.1",
        "uvicorn": "0.53.0",
        "anyio": "4.15.1",
        "h11": "0.16.0",
        "idna": "3.20",
    }
    missing = {
        name: version
        for name, version in expected.items()
        if version not in observed.get(name, set())
    }
    if missing:
        raise RuntimeError("SBOM is missing pinned target package versions: " + ", ".join(sorted(missing)))

    grype_command = [
        "docker",
        "run",
        "--rm",
        *host_network,
        *docker_socket,
        "--entrypoint",
        "/usr/local/bin/grype",
        root_image,
        f"docker:{target_image}",
        "--fail-on",
        "high",
    ]
    result = subprocess.run(
        grype_command,
        check=False,
        capture_output=True,
        env=dict(env),
        text=True,
    )
    grype_output = _redact(
        f"{result.stdout or ''}{result.stderr or ''}", secrets_to_redact
    )
    grype_path.write_text(grype_output, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"Grype high-severity gate failed with exit {result.returncode}.")
    return {"sbom": sbom_path.name, "vulnerability_report": grype_path.name}


def _compose_resources_exist(project_name: str) -> bool:
    checks = (
        ["docker", "ps", "--quiet", "--all", "--filter", f"label=com.docker.compose.project={project_name}"],
        ["docker", "volume", "ls", "--quiet", "--filter", f"label=com.docker.compose.project={project_name}"],
        ["docker", "network", "ls", "--quiet", "--filter", f"label=com.docker.compose.project={project_name}"],
    )
    for command in checks:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError("Could not verify acceptance Compose teardown.")
        if result.stdout.strip():
            return True
    return False


def _write_evidence(path: Path, report: Report) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _capture_autodev_logs(
    compose_prefix: Sequence[str],
    repo_root: Path,
    env: Mapping[str, str],
    secrets_to_redact: Sequence[str],
) -> str:
    result = subprocess.run(
        [*compose_prefix, "logs", "--tail", "100", "autonomous-development"],
        cwd=repo_root,
        env=dict(env),
        check=False,
        capture_output=True,
        text=True,
    )
    logs = _redact(f"{result.stdout or ''}{result.stderr or ''}", secrets_to_redact)
    return logs[-12000:]


def _capture_target_diagnostics(
    container_name: str,
    secrets_to_redact: Sequence[str],
) -> str:
    state = subprocess.run(
        ["docker", "inspect", "--format", "{{json .State}}", container_name],
        check=False,
        capture_output=True,
        text=True,
    )
    logs = subprocess.run(
        ["docker", "logs", "--tail", "80", container_name],
        check=False,
        capture_output=True,
        text=True,
    )
    payload = {
        "state": _redact((state.stdout or state.stderr or "").strip(), secrets_to_redact),
        "logs": _redact(f"{logs.stdout or ''}{logs.stderr or ''}", secrets_to_redact)[-8000:],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _clear_readonly_and_retry(function: Any, path: str, error: OSError) -> None:
    if isinstance(error, FileNotFoundError):
        return
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
    function(path)


def _remove_temp_tree_if_present(path: Path) -> None:
    try:
        shutil.rmtree(path, onexc=_clear_readonly_and_retry)
    except FileNotFoundError:
        try:
            path.stat()
        except FileNotFoundError:
            return
        raise


def run_acceptance(evidence_path: Path | None) -> int:
    run_id = uuid.uuid4().hex[:12]
    project_name = f"aios-acceptance-{run_id}"
    root_image = f"aios-acceptance-runtime:{run_id}"
    target_image = f"aios-acceptance-target:{run_id}"
    repo_root = Path(__file__).resolve().parents[3]
    target_source = Path(__file__).resolve().parent / "target"
    override_file = Path(__file__).resolve().parent / "compose.acceptance.yaml"
    deployment_id = f"acceptance-deployment-{run_id}"
    target_container = f"autodev-{deployment_id}"
    report: Report = {
        "schema_version": 1,
        "run_id": run_id,
        "project_name": project_name,
        "status": "running",
        "steps": [],
    }
    stage = "setup"
    temp_root: Path | None = None
    compose_prefix: list[str] | None = None
    compose_env: dict[str, str] = {}
    secrets_to_redact: list[str] = []
    cleanup_errors: list[str] = []

    def mark(name: str, status: str, **details: Any) -> None:
        report["steps"].append({"name": name, "status": status, **details})
        print(f"[acceptance] {name}: {status}", flush=True)

    try:
        runner_temp = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir()))
        runner_temp.mkdir(parents=True, exist_ok=True)
        temp_root = Path(tempfile.mkdtemp(prefix=f"{project_name}-", dir=runner_temp))
        paths = {
            "postgres": temp_root / "postgres",
            "control_plane": temp_root / "control-plane",
            "admin_artifacts": temp_root / "admin-artifacts",
            "autodev_state": temp_root / "autodev-state",
            "secrets": temp_root / "secrets",
            "maps": temp_root / "path-maps",
            "target_repo": temp_root / "target-repository",
        }
        for name, path in paths.items():
            if name != "target_repo":
                path.mkdir(parents=True, exist_ok=True)

        compose_env = _clean_subprocess_environment()
        for key in tuple(compose_env):
            if key.upper().startswith(_CONFIG_PREFIXES) or key.upper() in _COMPOSE_ENV_KEYS:
                compose_env.pop(key)

        database_password = secrets.token_hex(32)
        codex_token = secrets.token_urlsafe(32)
        operator_secret = secrets.token_urlsafe(32)
        secrets_to_redact = [database_password, codex_token, operator_secret]
        token_path = paths["secrets"] / "codex-ws-token"
        operator_path = paths["secrets"] / "operator-hmac"
        token_path.write_text(codex_token, encoding="utf-8")
        operator_path.write_text(operator_secret, encoding="utf-8")
        if os.name != "nt":
            token_path.chmod(0o600)
            operator_path.chmod(0o600)

        target_repo = paths["target_repo"]
        _prepare_target_repository(target_source, target_repo)
        path_map = {
            "version": 1,
            "roots": [
                {"containerRoot": "/workspace", "hostRoot": str(repo_root.resolve())},
                {
                    "containerRoot": "/data/autonomous-development",
                    "hostRoot": str(paths["autodev_state"].resolve()),
                },
                {"containerRoot": "/acceptance-target", "hostRoot": str(target_repo.resolve())},
            ],
        }
        autodev_path_map = paths["maps"] / "autodev-path-map.json"
        control_plane_path_map = paths["maps"] / "control-plane-path-map.json"
        _write_json(autodev_path_map, path_map)
        _write_json(
            control_plane_path_map,
            {
                "version": 1,
                "roots": [
                    {
                        "containerRoot": "/data/control-plane",
                        "hostRoot": str(paths["control_plane"].resolve()),
                    }
                ],
            },
        )

        compose_env.update(
            {
                "AIOS_IMAGE": root_image,
                "AIOS_POSTGRES_USER": "aios",
                "AIOS_POSTGRES_PASSWORD": database_password,
                "AIOS_HOST_POSTGRES_DATA_ROOT": str(paths["postgres"].resolve()),
                "AIOS_HOST_CODEX_APP_SERVER_TOKEN_FILE": str(token_path.resolve()),
                "AIOS_HOST_OPERATOR_HMAC_SECRET_FILE": str(operator_path.resolve()),
                "CONTROL_PLANE_HOST_DATA_ROOT": str(paths["control_plane"].resolve()),
                "CONTROL_PLANE_HOST_CODEX_PATH_MAP_FILE": str(control_plane_path_map.resolve()),
                "ADMIN_HOST_ARTIFACT_ROOT": str(paths["admin_artifacts"].resolve()),
                "AUTODEV_HOST_STATE_ROOT": str(paths["autodev_state"].resolve()),
                "AUTODEV_HOST_WORKSPACE_ROOT": str(repo_root.resolve()),
                "AUTODEV_HOST_DOCKER_SOCKET": "/var/run/docker.sock",
                "AUTODEV_HOST_CODEX_PATH_MAP_FILE": str(autodev_path_map.resolve()),
                "AUTODEV_DOCKER_NETWORK": f"{project_name}_default",
                "AIOS_ACCEPTANCE_HOST_TARGET_ROOT": str(target_repo.resolve()),
                "AIOS_PROMETHEUS_HOST_PORT": "",
                "AIOS_PERSONAL_WORLD_HOST_PORT": "",
                "AIOS_WORLD_RUNTIME_HOST_PORT": "",
                "AIOS_CONTROL_PLANE_HOST_PORT": "",
                "AIOS_ADMINISTRATIVE_API_HOST_PORT": "",
                "AIOS_AUTODEV_HOST_PORT": "",
            }
        )
        compose_prefix = _compose_prefix(repo_root, project_name, override_file)

        stage = "compose-config"
        _run(
            [*compose_prefix, "config", "--quiet"],
            cwd=repo_root,
            env=compose_env,
            secrets_to_redact=secrets_to_redact,
        )
        mark("compose-config", "passed")

        stage = "runtime-image-build"
        _host_build_root_image(repo_root, root_image, compose_env, secrets_to_redact)
        if os.name != "nt":
            _run(
                [*compose_prefix, "build", "autonomous-development"],
                cwd=repo_root,
                env=compose_env,
                capture_output=False,
                secrets_to_redact=secrets_to_redact,
            )
        root_image_id = _run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", root_image],
            env=compose_env,
            secrets_to_redact=secrets_to_redact,
        )
        report["runtime_image_id"] = root_image_id
        mark("runtime-image-build", "passed", image_id=root_image_id)

        stage = "target-image-build"
        _build_target_image(target_repo, target_image, compose_env, secrets_to_redact)
        target_image_id = _run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", target_image],
            env=compose_env,
            secrets_to_redact=secrets_to_redact,
        )
        report["target_image_id"] = target_image_id
        mark("target-image-build", "passed", image_id=target_image_id)

        stage = "sbom-and-vulnerability-scan"
        report["security_evidence"] = _scan_target_image(
            root_image,
            target_image,
            evidence_path.parent if evidence_path is not None else runner_temp / "aios-acceptance",
            compose_env,
            secrets_to_redact,
        )
        mark("sbom-and-vulnerability-scan", "passed")

        stage = "database-and-migration-startup"
        _run(
            [
                *compose_prefix,
                "up",
                "--detach",
                "--no-build",
                "postgres",
                "prometheus",
                "autodev-migrate",
                "acceptance-codex",
            ],
            cwd=repo_root,
            env=compose_env,
            capture_output=False,
            secrets_to_redact=secrets_to_redact,
        )
        mark("database-and-migration-startup", "passed")

        stage = "bootstrap-serving-release"
        with (target_repo / "autonomous-development.toml").open("rb") as stream:
            target_contract = tomllib.load(stream)
        target_id = str(target_contract["target_id"])
        created_at = datetime.now(UTC).isoformat()
        objective_id = f"acceptance-objective-{run_id}"
        release_id = f"acceptance-release-{run_id}"
        manifest_host_path = paths["autodev_state"] / "acceptance-bootstrap.json"
        _write_json(
            manifest_host_path,
            {
                "target_id": target_id,
                "repository": "/acceptance-target",
                "default_branch": "main",
                "objective": {
                    "id": objective_id,
                    "statement": "Maintain a persistent, read-back-verifiable acceptance task.",
                    "acceptance_criteria": [
                        "A task is written once to target reality.",
                        "The stored task can be read back after a container restart.",
                    ],
                    "primary_metrics": ["acceptance task verification"],
                    "reliability_constraints": ["No duplicate task effect."],
                    "performance_constraints": [],
                    "security_constraints": ["Task IDs cannot escape the state root."],
                    "mutation_policy": {
                        "allowed_paths": ["app.py", "tests"],
                        "forbidden_paths": [
                            "Dockerfile",
                            "requirements.txt",
                            "autonomous-development.toml",
                        ],
                        "max_changed_files": 5,
                        "max_implementation_attempts": 1,
                    },
                    "created_at": created_at,
                },
                "baseline_release": {
                    "id": release_id,
                    "artifact_digest": target_image_id,
                    "deployment_id": deployment_id,
                    "promoted_at": created_at,
                },
            },
        )
        bootstrap = _run(
            [
                *compose_prefix,
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "--entrypoint",
                "autonomous-development",
                "autonomous-development",
                "bootstrap",
                "--manifest",
                "/data/autonomous-development/acceptance-bootstrap.json",
            ],
            cwd=repo_root,
            env=compose_env,
            secrets_to_redact=secrets_to_redact,
        )
        bootstrap_result = json.loads(bootstrap.splitlines()[-1])
        if bootstrap_result.get("status") != "bootstrapped":
            raise RuntimeError("Autodev did not bootstrap the acceptance serving release.")
        report["target_id"] = target_contract["target_id"]
        report["deployment_id"] = deployment_id
        mark("bootstrap-serving-release", "passed", target_id=target_id)

        stage = "compose-startup"
        _run(
            [*compose_prefix, "up", "--detach", "--no-build", "autonomous-development"],
            cwd=repo_root,
            env=compose_env,
            capture_output=False,
            secrets_to_redact=secrets_to_redact,
        )
        autodev_binding = _run(
            [*compose_prefix, "port", "autonomous-development", "8765"],
            cwd=repo_root,
            env=compose_env,
            secrets_to_redact=secrets_to_redact,
        )
        autodev_host_port = int(autodev_binding.splitlines()[0].rsplit(":", maxsplit=1)[1])
        autodev_url = f"http://127.0.0.1:{autodev_host_port}"
        report["autodev_url"] = autodev_url
        mark("compose-startup", "passed", project_name=project_name)

        stage = "runtime-health"
        _wait_for_status(
            autodev_url,
            "/health",
            expected_status="ok",
            timeout_seconds=120,
        )
        mark("runtime-health", "passed")

        stage = "runtime-readiness"
        _wait_for_status(
            autodev_url,
            "/ready",
            expected_status="ready",
            timeout_seconds=120,
        )
        mark("runtime-readiness", "passed")

        stage = "target-health-readiness"
        container_port = int(target_contract["deployment"]["container_port"])
        target_binding = _run(
            ["docker", "port", target_container, f"{container_port}/tcp"],
            env=compose_env,
            secrets_to_redact=secrets_to_redact,
        )
        target_host_port = int(target_binding.splitlines()[0].rsplit(":", maxsplit=1)[1])
        target_url = f"http://127.0.0.1:{target_host_port}"
        report["target_url"] = target_url
        _wait_for_service(target_url, int(target_contract["deployment"]["startup_timeout_seconds"]))
        mark("target-health-readiness", "passed")

        task_id = f"ci-{run_id}"
        task_value = "  Acceptance Reality Read-back  "
        expected_result = "acceptance reality read-back"
        stage = "real-task"
        status_code, created = _http_json(
            f"{target_url}/tasks",
            method="POST",
            payload={"task_id": task_id, "value": task_value},
        )
        if status_code != 201 or created.get("result") != expected_result:
            raise RuntimeError(f"Task execution failed with HTTP {status_code}.")
        mark("real-task", "passed", task_id=task_id)

        stage = "target-restart"
        _run(["docker", "restart", target_container], env=compose_env)
        target_binding = _run(
            ["docker", "port", target_container, f"{container_port}/tcp"],
            env=compose_env,
            secrets_to_redact=secrets_to_redact,
        )
        target_host_port = int(target_binding.splitlines()[0].rsplit(":", maxsplit=1)[1])
        target_url = f"http://127.0.0.1:{target_host_port}"
        report["target_url_after_restart"] = target_url
        _wait_for_service(target_url, int(target_contract["deployment"]["startup_timeout_seconds"]))
        mark("target-restart", "passed")

        stage = "reality-readback"
        status_code, readback = _http_json(f"{target_url}/reality/{task_id}")
        if status_code != 200:
            raise RuntimeError(f"Reality read-back failed with HTTP {status_code}.")
        target_state_path = f"/tmp/aios-acceptance-state/{task_id}.json"
        stored = _run(
            [
                "docker",
                "exec",
                target_container,
                "python",
                "-c",
                "import json,sys; print(json.dumps(json.loads(open(sys.argv[1], encoding='utf-8').read()), sort_keys=True))",
                target_state_path,
            ],
            env=compose_env,
            secrets_to_redact=secrets_to_redact,
        )
        container_record = json.loads(stored)
        if readback != container_record:
            raise RuntimeError("API reality read-back differs from the task record in the target container.")
        mark("reality-readback", "passed")

        stage = "postgres-restart-recovery"
        postgres_container_id = _run(
            [*compose_prefix, "ps", "--quiet", "postgres"],
            cwd=repo_root,
            env=compose_env,
            secrets_to_redact=secrets_to_redact,
        )
        if not postgres_container_id:
            raise RuntimeError("PostgreSQL container was not available for restart recovery.")
        _run(["docker", "restart", postgres_container_id], env=compose_env)
        _wait_for_status(autodev_url, "/ready", expected_status="ready", timeout_seconds=120)
        status_code, postgres_recovered = _http_json(f"{target_url}/reality/{task_id}")
        if status_code != 200 or postgres_recovered != container_record:
            raise RuntimeError("Task reality did not survive PostgreSQL restart.")
        mark("postgres-restart-recovery", "passed")

        stage = "autodev-graceful-shutdown"
        autodev_container_id = _run(
            [*compose_prefix, "ps", "--quiet", "autonomous-development"],
            cwd=repo_root,
            env=compose_env,
            secrets_to_redact=secrets_to_redact,
        )
        _run(
            [*compose_prefix, "stop", "--timeout", "30", "autonomous-development"],
            cwd=repo_root,
            env=compose_env,
            secrets_to_redact=secrets_to_redact,
        )
        autodev_state = _run(
            ["docker", "inspect", "--format", "{{.State.Status}}|{{.State.ExitCode}}", autodev_container_id],
            env=compose_env,
            secrets_to_redact=secrets_to_redact,
        )
        if autodev_state != "exited|0":
            raise RuntimeError(f"Autodev did not shut down cleanly: {autodev_state}")
        mark("autodev-graceful-shutdown", "passed", state=autodev_state)

        stage = "autodev-restart-recovery"
        _run(
            [*compose_prefix, "start", "autonomous-development"],
            cwd=repo_root,
            env=compose_env,
            secrets_to_redact=secrets_to_redact,
        )
        autodev_binding = _run(
            [*compose_prefix, "port", "autonomous-development", "8765"],
            cwd=repo_root,
            env=compose_env,
            secrets_to_redact=secrets_to_redact,
        )
        autodev_host_port = int(autodev_binding.splitlines()[0].rsplit(":", maxsplit=1)[1])
        autodev_url = f"http://127.0.0.1:{autodev_host_port}"
        _wait_for_status(autodev_url, "/health", expected_status="ok", timeout_seconds=120)
        _wait_for_status(autodev_url, "/ready", expected_status="ready", timeout_seconds=120)
        status_code, recovered = _http_json(f"{target_url}/reality/{task_id}")
        if status_code != 200 or recovered != container_record:
            raise RuntimeError("Task reality did not survive Autodev service restart.")
        mark("autodev-restart-recovery", "passed")

        stage = "autodev-crash-recovery"
        _run(["docker", "kill", "--signal=KILL", autodev_container_id], env=compose_env)
        crash_state = _run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Status}}|{{.State.ExitCode}}",
                autodev_container_id,
            ],
            env=compose_env,
            secrets_to_redact=secrets_to_redact,
        )
        if crash_state != "exited|137":
            raise RuntimeError(f"Autodev did not record a SIGKILL crash: {crash_state}")
        _run(
            [*compose_prefix, "start", "autonomous-development"],
            cwd=repo_root,
            env=compose_env,
            secrets_to_redact=secrets_to_redact,
        )
        autodev_binding = _run(
            [*compose_prefix, "port", "autonomous-development", "8765"],
            cwd=repo_root,
            env=compose_env,
            secrets_to_redact=secrets_to_redact,
        )
        autodev_host_port = int(autodev_binding.splitlines()[0].rsplit(":", maxsplit=1)[1])
        autodev_url = f"http://127.0.0.1:{autodev_host_port}"
        report["autodev_url_after_crash_recovery"] = autodev_url
        _wait_for_status(autodev_url, "/health", expected_status="ok", timeout_seconds=120)
        _wait_for_status(autodev_url, "/ready", expected_status="ready", timeout_seconds=120)
        status_code, crash_recovered = _http_json(f"{target_url}/reality/{task_id}")
        if status_code != 200 or crash_recovered != container_record:
            raise RuntimeError("Task reality did not survive an ungraceful Autodev crash.")
        mark("autodev-crash-recovery", "passed", state=crash_state)

        stage = "verify"
        if (
            readback.get("task_id") != task_id
            or readback.get("status") != "completed"
            or readback.get("result") != expected_result
        ):
            raise RuntimeError("Reality did not match the expected completed task.")
        report["task"] = {
            "task_id": task_id,
            "expected_result": expected_result,
            "verified_result": readback["result"],
        }
        mark("verify", "passed")
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["failure"] = {
            "stage": stage,
            "type": type(error).__name__,
            "message": _redact(str(error), secrets_to_redact)[:1600],
        }
        if compose_prefix is not None and stage in {
            "runtime-health",
            "bootstrap-serving-release",
            "runtime-readiness",
            "postgres-restart-recovery",
            "autodev-graceful-shutdown",
            "autodev-restart-recovery",
            "autodev-crash-recovery",
        }:
            try:
                diagnostics = _capture_autodev_logs(
                    compose_prefix,
                    repo_root,
                    compose_env,
                    secrets_to_redact,
                )
                if diagnostics:
                    report["autodev_diagnostics"] = diagnostics
                    print("[acceptance] redacted Autodev startup diagnostics:", file=sys.stderr)
                    print(diagnostics, file=sys.stderr)
            except Exception as diagnostic_error:
                report["diagnostics_error"] = type(diagnostic_error).__name__
        if stage in {"target-health-readiness", "real-task", "target-restart", "reality-readback"}:
            try:
                diagnostics = _capture_target_diagnostics(target_container, secrets_to_redact)
                report["target_diagnostics"] = diagnostics
                print("[acceptance] target diagnostics:", file=sys.stderr)
                print(diagnostics, file=sys.stderr)
            except Exception as diagnostic_error:
                report["target_diagnostics_error"] = type(diagnostic_error).__name__
        print(
            f"[acceptance] {stage}: failed ({type(error).__name__}: "
            f"{_redact(str(error), secrets_to_redact)[:1000]})",
            file=sys.stderr,
        )
    finally:
        teardown_ok = True
        docker_teardown_safe = True
        target_container_name = f"autodev-{deployment_id}"
        try:
            if _resource_exists("container", target_container_name):
                _run(
                    ["docker", "container", "rm", "--force", target_container_name],
                    env=compose_env,
                    secrets_to_redact=secrets_to_redact,
                )
            if _resource_exists("container", target_container_name):
                raise RuntimeError("Temporary target container remained after removal.")
        except Exception as error:
            teardown_ok = False
            docker_teardown_safe = False
            cleanup_errors.append(f"target container cleanup: {type(error).__name__}")

        if compose_prefix is not None:
            try:
                _run(
                    [*compose_prefix, "down", "--volumes", "--remove-orphans"],
                    cwd=repo_root,
                    env=compose_env,
                    capture_output=False,
                    secrets_to_redact=secrets_to_redact,
                )
                if _compose_resources_exist(project_name):
                    raise RuntimeError("Temporary Compose resources remained after teardown.")
            except Exception as error:
                teardown_ok = False
                docker_teardown_safe = False
                cleanup_errors.append(f"Compose cleanup: {type(error).__name__}")

        if temp_root is not None and temp_root.exists() and docker_teardown_safe:
            try:
                runner_temp = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())).resolve()
                resolved_temp_root = temp_root.resolve()
                if (
                    resolved_temp_root.parent != runner_temp
                    or not resolved_temp_root.name.startswith(f"{project_name}-")
                ):
                    raise RuntimeError("Refusing to remove a path outside the isolated acceptance temp root.")
                try:
                    _remove_temp_tree_if_present(temp_root)
                except PermissionError:
                    if os.name == "nt" or not _resource_exists("image", root_image):
                        raise
                    _run(
                        [
                            "docker",
                            "run",
                            "--rm",
                            "--network",
                            "none",
                            "--user",
                            "0:0",
                            "--mount",
                            f"type=bind,source={resolved_temp_root},target=/cleanup",
                            "--entrypoint",
                            "/bin/sh",
                            root_image,
                            "-c",
                            "chmod -R u+rwX /cleanup && rm -rf /cleanup/* /cleanup/.[!.]* /cleanup/..?*",
                        ],
                        env=compose_env,
                        secrets_to_redact=secrets_to_redact,
                    )
                    _remove_temp_tree_if_present(temp_root)
                if temp_root.exists():
                    raise RuntimeError("Temporary acceptance directory remained after cleanup.")
            except Exception as error:
                teardown_ok = False
                cleanup_errors.append(f"temporary directory cleanup: {type(error).__name__}")

        for image_tag in (target_image, root_image):
            try:
                if _resource_exists("image", image_tag):
                    _run(
                        ["docker", "image", "rm", image_tag],
                        env=compose_env,
                        secrets_to_redact=secrets_to_redact,
                    )
                if _resource_exists("image", image_tag):
                    raise RuntimeError("Temporary image remained after removal.")
            except Exception as error:
                teardown_ok = False
                cleanup_errors.append(f"image cleanup: {type(error).__name__}")

        report["cleanup_errors"] = cleanup_errors
        report["status"] = "failed" if cleanup_errors else report["status"]
        mark("teardown", "passed" if teardown_ok else "failed")
        if evidence_path is not None:
            try:
                _write_evidence(evidence_path, report)
                print(f"[acceptance] evidence: {evidence_path}", flush=True)
            except OSError as error:
                report["status"] = "failed"
                print(f"[acceptance] evidence write failed: {type(error).__name__}", file=sys.stderr)

    return 0 if report["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated AIOS Autonomous Development acceptance.")
    parser.add_argument("--evidence-path", type=Path)
    arguments = parser.parse_args()
    return run_acceptance(arguments.evidence_path)


if __name__ == "__main__":
    raise SystemExit(main())
