from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = REPOSITORY_ROOT / "src/kernel/world_runtime/contracts/vectors.json"
MANIFEST_PATH = Path(__file__).with_name("traceability.json")
SOURCE_BYTES = SOURCE_PATH.read_bytes()
SUITE: dict[str, Any] = json.loads(SOURCE_BYTES)
MANIFEST: dict[str, Any] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
VECTORS: list[dict[str, Any]] = SUITE["vectors"]
TRACEABILITY: dict[str, list[str]] = MANIFEST["traceability"]


def test_public_vector_suite_is_versioned_sha_pinned_and_complete() -> None:
    vector_ids = [vector["id"] for vector in VECTORS]
    assert SUITE["suite_version"] == MANIFEST["suite_version"]
    assert MANIFEST["source_path"] == "src/kernel/world_runtime/contracts/vectors.json"
    assert MANIFEST["schema_version"] == 1
    canonical_source_bytes = SOURCE_BYTES.replace(b"\r\n", b"\n")
    assert hashlib.sha256(canonical_source_bytes).hexdigest() == MANIFEST["source_sha256"]
    assert len(VECTORS) == MANIFEST["vector_count"] == 65
    assert len(vector_ids) == len(set(vector_ids))
    assert set(TRACEABILITY) == set(vector_ids)


@pytest.mark.parametrize("vector", VECTORS, ids=lambda item: item["id"])
def test_each_vector_targets_a_discoverable_behavioral_test(vector: dict[str, Any]) -> None:
    nodeids = TRACEABILITY[vector["id"]]
    assert nodeids, vector["id"]
    for nodeid in nodeids:
        relative_path, separator, test_name = nodeid.partition("::")
        assert separator == "::", (vector["id"], nodeid)
        assert relative_path.startswith("tests/"), (vector["id"], nodeid)
        assert test_name.startswith("test_"), (vector["id"], nodeid)
        test_path = REPOSITORY_ROOT / relative_path
        assert test_path.is_file(), (vector["id"], nodeid)
        tree = ast.parse(test_path.read_text(encoding="utf-8"), filename=relative_path)
        test_functions = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert test_name in test_functions, (vector["id"], nodeid)
