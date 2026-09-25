from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any


def _normalize(value: Any) -> Any:
    if is_dataclass(value):
        data = asdict(value)
        kind = getattr(value, "kind", None)
        if kind is not None:
            data = {"kind": _normalize(kind), **data}
        return _normalize(data)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_normalize(v) for v in value]
    if isinstance(value, set):
        return sorted((_normalize(v) for v in value), key=lambda x: json.dumps(x, sort_keys=True))
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def semantic_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
