from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import fields
from datetime import UTC, datetime
from functools import cache
from typing import Any, TypeVar

from pydantic import TypeAdapter
from sqlalchemy import Engine, Table
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError

T = TypeVar("T")


@cache
def _adapter(model: type[Any]) -> TypeAdapter[Any]:
    return TypeAdapter(model)


@cache
def _fields(model: type[Any]) -> frozenset[str]:
    return frozenset(field.name for field in fields(model))


def record_values(table: Table, value: object, **overrides: object) -> dict[str, object]:
    adapter = _adapter(type(value))
    python_data = adapter.dump_python(value, mode="python")
    json_data: dict[str, object] | None = None
    values: dict[str, object] = {}
    columns = {column.name: column for column in table.columns}
    for name, column in columns.items():
        field = name.removesuffix("_json")
        if field not in python_data:
            continue
        item = python_data[field]
        if name.endswith("_json"):
            if json_data is None:
                json_data = adapter.dump_python(value, mode="json")
            item = json_data[field]
        if item is None and column.primary_key and column.autoincrement:
            continue
        values[name] = item
    values.update({name: item for name, item in overrides.items() if name in columns})
    return values


def record_from_row(
    model: type[T],
    row: Mapping[str, object] | RowMapping | object,
    /,
    *,
    rename: Mapping[str, str] | None = None,
    **overrides: object,
) -> T:
    names = _fields(model)
    if isinstance(row, Mapping):
        items = row.items()
    else:
        items = ((name, getattr(row, name)) for name in dir(row) if not name.startswith("_"))
    renames = rename or {}
    values: dict[str, object] = {}
    for column, item in items:
        source = str(column)
        field = renames.get(source, source.removesuffix("_json"))
        if field not in names:
            continue
        if isinstance(item, datetime) and item.tzinfo is None:
            item = item.replace(tzinfo=UTC)
        values[field] = item
    values.update(overrides)
    return _adapter(model).validate_python(values)


def load_one(
    engine: Engine,
    statement: Any,
    model: type[T],
    *,
    transform: Callable[[RowMapping], T] | None = None,
) -> T | None:
    with engine.connect() as connection:
        row = connection.execute(statement).mappings().first()
    if row is None:
        return None
    return transform(row) if transform is not None else record_from_row(model, row)


def insert_once(
    engine: Engine,
    statement: Any,
    *,
    load: Callable[[], T | None],
    expected: T,
    conflict: Callable[[], Exception],
) -> T:
    existing = load()
    if existing is not None:
        if existing != expected:
            raise conflict()
        return existing
    try:
        with engine.begin() as connection:
            connection.execute(statement)
    except IntegrityError as exc:
        existing = load()
        if existing is None:
            raise
        if existing != expected:
            raise conflict() from exc
        return existing
    return expected
