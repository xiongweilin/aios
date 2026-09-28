from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


def model_from_row(
    model: type[ModelT],
    row: object,
    /,
    **overrides: Any,
) -> ModelT:
    values = {
        name: getattr(row, name)
        for name in model.model_fields
        if hasattr(row, name)
    }
    values.update(overrides)
    return model.model_validate(values)


def model_values(
    model: BaseModel,
    /,
    *,
    exclude: set[str] | frozenset[str] = frozenset(),
    rename: Mapping[str, str] | None = None,
    json_fields: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    values = model.model_dump(mode="python", exclude=exclude)
    if json_fields:
        encoded = model.model_dump(mode="json", include=json_fields)
        for name in json_fields:
            if name in values:
                values[name] = encoded[name]
    for source, target in (rename or {}).items():
        values[target] = values.pop(source)
    return values
