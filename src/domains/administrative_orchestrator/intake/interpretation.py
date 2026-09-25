from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .models import (
    EvidenceSpan,
    InterpretationRecord,
    InterpretationStatus,
    SourceArtifact,
)
from .repository import IntakeRepository


class ModelGatewayError(RuntimeError):
    """Base error raised when the model gateway cannot produce a response."""


class ModelTimeoutError(ModelGatewayError):
    """The model gateway exceeded the configured timeout."""


class ModelProviderUnavailable(ModelGatewayError):
    """The model provider is unavailable or rejected the request."""


class InterpretationValidationError(ValueError):
    """The model response cannot be admitted as a candidate interpretation."""


class InterpretationProfile(BaseModel):
    """Versioned instructions and output schema for one interpretation lane."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_ref: str = Field(min_length=1, max_length=512)
    schema_ref: str = Field(min_length=1, max_length=512)
    instruction: str = Field(min_length=1, max_length=4000)


class CandidateFactDraft(BaseModel):
    """The only fact shape a model may propose to the Intake plane."""

    model_config = ConfigDict(extra="forbid")

    fact_key: str = Field(min_length=1, max_length=512)
    value: Any
    evidence_span_refs: tuple[UUID, ...] = ()


class MeetingCommitmentClassification(StrEnum):
    """Closed semantic classes emitted by the M9 meeting profile."""

    EXPLICIT_SELF_COMMITMENT = "explicit_self_commitment"
    AMBIGUOUS_COMMITMENT = "ambiguous_commitment"
    ASPIRATION = "aspiration"
    SUGGESTION = "suggestion"
    INFORMATION = "information"
    ASSIGNMENT_TO_OTHER = "assignment_to_other"


class MeetingCommitmentDraft(BaseModel):
    """Candidate-only commitment semantics extracted from untrusted text."""

    model_config = ConfigDict(extra="forbid")

    speaker_label: str = Field(min_length=1, max_length=512)
    candidate_action: str = Field(min_length=1, max_length=2000)
    candidate_due_text: str | None = Field(default=None, max_length=512)
    candidate_due_at: datetime | None = None
    candidate_scope_ref: str | None = Field(default=None, max_length=1000)
    candidate_beneficiary: str | None = Field(default=None, max_length=1000)
    classification: MeetingCommitmentClassification
    evidence_span_refs: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def validate_due_time(self) -> MeetingCommitmentDraft:
        if self.candidate_due_at is not None and self.candidate_due_at.tzinfo is None:
            raise ValueError("candidate_due_at must be offset-aware")
        return self


class MeetingInterpretationPayload(BaseModel):
    """Versioned closed output for ``meeting.commitment.v1``."""

    model_config = ConfigDict(extra="forbid")

    candidate_commitments: tuple[MeetingCommitmentDraft, ...] = ()
    evidence_span_refs: tuple[UUID, ...] = ()


class CandidateInterpretationPayload(BaseModel):
    """Closed candidate-only model output schema.

    Unknown fields are rejected rather than ignored. In particular, model
    output cannot smuggle authority, decisions, grants, tools, or delivery
    commands through an untyped JSON envelope.
    """

    model_config = ConfigDict(extra="forbid")

    candidate_intent: str = Field(min_length=1, max_length=2000)
    candidate_facts: tuple[CandidateFactDraft, ...] = ()
    draft_response: str | None = Field(default=None, max_length=10000)
    evidence_span_refs: tuple[UUID, ...] = ()


class ModelProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1, max_length=128)
    model_identity: str = Field(min_length=1, max_length=512)
    model_version: str = Field(min_length=1, max_length=256)


@dataclass(frozen=True, slots=True)
class ModelRequest:
    artifact_ref: UUID
    profile: InterpretationProfile
    source_text: str


@dataclass(frozen=True, slots=True)
class ModelResponse:
    raw_output: str
    provenance: ModelProvenance


@runtime_checkable
class ModelGateway(Protocol):
    @property
    def provenance(self) -> ModelProvenance:
        """Return provider/model metadata even when a request fails."""

    def complete(self, request: ModelRequest, *, timeout_seconds: float) -> ModelResponse:
        """Return one raw structured response without assigning authority."""


ModelOutput = str | ModelResponse
ModelOutputFactory = Callable[[ModelRequest], ModelOutput]


class StaticModelGateway:
    """Deterministic adapter for tests and local contract exercises."""

    def __init__(
        self,
        output: ModelOutput | ModelOutputFactory,
        *,
        provenance: ModelProvenance,
    ) -> None:
        self._output = output
        self._provenance = provenance

    @property
    def provenance(self) -> ModelProvenance:
        return self._provenance

    def complete(self, request: ModelRequest, *, timeout_seconds: float) -> ModelResponse:
        del timeout_seconds
        output = self._output(request) if callable(self._output) else self._output
        if isinstance(output, ModelResponse):
            return output
        return ModelResponse(raw_output=output, provenance=self._provenance)


class InterpretationClient:
    """Turn one model response into an append-only, candidate-only record."""

    def __init__(
        self,
        gateway: ModelGateway,
        repository: IntakeRepository | None = None,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.gateway = gateway
        self.repository = repository
        self.timeout_seconds = timeout_seconds

    def interpret(
        self,
        artifact: SourceArtifact,
        source_text: str,
        profile: InterpretationProfile,
        evidence_spans: Sequence[EvidenceSpan] = (),
        *,
        source_artifacts: Sequence[SourceArtifact] = (),
        interpretation_id: UUID | None = None,
    ) -> InterpretationRecord:
        artifact_refs = _unique_artifact_refs(artifact, source_artifacts)
        request = ModelRequest(
            artifact_ref=artifact.artifact_id,
            profile=profile,
            source_text=source_text,
        )
        try:
            response = self.gateway.complete(request, timeout_seconds=self.timeout_seconds)
        except ModelTimeoutError:
            return self._persist_failure(
                artifact_refs, profile, "model_timeout", interpretation_id=interpretation_id
            )
        except ModelProviderUnavailable:
            return self._persist_failure(
                artifact_refs, profile, "provider_unavailable", interpretation_id=interpretation_id
            )
        except ModelGatewayError:
            return self._persist_failure(
                artifact_refs, profile, "provider_error", interpretation_id=interpretation_id
            )

        try:
            payload = self._parse_payload(response.raw_output, profile)
            payload = self._bind_single_document_span_when_unambiguous(
                payload,
                primary_artifact_ref=artifact.artifact_id,
                evidence_spans=evidence_spans,
            )
            bound_evidence = self._bind_evidence(payload, artifact_refs, evidence_spans)
        except (InterpretationValidationError, TypeError, ValueError):
            return self._persist_invalid(
                artifact_refs, profile, response, interpretation_id=interpretation_id
            )

        record = InterpretationRecord(
            interpretation_id=interpretation_id or uuid4(),
            artifact_refs=artifact_refs,
            interpretation_profile_ref=profile.profile_ref,
            model_provider=response.provenance.provider,
            model_identity=response.provenance.model_identity,
            model_version=response.provenance.model_version,
            schema_ref=profile.schema_ref,
            structured_output=payload.model_dump(mode="json"),
            evidence_span_refs=bound_evidence,
            response_digest=_sha256_text(response.raw_output),
            status=InterpretationStatus.SUCCEEDED,
        )
        return self._append(record)

    @staticmethod
    def _bind_single_document_span_when_unambiguous(
        payload: CandidateInterpretationPayload | MeetingInterpretationPayload,
        *,
        primary_artifact_ref: UUID,
        evidence_spans: Sequence[EvidenceSpan],
    ) -> CandidateInterpretationPayload | MeetingInterpretationPayload:
        """Bind claims to one unambiguous document page without inventing facts."""

        document_spans = tuple(
            span for span in evidence_spans if span.artifact_ref != primary_artifact_ref
        )
        if len(document_spans) != 1:
            return payload
        fallback_ref = document_spans[0].evidence_span_id
        if isinstance(payload, MeetingInterpretationPayload):
            commitments = tuple(
                commitment
                if commitment.evidence_span_refs
                else commitment.model_copy(update={"evidence_span_refs": (fallback_ref,)})
                for commitment in payload.candidate_commitments
            )
            return payload.model_copy(
                update={
                    "candidate_commitments": commitments,
                    "evidence_span_refs": tuple(
                        dict.fromkeys((*payload.evidence_span_refs, fallback_ref))
                    ),
                }
            )
        facts = tuple(
            fact
            if fact.evidence_span_refs
            else fact.model_copy(update={"evidence_span_refs": (fallback_ref,)})
            for fact in payload.candidate_facts
        )
        evidence_refs = tuple(
            dict.fromkeys((*payload.evidence_span_refs, fallback_ref))
        )
        return payload.model_copy(
            update={"candidate_facts": facts, "evidence_span_refs": evidence_refs}
        )

    @staticmethod
    def _parse_payload(
        raw_output: str,
        profile: InterpretationProfile,
    ) -> CandidateInterpretationPayload | MeetingInterpretationPayload:
        try:
            decoded = json.loads(raw_output)
        except (TypeError, ValueError) as exc:
            raise InterpretationValidationError("model response is not valid JSON") from exc
        payload_type = (
            MeetingInterpretationPayload
            if profile.profile_ref == "meeting.commitment.v1"
            else CandidateInterpretationPayload
        )
        try:
            return payload_type.model_validate(decoded)
        except ValidationError as exc:
            raise InterpretationValidationError("model response violates candidate schema") from exc

    @staticmethod
    def _bind_evidence(
        payload: CandidateInterpretationPayload | MeetingInterpretationPayload,
        artifact_refs: Sequence[UUID],
        evidence_spans: Sequence[EvidenceSpan],
    ) -> tuple[UUID, ...]:
        trusted_artifacts = set(artifact_refs)
        spans_by_id: dict[UUID, EvidenceSpan] = {}
        for span in evidence_spans:
            if span.artifact_ref not in trusted_artifacts:
                raise InterpretationValidationError("EvidenceSpan belongs to another artifact")
            if span.evidence_span_id in spans_by_id:
                raise InterpretationValidationError("duplicate EvidenceSpan identity")
            spans_by_id[span.evidence_span_id] = span

        requested = set(payload.evidence_span_refs)
        if isinstance(payload, MeetingInterpretationPayload):
            for commitment in payload.candidate_commitments:
                requested.update(commitment.evidence_span_refs)
        else:
            for fact in payload.candidate_facts:
                requested.update(fact.evidence_span_refs)

        for evidence_ref in requested:
            if evidence_ref not in spans_by_id:
                raise InterpretationValidationError("model referenced an unbound EvidenceSpan")

        return tuple(sorted(requested, key=str))

    def _persist_invalid(
        self,
        artifact_refs: tuple[UUID, ...],
        profile: InterpretationProfile,
        response: ModelResponse,
        *,
        interpretation_id: UUID | None = None,
    ) -> InterpretationRecord:
        record = InterpretationRecord(
            interpretation_id=interpretation_id or uuid4(),
            artifact_refs=artifact_refs,
            interpretation_profile_ref=profile.profile_ref,
            model_provider=response.provenance.provider,
            model_identity=response.provenance.model_identity,
            model_version=response.provenance.model_version,
            schema_ref=profile.schema_ref,
            structured_output={},
            evidence_span_refs=(),
            response_digest=_sha256_text(response.raw_output),
            status=InterpretationStatus.INVALID,
        )
        return self._append(record)

    def _persist_failure(
        self,
        artifact_refs: tuple[UUID, ...],
        profile: InterpretationProfile,
        failure_code: str,
        *,
        interpretation_id: UUID | None = None,
    ) -> InterpretationRecord:
        provenance = self.gateway.provenance
        record = InterpretationRecord(
            interpretation_id=interpretation_id or uuid4(),
            artifact_refs=artifact_refs,
            interpretation_profile_ref=profile.profile_ref,
            model_provider=provenance.provider,
            model_identity=provenance.model_identity,
            model_version=provenance.model_version,
            schema_ref=profile.schema_ref,
            structured_output={},
            evidence_span_refs=(),
            response_digest=_sha256_text(failure_code),
            status=InterpretationStatus.FAILED,
        )
        return self._append(record)

    def _append(self, record: InterpretationRecord) -> InterpretationRecord:
        if self.repository is not None:
            return self.repository.append_interpretation(record)
        return record


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _unique_artifact_refs(
    primary: SourceArtifact,
    additional: Sequence[SourceArtifact],
) -> tuple[UUID, ...]:
    refs: list[UUID] = []
    for item in (primary, *additional):
        if item.artifact_id not in refs:
            refs.append(item.artifact_id)
    return tuple(refs)


__all__ = [
    "CandidateFactDraft",
    "CandidateInterpretationPayload",
    "MeetingCommitmentClassification",
    "MeetingCommitmentDraft",
    "MeetingInterpretationPayload",
    "InterpretationClient",
    "InterpretationProfile",
    "InterpretationValidationError",
    "ModelGateway",
    "ModelGatewayError",
    "ModelOutput",
    "ModelProvenance",
    "ModelProviderUnavailable",
    "ModelRequest",
    "ModelResponse",
    "ModelTimeoutError",
    "StaticModelGateway",
]
