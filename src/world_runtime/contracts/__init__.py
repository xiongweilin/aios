from __future__ import annotations

import json
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any


CATALOG_VERSION = "world-runtime-contracts-v10"
CATALOG_OWNER = "world-runtime/contracts"


def _catalog_path() -> Path:
    path = Path(__file__).with_name("catalog.toml")
    if not path.is_file():
        raise FileNotFoundError("World Runtime canonical contract catalog is unavailable")
    return path


@lru_cache(maxsize=1)
def contract_catalog() -> dict[str, Any]:
    with _catalog_path().open("rb") as handle:
        value = tomllib.load(handle)
    if value.get("catalog_version") != CATALOG_VERSION:
        raise ValueError("World Runtime contract catalog version mismatch")
    if value.get("owner") != CATALOG_OWNER:
        raise ValueError("World Runtime contract catalog owner mismatch")
    if not isinstance(value.get("contracts"), dict) or not value["contracts"]:
        raise ValueError("World Runtime contract catalog has no contracts")
    if not isinstance(value.get("invariants"), dict) or not value["invariants"]:
        raise ValueError("World Runtime contract catalog has no invariants")
    return value


def contract_descriptor(name: str) -> dict[str, Any]:
    contracts = contract_catalog()["contracts"]
    try:
        value = contracts[name]
    except KeyError as exc:
        raise KeyError(f"unknown World Runtime contract: {name}") from exc
    return dict(value)


def contract_schema(name: str) -> dict[str, Any]:
    descriptor = contract_descriptor(name)
    path_value = descriptor.get("schema_path")
    if not path_value:
        raise KeyError(f"World Runtime contract has no canonical schema: {name}")
    path = Path(__file__).parent / str(path_value)
    if not path.is_file():
        raise FileNotFoundError(f"canonical schema is unavailable for {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def domain_conformance_vectors() -> dict[str, Any]:
    path = Path(__file__).parent / "domain" / "vectors-v3.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("suite_version") != "domain-controller-protocol-v3":
        raise ValueError("Domain Controller conformance suite version mismatch")
    return value


__all__ = [
    "CATALOG_OWNER",
    "CATALOG_VERSION",
    "contract_catalog",
    "contract_descriptor",
    "contract_schema",
    "domain_conformance_vectors",
]
