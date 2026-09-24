from __future__ import annotations

import hashlib

import pytest

from administrative_orchestrator.intake.artifacts import (
    ArtifactDigestMismatch,
    ArtifactNotFound,
    ArtifactStorageUnavailable,
    ArtifactStore,
    FilesystemArtifactStore,
)


def test_filesystem_artifact_store_is_content_addressed_and_round_trips(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    content = b"verified source representation"
    digest = hashlib.sha256(content).hexdigest()

    first = store.put(content, expected_digest=digest)
    second = store.put(content)

    assert isinstance(store, ArtifactStore)
    assert first == second
    assert first.digest == digest
    assert first.content_digest == digest
    assert first.storage_ref == f"filesystem://sha256/{digest}"
    assert first.size == len(content)
    assert store.get(first.storage_ref) == content
    assert store.verify_digest(first.storage_ref, digest) is True


def test_put_rejects_expected_digest_mismatch(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ArtifactDigestMismatch):
        store.put(b"content", expected_digest="0" * 64)


def test_get_rejects_missing_object(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    missing_ref = f"filesystem://sha256/{'a' * 64}"

    with pytest.raises(ArtifactNotFound):
        store.get(missing_ref)


def test_get_rejects_corrupted_representation(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    stored = store.put(b"original")
    object_path = tmp_path / "artifacts" / "sha256" / stored.digest
    object_path.write_bytes(b"corrupted")

    with pytest.raises(ArtifactDigestMismatch):
        store.get(stored.storage_ref)


def test_verify_digest_rejects_wrong_expected_digest(tmp_path) -> None:
    store = FilesystemArtifactStore(tmp_path / "artifacts")
    stored = store.put(b"content")

    with pytest.raises(ArtifactDigestMismatch):
        store.verify_digest(stored.storage_ref, "0" * 64)


def test_put_reports_unavailable_storage(tmp_path) -> None:
    storage_root = tmp_path / "not-a-directory"
    storage_root.write_bytes(b"occupied")
    store = FilesystemArtifactStore(storage_root)

    with pytest.raises(ArtifactStorageUnavailable):
        store.put(b"content")
