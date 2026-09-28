from __future__ import annotations

from sqlalchemy import Engine, insert, select

from autonomous_development.domain.models import ChangeProposal
from autonomous_development.ports.persistence import ChangeProposalRepository

from .records import insert_once, load_one, record_values
from .schema import change_proposals


class SqlChangeProposalRepository(ChangeProposalRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def add(self, proposal: ChangeProposal) -> ChangeProposal:
        return insert_once(
            self._engine,
            insert(change_proposals).values(**record_values(change_proposals, proposal)),
            load=lambda: self.get(proposal.id),
            expected=proposal,
            conflict=lambda: ValueError(
                f"proposal id already exists with different content: {proposal.id}"
            ),
        )

    def get(self, id: str) -> ChangeProposal | None:
        return load_one(
            self._engine,
            select(change_proposals).where(change_proposals.c.id == id),
            ChangeProposal,
        )
