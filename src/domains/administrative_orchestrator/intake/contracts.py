from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import Field

from ..domain import UtcModel, utcnow
from .models import CandidateAdministrativeRequest, CandidateFactAssertion


class DraftResponse(UtcModel):
    """A non-delivered response draft derived from candidate context.

    Deliberately absent: recipient, delivery status, provider handle, effect
    intent, or any dispatch method. Organizational communication effects are a
    separate future authority boundary.
    """

    draft_id: UUID = Field(default_factory=uuid4)
    candidate_ref: UUID
    body: str = Field(min_length=1, max_length=10000)
    source_refs: tuple[UUID, ...] = Field(min_length=1)
    created_at: datetime = Field(default_factory=utcnow)


class CandidateProjection(UtcModel):
    """The only output currently permitted from the PR3 projection service."""

    candidate: CandidateAdministrativeRequest
    facts: tuple[CandidateFactAssertion, ...] = ()
    draft_response: DraftResponse | None = None
