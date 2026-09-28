from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from typing import Any, TypeVar

from pydantic import TypeAdapter
from sqlalchemy.engine import RowMapping

T = TypeVar("T")


def record_from_row(
    model: type[T],
    row: RowMapping,
    /,
    *,
    rename: Mapping[str, str] | None = None,
    **overrides: Any,
) -> T:
    values = {
        name: value.replace(tzinfo=UTC) if isinstance(value, datetime) and value.tzinfo is None else value
        for name, value in dict(row).items()
    }
    for source, target in (rename or {}).items():
        if source in values:
            values[target] = values.pop(source)
    values.update(overrides)
    if is_dataclass(model):
        allowed = {field.name for field in fields(model)}
        values = {name: value for name, value in values.items() if name in allowed}
    return TypeAdapter(model).validate_python(values)


def record_values(
    record: object,
    /,
    *,
    rename: Mapping[str, str] | None = None,
    json_fields: set[str] | frozenset[str] = frozenset(),
    exclude: set[str] | frozenset[str] = frozenset(),
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    adapter = TypeAdapter(type(record))
    values = adapter.dump_python(record, mode="python", exclude=exclude)
    if not isinstance(values, dict):
        raise TypeError("persisted record must serialize to an object")
    if json_fields:
        encoded = adapter.dump_python(record, mode="json", include=json_fields)
        for name in json_fields:
            if name in values:
                values[name] = encoded[name]
    for source, target in (rename or {}).items():
        values[target] = values.pop(source)
    values.update(extra or {})
    return values
