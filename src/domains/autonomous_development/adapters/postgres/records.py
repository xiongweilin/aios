from __future__ import annotations

from collections.abc import Callable
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


def record_values(table: Table, value: object, **extra: object) -> dict[str, object]:
    data = _adapter(type(value)).dump_python(value, mode="python")
    values: dict[str, object] = {}
    for column in table.columns:
        field = column.name.removesuffix("_json")
        if field not in data:
            continue
        item = data[field]
        if item is None and column.primary_key and column.autoincrement:
            continue
        values[column.name] = item
    values.update(extra)
    return values


def record_from_row(model: type[T], row: RowMapping) -> T:
    names = _fields(model)
    values: dict[str, object] = {}
    for column, item in row.items():
        field = str(column).removesuffix("_json")
        if field not in names:
            continue
        if isinstance(item, datetime) and item.tzinfo is None:
            item = item.replace(tzinfo=UTC)
        values[field] = item
    return _adapter(model).validate_python(values)


def load_one(engine: Engine, statement: Any, model: type[T]) -> T | None:
    with engine.connect() as connection:
        row = connection.execute(statement).mappings().first()
    return None if row is None else record_from_row(model, row)


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
