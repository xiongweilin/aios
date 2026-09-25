from __future__ import annotations

from typing import Any
from uuid import UUID

from .contracts import CandidateProjection, DraftResponse
from .models import (
    CandidateAdministrativeRequest,
    CandidateAuthority,
    CandidateFactAssertion,
    InterpretationRecord,
)


class CandidateProjectionError(ValueError):
    """The untrusted interpretation cannot be projected safely."""


class CandidateProjectionService:
    """Project untrusted interpretation data into candidate-only objects.

    This service has no persistence, authority, provider, Kernel, or dispatch
    dependency. It intentionally ignores authority-like fields in model
    output and assigns the only candidate authority allowed by the type.
    """

    def project(
        self,
        interpretation: InterpretationRecord,
        *,
        conversation_ref: str,
        candidate_requester: str,
        source_refs: tuple[UUID, ...],
    ) -> CandidateProjection:
        if not source_refs:
            raise CandidateProjectionError("candidate projection requires source_refs")

        output = interpretation.structured_output
        candidate_intent = output.get("candidate_intent", "unclassified")
        if not isinstance(candidate_intent, str) or not candidate_intent.strip():
            raise CandidateProjectionError("candidate_intent must be a non-blank string")

        raw_facts = output.get("candidate_facts", [])
        if not isinstance(raw_facts, list):
            raise CandidateProjectionError("candidate_facts must be a list when present")

        facts: list[CandidateFactAssertion] = []
        for raw_fact in raw_facts:
            if not isinstance(raw_fact, dict):
                raise CandidateProjectionError("each candidate fact must be an object")
            fact_key = raw_fact.get("fact_key")
            if not isinstance(fact_key, str) or not fact_key.strip():
                raise CandidateProjectionError("each candidate fact requires fact_key")
            evidence_refs = self._verified_evidence_refs(
                raw_fact.get("evidence_span_refs"), interpretation
            )
            facts.append(
                CandidateFactAssertion(
                    fact_key=fact_key,
                    value=raw_fact.get("value"),
                    # Never copy an authority-like model field. Candidate
                    # projection always starts at the least privileged value.
                    authority=CandidateAuthority.CLAIM,
                    interpretation_ref=interpretation.interpretation_id,
                    source_refs=source_refs,
                    evidence_span_refs=evidence_refs,
                    no_evidence_reason=(
                        None
                        if evidence_refs
                        else "No verified EvidenceSpan reference was supplied by the interpretation."
                    ),
                    extractor_ref="interpretation-projection-v1",
                )
            )

        candidate = CandidateAdministrativeRequest(
            conversation_ref=conversation_ref,
            interpretation_refs=(interpretation.interpretation_id,),
            candidate_requester=candidate_requester,
            candidate_intent=candidate_intent,
            candidate_fact_refs=tuple(fact.candidate_fact_id for fact in facts),
            source_refs=source_refs,
        )
        draft_response = self._draft_response(output, candidate, source_refs)
        return CandidateProjection(
            candidate=candidate,
            facts=tuple(facts),
            draft_response=draft_response,
        )

    @staticmethod
    def _verified_evidence_refs(
        raw_refs: Any, interpretation: InterpretationRecord
    ) -> tuple[UUID, ...]:
        if raw_refs is None:
            return ()
        if not isinstance(raw_refs, list):
            raise CandidateProjectionError("evidence_span_refs must be a list when present")
        trusted = set(interpretation.evidence_span_refs)
        verified: list[UUID] = []
        for raw_ref in raw_refs:
            try:
                ref = UUID(str(raw_ref))
            except (TypeError, ValueError) as exc:
                raise CandidateProjectionError("evidence_span_refs must contain UUIDs") from exc
            if ref in trusted and ref not in verified:
                verified.append(ref)
        return tuple(verified)

    @staticmethod
    def _draft_response(
        output: dict[str, Any],
        candidate: CandidateAdministrativeRequest,
        source_refs: tuple[UUID, ...],
    ) -> DraftResponse | None:
        raw_draft = output.get("draft_response")
        if raw_draft is None:
            return None
        if not isinstance(raw_draft, str) or not raw_draft.strip():
            raise CandidateProjectionError("draft_response must be a non-blank string")
        return DraftResponse(
            candidate_ref=candidate.candidate_id,
            body=raw_draft,
            source_refs=source_refs,
        )


__all__ = ["CandidateProjectionError", "CandidateProjectionService"]
