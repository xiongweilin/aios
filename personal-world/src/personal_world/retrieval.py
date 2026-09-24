from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Any

from personal_world.model.contracts import PersonalRecord, SearchHit

_TOKEN = re.compile(r"[\w\-.:/]+", re.UNICODE)
_VECTOR_SIZE = 128


def record_text(record: PersonalRecord) -> str:
    semantic_key = (
        f"{record.semantic.namespace}:"
        f"{record.semantic.kind_value}:"
        f"{record.semantic.id}:"
        f"{record.semantic.version}"
    )
    parts: list[str] = [semantic_key, _stringify(record.value)]
    if record.context:
        parts.append(_stringify(record.context))
    if record.target_ref:
        parts.append(record.target_ref)
    if record.resource_ref:
        parts.append(record.resource_ref)
    if record.domain:
        parts.append(record.domain)
    if record.relation:
        parts.append(record.relation)
    return " ".join(parts)


def search_records(records: list[PersonalRecord], query: str, limit: int) -> list[SearchHit]:
    query_tokens = _tokens(query)
    query_vector = _hashed_vector(query_tokens)
    hits: list[SearchHit] = []
    for record in records:
        text_tokens = _tokens(record_text(record))
        lexical = _jaccard(query_tokens, text_tokens)
        semantic = _cosine(query_vector, _hashed_vector(text_tokens))
        score = 0.55 * lexical + 0.45 * semantic
        if score > 0:
            hits.append(
                SearchHit(record=record, lexical_score=lexical, semantic_score=semantic, score=score)
            )
    hits.sort(key=lambda item: (item.score, item.record.temporal.recorded_at), reverse=True)
    return hits[:limit]


def _tokens(text: str) -> list[str]:
    return [token.casefold() for token in _TOKEN.findall(text)]


def _jaccard(left: list[str], right: list[str]) -> float:
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _hashed_vector(tokens: list[str]) -> list[float]:
    counts = Counter(tokens)
    vector = [0.0] * _VECTOR_SIZE
    for token, count in counts.items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        raw = int.from_bytes(digest, "big")
        index = raw % _VECTOR_SIZE
        sign = -1.0 if (raw >> 8) & 1 else 1.0
        vector[index] += sign * float(count)
    return vector


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        return 0.0
    return max(0.0, dot / (na * nb))


def _stringify(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {_stringify(item)}" for key, item in sorted(value.items()))
    if isinstance(value, (list, tuple, set)):
        return " ".join(_stringify(item) for item in value)
    return str(value)
