from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from autonomous_development.domain.models import Deployment

_SAFE_DEPLOYMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,80}$")
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def is_local_deployment_url(
    base_url: str,
    *,
    deployment_id: str | None = None,
) -> bool:
    parsed = urlsplit(base_url)
    hostname = parsed.hostname
    if (
        parsed.scheme != "http"
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False
    if hostname in _LOOPBACK_HOSTS:
        return True
    prefix = "autodev-"
    if not hostname.casefold().startswith(prefix):
        return False
    observed_id = hostname[len(prefix) :]
    if not _SAFE_DEPLOYMENT_ID.fullmatch(observed_id):
        return False
    return deployment_id is None or observed_id.casefold() == deployment_id.casefold()


@dataclass(frozen=True, slots=True)
class DeploymentSpec:
    deployment_id: str
    target_id: str
    artifact_id: str
    image_digest: str
    container_port: int

    def __post_init__(self) -> None:
        for label, value in (
            ("deployment_id", self.deployment_id),
            ("target_id", self.target_id),
            ("artifact_id", self.artifact_id),
            ("image_digest", self.image_digest),
        ):
            if not value.strip():
                raise ValueError(f"{label} must be non-empty")
        if not self.image_digest.startswith("sha256:"):
            raise ValueError("deployment requires a content-addressed image")
        if not 1 <= self.container_port <= 65535:
            raise ValueError("container_port must be between 1 and 65535")


@dataclass(frozen=True, slots=True)
class DeploymentRuntime:
    deployment_id: str
    container_id: str
    base_url: str
    evidence_ref: str


class DeploymentProvider(Protocol):
    def ensure(self, spec: DeploymentSpec) -> DeploymentRuntime: ...

    def stop(self, deployment_id: str) -> None: ...


class DeploymentObserver(Protocol):
    def wait_ready(
        self,
        spec: DeploymentSpec,
        runtime: DeploymentRuntime,
        *,
        health_path: str,
        readiness_path: str,
        timeout_seconds: int,
    ) -> Deployment: ...


class DeploymentProviderError(RuntimeError):
    pass


class DeploymentObservationError(RuntimeError):
    pass
