from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from ..domain import UtcModel, utcnow


class InterpretationStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INVALID = "invalid"


def _require_text(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def _locator_digest(locator: dict[str, Any]) -> str:
    encoded = json.dumps(locator, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class EvidenceSpan(UtcModel):
    evidence_span_id: UUID = Field(default_factory=uuid4)
    artifact_ref: UUID
    representation_ref: UUID | None = None
    representation_digest: str = Field(min_length=1, max_length=128)
    locator_kind: str = Field(min_length=1, max_length=128)
    locator: dict[str, Any] = Field(min_length=1)
    extractor_ref: str = Field(min_length=1, max_length=512)
    locator_digest: str | None = Field(default=None, min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_locator_digest(self) -> EvidenceSpan:
        expected = _locator_digest(self.locator)
        if self.locator_digest is None:
            self.locator_digest = expected
        elif self.locator_digest != expected:
            raise ValueError("locator_digest does not match canonical locator")
        _require_text(self.representation_digest, "representation_digest")
        _require_text(self.locator_kind, "locator_kind")
        _require_text(self.extractor_ref, "extractor_ref")
        return self


class InterpretationRecord(UtcModel):
    interpretation_id: UUID = Field(default_factory=uuid4)
    artifact_refs: tuple[UUID, ...] = Field(min_length=1)
    interpretation_profile_ref: str = Field(min_length=1, max_length=512)
    model_provider: str = Field(min_length=1, max_length=128)
    model_identity: str = Field(min_length=1, max_length=512)
    model_version: str = Field(min_length=1, max_length=256)
    schema_ref: str = Field(min_length=1, max_length=512)
    interpreted_at: datetime = Field(default_factory=utcnow)
    structured_output: dict[str, Any] = Field(default_factory=dict)
    evidence_span_refs: tuple[UUID, ...] = ()
    response_digest: str = Field(min_length=1, max_length=128)
    status: InterpretationStatus = InterpretationStatus.SUCCEEDED

    @model_validator(mode="after")
    def validate_provenance(self) -> InterpretationRecord:
        for name in (
            "interpretation_profile_ref", "model_provider", "model_identity",
            "model_version", "schema_ref", "response_digest",
        ):
            _require_text(getattr(self, name), name)
        return self


__all__ = ["EvidenceSpan", "InterpretationRecord", "InterpretationStatus"]
