from __future__ import annotations

import hashlib
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_STORAGE_PREFIX = "filesystem://sha256/"


class ArtifactStoreError(RuntimeError):
    """Base error for artifact storage and integrity failures."""


class ArtifactNotFound(ArtifactStoreError):
    """The requested content-addressed object does not exist."""

    def __init__(self, storage_ref: str) -> None:
        self.storage_ref = storage_ref
        super().__init__(f"artifact object not found: {storage_ref}")


class ArtifactDigestMismatch(ArtifactStoreError):
    """The representation does not match the digest that identifies it."""

    def __init__(self, expected_digest: str, actual_digest: str | None) -> None:
        self.expected_digest = expected_digest
        self.actual_digest = actual_digest
        actual = actual_digest or "unavailable"
        super().__init__(f"artifact digest mismatch: expected {expected_digest}, got {actual}")


class ArtifactStorageUnavailable(ArtifactStoreError):
    """The configured artifact storage cannot be read or written."""


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    storage_ref: str
    digest: str
    size: int

    @property
    def content_digest(self) -> str:
        """Alias matching SourceArtifact.content_digest."""

        return self.digest


@runtime_checkable
class ArtifactStore(Protocol):
    """Port for durable, integrity-checked content-addressed artifacts."""

    def put(self, content: bytes, expected_digest: str | None = None) -> StoredArtifact:
        """Store bytes and return their stable content-addressed reference."""

    def get(self, storage_ref: str, expected_digest: str | None = None) -> bytes:
        """Read bytes and fail if the stored representation is not intact."""

    def verify_digest(self, storage_ref: str, expected_digest: str) -> bool:
        """Verify an object against a digest, raising on any failure."""


class FilesystemArtifactStore:
    """Local/staging adapter using atomic SHA-256 content-addressed files.

    This adapter stores raw bytes outside PostgreSQL. Its reference format is
    intentionally explicit so a later object-store adapter can preserve the
    same port without changing durable intake metadata.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def put(self, content: bytes, expected_digest: str | None = None) -> StoredArtifact:
        if not isinstance(content, bytes):
            raise TypeError("artifact content must be bytes")

        digest = _sha256(content)
        expected = _normalise_digest(expected_digest) if expected_digest is not None else None
        if expected is not None and expected != digest:
            raise ArtifactDigestMismatch(expected, digest)

        storage_dir = self.root / "sha256"
        self._ensure_storage_dir(storage_dir, create=True)
        target = self._object_path(storage_dir, digest)

        if target.exists():
            existing = self._read(target, f"filesystem://sha256/{digest}")
            actual = _sha256(existing)
            if actual != digest:
                raise ArtifactDigestMismatch(digest, actual)
            return _stored_artifact(digest, len(existing))

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=storage_dir,
                prefix=".artifact-",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, target)
        except OSError as exc:
            raise ArtifactStorageUnavailable("artifact storage is not writable") from exc
        finally:
            if temporary_path is not None and temporary_path.exists():
                with suppress(OSError):
                    temporary_path.unlink()

        return _stored_artifact(digest, len(content))

    def get(self, storage_ref: str, expected_digest: str | None = None) -> bytes:
        digest = _digest_from_storage_ref(storage_ref)
        expected = _normalise_digest(expected_digest) if expected_digest is not None else None
        if expected is not None and expected != digest:
            raise ArtifactDigestMismatch(expected, digest)

        storage_dir = self.root / "sha256"
        self._ensure_storage_dir(storage_dir, create=False)
        target = self._object_path(storage_dir, digest)
        content = self._read(target, storage_ref)
        actual = _sha256(content)
        if actual != digest:
            raise ArtifactDigestMismatch(digest, actual)
        return content

    def verify_digest(self, storage_ref: str, expected_digest: str) -> bool:
        self.get(storage_ref, expected_digest=expected_digest)
        return True

    def _ensure_storage_dir(self, storage_dir: Path, *, create: bool) -> None:
        try:
            if self.root.exists() and not self.root.is_dir():
                raise ArtifactStorageUnavailable("artifact storage root is not a directory")
            if storage_dir.exists() and not storage_dir.is_dir():
                raise ArtifactStorageUnavailable("artifact storage digest directory is not a directory")
            if create:
                storage_dir.mkdir(parents=True, exist_ok=True)
        except ArtifactStorageUnavailable:
            raise
        except OSError as exc:
            raise ArtifactStorageUnavailable("artifact storage is unavailable") from exc

    @staticmethod
    def _object_path(storage_dir: Path, digest: str) -> Path:
        target = storage_dir / digest
        try:
            target.resolve(strict=False).relative_to(storage_dir.resolve(strict=False))
        except ValueError as exc:
            raise ArtifactStorageUnavailable("artifact storage path escaped its root") from exc
        return target

    @staticmethod
    def _read(target: Path, storage_ref: str) -> bytes:
        try:
            if not target.exists():
                raise ArtifactNotFound(storage_ref)
            return target.read_bytes()
        except ArtifactNotFound:
            raise
        except FileNotFoundError as exc:
            raise ArtifactNotFound(storage_ref) from exc
        except OSError as exc:
            raise ArtifactStorageUnavailable("artifact storage is not readable") from exc


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _normalise_digest(digest: str) -> str:
    if not isinstance(digest, str):
        raise ArtifactStoreError("artifact digest must be a SHA-256 hex string")
    normalised = digest.strip().lower()
    if not _DIGEST_PATTERN.fullmatch(normalised):
        raise ArtifactStoreError("artifact digest must be a SHA-256 hex string")
    return normalised


def _digest_from_storage_ref(storage_ref: str) -> str:
    if not isinstance(storage_ref, str) or not storage_ref.startswith(_STORAGE_PREFIX):
        raise ArtifactStoreError("unsupported artifact storage reference")
    return _normalise_digest(storage_ref[len(_STORAGE_PREFIX) :])


def _stored_artifact(digest: str, size: int) -> StoredArtifact:
    return StoredArtifact(
        storage_ref=f"{_STORAGE_PREFIX}{digest}",
        digest=digest,
        size=size,
    )


__all__ = [
    "ArtifactDigestMismatch",
    "ArtifactNotFound",
    "ArtifactStorageUnavailable",
    "ArtifactStore",
    "ArtifactStoreError",
    "FilesystemArtifactStore",
    "StoredArtifact",
]
