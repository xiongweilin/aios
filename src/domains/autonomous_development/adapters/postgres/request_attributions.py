from __future__ import annotations

from sqlalchemy import Engine, insert, select

from autonomous_development.domain.models import RequestAttribution
from autonomous_development.ports.persistence import RequestAttributionRepository

from .records import insert_once, load_one, record_values
from .schema import request_attributions


class SqlRequestAttributionRepository(RequestAttributionRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, attribution: RequestAttribution) -> RequestAttribution:
        return insert_once(
            self._engine,
            insert(request_attributions).values(
                **record_values(request_attributions, attribution)
            ),
            load=lambda: self.get(attribution.request_ref),
            expected=attribution,
            conflict=lambda: ValueError(
                "request reference already exists with different attribution: "
                f"{attribution.request_ref}"
            ),
        )

    def get(self, request_ref: str) -> RequestAttribution | None:
        return load_one(
            self._engine,
            select(request_attributions).where(
                request_attributions.c.request_ref == request_ref
            ),
            RequestAttribution,
        )
