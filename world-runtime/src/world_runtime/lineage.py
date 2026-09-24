from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from semantic_language import Revision, SemanticRef, semantic_digest

from .ledger import LedgerConcurrencyConflict, SemanticLedger


def _ref_payload(ref: SemanticRef) -> dict[str, str]:
    return {
        "kind": ref.kind_value,
        "id": ref.id,
        "namespace": ref.namespace,
        "version": ref.version,
    }


def _ref_from_payload(value: Mapping[str, Any]) -> SemanticRef:
    return SemanticRef(
        kind=str(value["kind"]),
        id=str(value["id"]),
        namespace=str(value.get("namespace", "universal")),
        version=str(value.get("version", "0.1")),
    )


def _ref_key(ref: SemanticRef) -> str:
    return semantic_digest(_ref_payload(ref))


class RevisionLineageService:
    """Append-only successor lineage for semantic and Runtime-namespaced objects.

    The service does not own object semantics. It only records that one immutable
    object explicitly supersedes another under a semantic-language Revision.
    """

    def __init__(self, ledger: SemanticLedger) -> None:
        self.ledger = ledger

    def record(self, revision: Revision) -> None:
        target = revision.target_ref
        previous = revision.supersedes_ref
        if target is None or previous is None:
            raise ValueError("lineage Revision requires target_ref and supersedes_ref")
        if target == previous:
            raise ValueError("lineage Revision target must differ from superseded ref")
        if (
            target.kind_value != previous.kind_value
            or target.namespace != previous.namespace
        ):
            raise ValueError("lineage Revision must preserve kind and namespace")
        if not revision.reason.strip():
            raise ValueError("lineage Revision requires explicit reason")
        if not revision.basis_refs:
            raise ValueError("lineage Revision requires explicit basis refs")

        value = {
            "id": revision.id,
            "target_ref": _ref_payload(target),
            "supersedes_ref": _ref_payload(previous),
            "reason": revision.reason,
            "basis_refs": [_ref_payload(ref) for ref in revision.basis_refs],
            "created_at": revision.created_at.isoformat(),
            "metadata": dict(revision.metadata),
        }
        existing_revision = self.ledger.project_get(
            "institutional.revision",
            revision.id,
        )
        if existing_revision is not None:
            if existing_revision[0] != value:
                raise ValueError("Revision identity rebound")
            return

        previous_key = _ref_key(previous)
        target_key = _ref_key(target)
        previous_root = self.ledger.project_get(
            "institutional.lineage-root",
            previous_key,
        )
        root = (
            _ref_from_payload(previous_root[0]["root_ref"])
            if previous_root is not None
            else previous
        )
        root_key = _ref_key(root)

        target_root = self.ledger.project_get(
            "institutional.lineage-root",
            target_key,
        )
        if target_root is not None:
            existing_root = _ref_from_payload(target_root[0]["root_ref"])
            if existing_root != root:
                raise ValueError("lineage target already belongs to another root")
            raise ValueError("lineage target is already recorded")

        head_row = self.ledger.project_get(
            "institutional.lineage-head",
            root_key,
        )
        if head_row is None:
            current_head = previous
            head_version = None
        else:
            current_head = _ref_from_payload(head_row[0]["head_ref"])
            head_version = head_row[1]
        if current_head != previous:
            raise ValueError(
                "Revision must supersede the current lineage head; branching is rejected"
            )

        root_value = {"root_ref": _ref_payload(root)}
        head_value = {"root_ref": _ref_payload(root), "head_ref": _ref_payload(target)}

        try:
            with self.ledger.transaction():
                self.ledger.project_put(
                    "institutional.revision",
                    revision.id,
                    value,
                    expected_version=0,
                )
                if previous_root is None:
                    self.ledger.project_put(
                        "institutional.lineage-root",
                        previous_key,
                        root_value,
                        expected_version=0,
                    )
                self.ledger.project_put(
                    "institutional.lineage-root",
                    target_key,
                    root_value,
                    expected_version=0,
                )
                if head_version is None:
                    self.ledger.project_put(
                        "institutional.lineage-head",
                        root_key,
                        head_value,
                        expected_version=0,
                    )
                else:
                    self.ledger.project_put(
                        "institutional.lineage-head",
                        root_key,
                        head_value,
                        expected_version=head_version,
                    )
                self.ledger.append(
                    stream=f"institutional-lineage:{root_key}",
                    kind="institutional.revision.recorded",
                    payload=value,
                )
        except LedgerConcurrencyConflict as exc:
            replay = self.ledger.project_get("institutional.revision", revision.id)
            if replay is not None and replay[0] == value:
                return
            raise ValueError("lineage head changed concurrently") from exc

    def resolve_current(self, ref: SemanticRef) -> SemanticRef:
        member = self.ledger.project_get(
            "institutional.lineage-root",
            _ref_key(ref),
        )
        if member is None:
            return ref
        root = _ref_from_payload(member[0]["root_ref"])
        head = self.ledger.project_get(
            "institutional.lineage-head",
            _ref_key(root),
        )
        if head is None:
            return ref
        return _ref_from_payload(head[0]["head_ref"])

    def root(self, ref: SemanticRef) -> SemanticRef:
        member = self.ledger.project_get(
            "institutional.lineage-root",
            _ref_key(ref),
        )
        if member is None:
            return ref
        return _ref_from_payload(member[0]["root_ref"])

    def is_current(self, ref: SemanticRef) -> bool:
        return self.resolve_current(ref) == ref

    def assert_current(self, ref: SemanticRef) -> None:
        current = self.resolve_current(ref)
        if current != ref:
            raise ValueError(
                f"semantic object is superseded; current ref is {current.id}"
            )

    def history(self, ref: SemanticRef) -> tuple[Revision, ...]:
        root = self.root(ref)
        events = self.ledger.events(
            stream=f"institutional-lineage:{_ref_key(root)}",
            kind="institutional.revision.recorded",
        )
        revisions: list[Revision] = []
        for event in events:
            payload = event.payload
            revisions.append(
                Revision(
                    id=str(payload["id"]),
                    target_ref=_ref_from_payload(payload["target_ref"]),
                    supersedes_ref=_ref_from_payload(payload["supersedes_ref"]),
                    reason=str(payload["reason"]),
                    basis_refs=tuple(
                        _ref_from_payload(item)
                        for item in payload.get("basis_refs", [])
                    ),
                    created_at=datetime.fromisoformat(str(payload["created_at"])),
                    metadata=dict(payload.get("metadata", {})),
                )
            )
        return tuple(revisions)


__all__ = ["RevisionLineageService"]
