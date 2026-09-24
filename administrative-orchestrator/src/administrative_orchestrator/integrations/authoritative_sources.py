from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from ..domain import FactAssertion, FactAuthority, FactSnapshot, normalize_datetime, utcnow


class SourceFreshness(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    UNKNOWN = "unknown"


class AuthoritativeRecord(BaseModel):
    source: str
    source_ref: str
    source_version: str
    observed_at: datetime = Field(default_factory=utcnow)
    freshness: SourceFreshness = SourceFreshness.CURRENT
    value: dict[str, Any]
    digest: str

    @classmethod
    def build(
        cls,
        *,
        source: str,
        source_ref: str,
        source_version: str,
        value: dict[str, Any],
        observed_at: datetime | None = None,
        freshness: SourceFreshness = SourceFreshness.CURRENT,
    ) -> AuthoritativeRecord:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        return cls(
            source=source,
            source_ref=source_ref,
            source_version=source_version,
            observed_at=normalize_datetime(observed_at or utcnow()),
            freshness=freshness,
            value=value,
            digest=hashlib.sha256(canonical.encode()).hexdigest(),
        )

    def is_fresh_at(self, at: datetime, *, max_age_seconds: int) -> bool:
        at = normalize_datetime(at)
        return (
            self.freshness is SourceFreshness.CURRENT
            and self.observed_at <= at
            and at - self.observed_at <= timedelta(seconds=max_age_seconds)
        )

    def as_fact_snapshot(self, *, owner: str) -> FactSnapshot:
        if self.freshness is not SourceFreshness.CURRENT:
            raise ValueError("only current authoritative records may mint FactSnapshot(AUTHORITATIVE)")
        assertions = {
            key: FactAssertion(
                value=value,
                authority=FactAuthority.AUTHORITATIVE,
                source=self.source,
                owner=owner,
                source_ref=self.source_ref,
                source_version=self.source_version,
                observed_at=self.observed_at,
                digest=self.digest,
            )
            for key, value in self.value.items()
        }
        return FactSnapshot(
            source=self.source,
            owner=owner,
            authority=FactAuthority.AUTHORITATIVE,
            source_ref=self.source_ref,
            source_version=self.source_version,
            observed_at=self.observed_at,
            facts=dict(self.value),
            assertions=assertions,
            digest=self.digest,
        )


class HRFactSource(Protocol):
    def read_employee(self, employee_ref: str) -> AuthoritativeRecord: ...

    def read_department(self, department_ref: str) -> AuthoritativeRecord: ...

    def read_manager(self, employee_ref: str) -> AuthoritativeRecord: ...


class OrganizationDirectory(Protocol):
    def resolve_person(self, external_identity: str) -> AuthoritativeRecord: ...


class IdentityDirectory(Protocol):
    def read_identity(self, identity_ref: str) -> AuthoritativeRecord: ...


__all__ = [
    "AuthoritativeRecord",
    "HRFactSource",
    "IdentityDirectory",
    "OrganizationDirectory",
    "SourceFreshness",
]
