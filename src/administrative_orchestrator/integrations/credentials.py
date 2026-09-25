from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class CredentialResolutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CredentialRef:
    configuration_ref: str
    environment_variable: str


class CredentialResolver(Protocol):
    def resolve(self, ref: CredentialRef) -> str: ...


class EnvironmentCredentialResolver:
    """Resolve a secret at process edge without persisting its value.

    Domain records, Kernel contracts, logs and provider bindings should retain
    only `configuration_ref`; the resolved secret is intentionally ephemeral.
    """

    def resolve(self, ref: CredentialRef) -> str:
        value = os.environ.get(ref.environment_variable, "")
        if not value:
            raise CredentialResolutionError(
                f"credential configuration {ref.configuration_ref!r} is unavailable"
            )
        return value


def read_credential_file(path: str, *, configuration_ref: str) -> str:
    """Read a configured credential file without ever including its value in errors."""

    candidate = Path(path)
    if not path or candidate.is_symlink() or not candidate.is_file():
        raise CredentialResolutionError(
            f"credential configuration {configuration_ref!r} is unavailable"
        )
    try:
        value = candidate.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise CredentialResolutionError(
            f"credential configuration {configuration_ref!r} is unavailable"
        ) from exc
    if not value:
        raise CredentialResolutionError(
            f"credential configuration {configuration_ref!r} is unavailable"
        )
    return value


class EnvironmentOrFileCredentialResolver:
    """Resolve process-edge credentials from env, with an explicit file fallback."""

    def __init__(self, file_by_environment_variable: Mapping[str, str] | None = None):
        self._file_by_environment_variable = dict(file_by_environment_variable or {})

    def resolve(self, ref: CredentialRef) -> str:
        value = os.environ.get(ref.environment_variable, "")
        if value:
            return value
        file_path = self._file_by_environment_variable.get(ref.environment_variable, "")
        if file_path:
            return read_credential_file(
                file_path,
                configuration_ref=ref.configuration_ref,
            )
        raise CredentialResolutionError(
            f"credential configuration {ref.configuration_ref!r} is unavailable"
        )


__all__ = [
    "CredentialRef",
    "CredentialResolutionError",
    "CredentialResolver",
    "EnvironmentCredentialResolver",
    "EnvironmentOrFileCredentialResolver",
    "read_credential_file",
]
