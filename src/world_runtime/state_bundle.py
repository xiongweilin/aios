from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from .ledger import SemanticLedger


BUNDLE_VERSION = "world-runtime-state-v1"


@dataclass(frozen=True, slots=True)
class BundleValidation:
    valid: bool
    errors: tuple[str, ...]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest(payload: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(payload)).hexdigest()


class StateBundleService:
    """Portable full Runtime state with integrity and reference-graph validation."""

    def __init__(self, ledger: SemanticLedger) -> None:
        self.ledger = ledger

    def export(self) -> dict[str, Any]:
        payload = {
            "bundle_version": BUNDLE_VERSION,
            "events": self.ledger.export_event_rows(),
            "projections": self.ledger.export_projection_rows(),
        }
        return {
            **payload,
            "manifest": {
                "bundle_version": BUNDLE_VERSION,
                "event_count": len(payload["events"]),
                "projection_count": len(payload["projections"]),
                "digest": _digest(payload),
            },
        }

    def validate(self, bundle: Mapping[str, Any]) -> BundleValidation:
        errors: list[str] = []
        if bundle.get("bundle_version") != BUNDLE_VERSION:
            errors.append("unsupported bundle_version")

        events = bundle.get("events")
        projections = bundle.get("projections")
        manifest = bundle.get("manifest")
        if not isinstance(events, list):
            errors.append("events must be a list")
            events = []
        if not isinstance(projections, list):
            errors.append("projections must be a list")
            projections = []
        if not isinstance(manifest, Mapping):
            errors.append("manifest must be an object")
            manifest = {}

        payload = {
            "bundle_version": bundle.get("bundle_version"),
            "events": events,
            "projections": projections,
        }
        expected_digest = manifest.get("digest") if isinstance(manifest, Mapping) else None
        if expected_digest != _digest(payload):
            errors.append("bundle digest mismatch")
        if manifest.get("event_count") != len(events):
            errors.append("manifest event_count mismatch")
        if manifest.get("projection_count") != len(projections):
            errors.append("manifest projection_count mismatch")

        event_ids: set[str] = set()
        sequences: list[int] = []
        for raw in events:
            if not isinstance(raw, Mapping):
                errors.append("event row must be an object")
                continue
            event_id = str(raw.get("id", ""))
            if not event_id:
                errors.append("event id is required")
            elif event_id in event_ids:
                errors.append(f"duplicate event id: {event_id}")
            event_ids.add(event_id)
            try:
                sequences.append(int(raw["sequence"]))
            except (KeyError, TypeError, ValueError):
                errors.append(f"event sequence is invalid: {event_id or '<unknown>'}")
            if not str(raw.get("stream", "")).strip():
                errors.append(f"event stream is required: {event_id or '<unknown>'}")
            if not str(raw.get("kind", "")).strip():
                errors.append(f"event kind is required: {event_id or '<unknown>'}")
            if not isinstance(raw.get("payload"), Mapping):
                errors.append(f"event payload must be an object: {event_id or '<unknown>'}")

        if sequences and sequences != sorted(sequences):
            errors.append("event sequences are not monotonic")
        if len(sequences) != len(set(sequences)):
            errors.append("event sequences are not unique")

        projection_index: dict[tuple[str, str], Mapping[str, Any]] = {}
        for raw in projections:
            if not isinstance(raw, Mapping):
                errors.append("projection row must be an object")
                continue
            namespace = str(raw.get("namespace", ""))
            key = str(raw.get("key", ""))
            value = raw.get("value")
            if not namespace or not key:
                errors.append("projection namespace/key are required")
                continue
            identity = (namespace, key)
            if identity in projection_index:
                errors.append(f"duplicate projection: {namespace}/{key}")
                continue
            if not isinstance(value, Mapping):
                errors.append(f"projection value must be an object: {namespace}/{key}")
                continue
            projection_index[identity] = value
            try:
                version = int(raw.get("version", 0))
            except (TypeError, ValueError):
                version = 0
            if version <= 0:
                errors.append(f"projection version must be positive: {namespace}/{key}")

        self._validate_graph(projection_index, errors)
        return BundleValidation(valid=not errors, errors=tuple(errors))

    def import_bundle(self, bundle: Mapping[str, Any]) -> None:
        validation = self.validate(bundle)
        if not validation.valid:
            raise ValueError("invalid state bundle: " + "; ".join(validation.errors))
        if self.ledger.events() or self.ledger.export_projection_rows():
            raise ValueError("state bundle import requires an empty destination ledger")
        self.ledger.import_state_rows(
            events=list(bundle["events"]),
            projections=list(bundle["projections"]),
        )

    @staticmethod
    def _validate_graph(
        index: dict[tuple[str, str], Mapping[str, Any]],
        errors: list[str],
    ) -> None:
        def require(namespace: str, key: object, owner: str) -> None:
            ref = str(key or "")
            if not ref or (namespace, ref) not in index:
                errors.append(f"{owner} references missing {namespace}/{ref or '<empty>'}")

        for (namespace, key), value in index.items():
            owner = f"{namespace}/{key}"
            if namespace == "execution.work":
                require(
                    "responsibility.current",
                    value.get("responsibility_id"),
                    owner,
                )
            elif namespace == "execution.run":
                require("execution.work", value.get("work_id"), owner)
            elif namespace == "governance.authorization":
                require("governance.mandate", value.get("mandate_id"), owner)
                require("decision.current", value.get("decision_id"), owner)
            elif namespace == "strategy.goal":
                require("governance.mandate", value.get("mandate_id"), owner)
                require("decision.current", value.get("decision_id"), owner)
            elif namespace == "recovery.disposition":
                require(
                    "execution.provider-attempt",
                    value.get("idempotency_key"),
                    owner,
                )
            elif namespace == "recovery.application":
                require(
                    "recovery.disposition",
                    value.get("idempotency_key"),
                    owner,
                )
            elif namespace == "recovery.resolution":
                require(
                    "recovery.disposition",
                    value.get("idempotency_key"),
                    owner,
                )
                require(
                    "recovery.application",
                    value.get("idempotency_key"),
                    owner,
                )
            elif namespace == "responsibility.relation":
                require(
                    "responsibility.current",
                    value.get("source_responsibility_id"),
                    owner,
                )
                require(
                    "responsibility.current",
                    value.get("target_responsibility_id"),
                    owner,
                )
            elif namespace == "strategy.issue":
                require("governance.mandate", value.get("mandate_id"), owner)
            elif namespace == "strategy.option":
                require("strategy.issue", value.get("issue_id"), owner)
            elif namespace == "strategy.portfolio-proposal":
                require("strategy.issue", value.get("issue_id"), owner)
                for option_id in value.get("option_ids", []):
                    require("strategy.option", option_id, owner)
                for goal_id in value.get("goal_refs", []):
                    require("strategy.goal", goal_id, owner)
            elif namespace == "strategy.portfolio":
                require(
                    "strategy.portfolio-proposal",
                    value.get("proposal_id"),
                    owner,
                )
                require("strategy.issue", value.get("issue_id"), owner)
                require("decision.current", value.get("decision_id"), owner)
                for option_id in value.get("option_ids", []):
                    require("strategy.option", option_id, owner)
                for goal_id in value.get("goal_refs", []):
                    require("strategy.goal", goal_id, owner)
            elif namespace == "strategy.portfolio-current":
                require("strategy.portfolio", value.get("id"), owner)
                require("strategy.issue", value.get("issue_id"), owner)
            elif namespace == "strategy.portfolio-allocation-state":
                require("strategy.portfolio", key, owner)
            elif namespace == "strategy.resource-allocation":
                require("strategy.portfolio", value.get("portfolio_id"), owner)
                require(
                    "responsibility.current",
                    value.get("responsibility_id"),
                    owner,
                )
                require("decision.current", value.get("decision_id"), owner)
            elif namespace == "qualification.dependency":
                previous_id = value.get("supersedes_dependency_id")
                if previous_id:
                    require("qualification.dependency", previous_id, owner)
            elif namespace == "qualification.review-obligation":
                require(
                    "qualification.dependency",
                    value.get("dependency_id"),
                    owner,
                )
            elif namespace == "qualification.revalidation-assessment":
                require(
                    "qualification.review-obligation",
                    value.get("obligation_id"),
                    owner,
                )


__all__ = [
    "BUNDLE_VERSION",
    "BundleValidation",
    "StateBundleService",
]
