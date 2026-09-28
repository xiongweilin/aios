from __future__ import annotations

import json
import tomllib
from functools import lru_cache
from importlib.resources import files
from typing import Any

CATALOG_VERSION = "world-runtime-contracts-v12"
CATALOG_OWNER = "world-runtime/contracts"


def _contracts_root():
    return files(__package__)


@lru_cache(maxsize=1)
def contract_catalog() -> dict[str, Any]:
    with _contracts_root().joinpath("catalog.toml").open("rb") as handle:
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
    resource = _contracts_root().joinpath(str(path_value))
    try:
        return json.loads(resource.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"canonical schema is unavailable for {name}") from exc



PUBLIC_CONFORMANCE_SUITE_VERSION = "world-runtime-conformance-v11"


@lru_cache(maxsize=1)
def conformance_vectors() -> dict[str, Any]:
    resource = _contracts_root().joinpath("vectors.json")
    value = json.loads(resource.read_text(encoding="utf-8"))
    if value.get("suite_version") != PUBLIC_CONFORMANCE_SUITE_VERSION:
        raise ValueError("World Runtime conformance suite version mismatch")
    if not isinstance(value.get("vectors"), list) or not value["vectors"]:
        raise ValueError("World Runtime conformance vectors are unavailable")
    return value

def domain_conformance_vectors() -> dict[str, Any]:
    resource = _contracts_root().joinpath("domain", "vectors-v3.json")
    value = json.loads(resource.read_text(encoding="utf-8"))
    if value.get("suite_version") != "domain-controller-protocol-v3":
        raise ValueError("Domain Controller conformance suite version mismatch")
    return value


__all__ = [
    "CATALOG_OWNER",
    "CATALOG_VERSION",
    "PUBLIC_CONFORMANCE_SUITE_VERSION",
    "contract_catalog",
    "contract_descriptor",
    "contract_schema",
    "conformance_vectors",
    "domain_conformance_vectors",
]
