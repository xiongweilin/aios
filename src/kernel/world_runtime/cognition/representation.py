from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from uuid import uuid4


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class RepresentationMutationKind(StrEnum):
    ADD_FACTOR = "add-factor"
    REMOVE_FACTOR = "remove-factor"
    SPLIT_FACTOR = "split-factor"
    MERGE_FACTOR = "merge-factor"
    CHANGE_BOUNDARY = "change-boundary"
    CHANGE_SCALE = "change-scale"
    ADD_RELATION = "add-relation"
    REMOVE_RELATION = "remove-relation"
    CHANGE_EQUIVALENCE = "change-equivalence"
    ADD_OBSERVATION_CHANNEL = "add-observation-channel"
    REFRAME_PROBLEM = "reframe-problem"


@dataclass(frozen=True, slots=True)
class RepresentationState:
    scope: str
    factors: tuple[str, ...] = ()
    relations: tuple[str, ...] = ()
    boundaries: tuple[str, ...] = ()
    scales: tuple[str, ...] = ()
    equivalences: tuple[str, ...] = ()
    observation_channels: tuple[str, ...] = ()
    problem_frame: str = ""
    version: int = 1
    basis_refs: tuple[str, ...] = ()
    id: str = field(default_factory=lambda: _new_id("representation"))

    def __post_init__(self) -> None:
        if not self.scope.strip() or self.version < 1:
            raise ValueError("representation requires bounded scope and positive version")


@dataclass(frozen=True, slots=True)
class RepresentationRevisionCandidate:
    representation_ref: str
    mutation: RepresentationMutationKind
    parameters: tuple[tuple[str, str], ...]
    reason: str
    basis_refs: tuple[str, ...]
    expected_discriminating_change: str
    id: str = field(default_factory=lambda: _new_id("representation_revision"))

    def __post_init__(self) -> None:
        if not self.reason.strip() or not self.basis_refs:
            raise ValueError("representation revision requires reason and basis_refs")
        if not self.expected_discriminating_change.strip():
            raise ValueError("representation revision must state its discriminating consequence")

    @property
    def parameter_map(self) -> dict[str, str]:
        return dict(self.parameters)


@dataclass(frozen=True, slots=True)
class RepresentationRevisionResult:
    prior_ref: str
    candidate_ref: str
    applied: bool
    reason: str
    representation: RepresentationState | None = None


class RepresentationReviser:
    """Apply an explicitly adopted representation candidate; adoption is external policy."""

    def apply(
        self,
        state: RepresentationState,
        candidate: RepresentationRevisionCandidate,
    ) -> RepresentationRevisionResult:
        if candidate.representation_ref != state.id:
            return RepresentationRevisionResult(
                state.id,
                candidate.id,
                False,
                "revision candidate targets another representation",
            )
        params = candidate.parameter_map
        try:
            updated = self._apply_mutation(state, candidate.mutation, params)
        except ValueError as exc:
            return RepresentationRevisionResult(state.id, candidate.id, False, str(exc))
        updated = replace(
            updated,
            id=_new_id("representation"),
            version=state.version + 1,
            basis_refs=tuple(
                dict.fromkeys((*state.basis_refs, *candidate.basis_refs, candidate.id))
            ),
        )
        return RepresentationRevisionResult(
            prior_ref=state.id,
            candidate_ref=candidate.id,
            applied=True,
            reason="explicitly adopted representation revision applied",
            representation=updated,
        )

    def _apply_mutation(
        self,
        state: RepresentationState,
        mutation: RepresentationMutationKind,
        params: dict[str, str],
    ) -> RepresentationState:
        if mutation is RepresentationMutationKind.ADD_FACTOR:
            return replace(
                state,
                factors=self._add(state.factors, self._required(params, "factor")),
            )
        if mutation is RepresentationMutationKind.REMOVE_FACTOR:
            return replace(
                state,
                factors=self._remove(state.factors, self._required(params, "factor")),
            )
        if mutation is RepresentationMutationKind.SPLIT_FACTOR:
            source = self._required(params, "source")
            left = self._required(params, "left")
            right = self._required(params, "right")
            factors = self._remove(state.factors, source)
            return replace(state, factors=self._add(self._add(factors, left), right))
        if mutation is RepresentationMutationKind.MERGE_FACTOR:
            left = self._required(params, "left")
            right = self._required(params, "right")
            target = self._required(params, "target")
            factors = self._remove(self._remove(state.factors, left), right)
            return replace(state, factors=self._add(factors, target))
        if mutation is RepresentationMutationKind.CHANGE_BOUNDARY:
            return replace(state, boundaries=(self._required(params, "boundary"),))
        if mutation is RepresentationMutationKind.CHANGE_SCALE:
            return replace(state, scales=(self._required(params, "scale"),))
        if mutation is RepresentationMutationKind.ADD_RELATION:
            return replace(
                state,
                relations=self._add(state.relations, self._required(params, "relation")),
            )
        if mutation is RepresentationMutationKind.REMOVE_RELATION:
            return replace(
                state,
                relations=self._remove(state.relations, self._required(params, "relation")),
            )
        if mutation is RepresentationMutationKind.CHANGE_EQUIVALENCE:
            return replace(state, equivalences=(self._required(params, "equivalence"),))
        if mutation is RepresentationMutationKind.ADD_OBSERVATION_CHANNEL:
            return replace(
                state,
                observation_channels=self._add(
                    state.observation_channels,
                    self._required(params, "channel"),
                ),
            )
        if mutation is RepresentationMutationKind.REFRAME_PROBLEM:
            return replace(state, problem_frame=self._required(params, "problem_frame"))
        raise ValueError(f"unsupported representation mutation: {mutation.value}")

    def _required(self, params: dict[str, str], key: str) -> str:
        value = params.get(key, "").strip()
        if not value:
            raise ValueError(f"representation revision requires parameter {key}")
        return value

    def _add(self, values: tuple[str, ...], value: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*values, value)))

    def _remove(self, values: tuple[str, ...], value: str) -> tuple[str, ...]:
        if value not in values:
            raise ValueError(f"representation does not contain {value}")
        return tuple(item for item in values if item != value)
