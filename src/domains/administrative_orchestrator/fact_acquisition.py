from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .config import Settings
from .domain import AdministrativeCase, FactAssertion, FactAuthority, FactSnapshot, utcnow
from .integrations.authoritative_sources import AuthoritativeRecord, HRFactSource
from .integrations.credentials import CredentialRef
from .integrations.odoo import OdooConnection, OdooHRFactSource


class FactAcquisitionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ExternalFactValidation:
    valid: bool
    reasons: tuple[str, ...] = ()


def build_hris_source(settings: Settings) -> HRFactSource | None:
    if settings.hris_source_kind == "disabled":
        return None
    if settings.hris_source_kind == "odoo":
        return OdooHRFactSource(
            OdooConnection(
                base_url=settings.odoo_base_url,
                database=settings.odoo_database,
                username=settings.odoo_reader_username,
                reader_credential=CredentialRef(
                    configuration_ref="odoo:hris-reader",
                    environment_variable=settings.odoo_reader_secret_env,
                ),
                timeout_seconds=settings.connector_timeout_seconds,
                allow_insecure_http=settings.runtime_profile != "production",
            ),
            termination_status_field=settings.odoo_termination_status_field,
            termination_effective_at_field=settings.odoo_termination_effective_at_field,
            employment_episode_field=settings.odoo_employment_episode_field,
            principal_id_field=settings.odoo_principal_id_field,
        )
    raise FactAcquisitionError(f"unsupported HRIS source kind {settings.hris_source_kind!r}")


def _merge_authoritative_facts(
    case: AdministrativeCase,
    record: AuthoritativeRecord,
    *,
    source: str,
    authoritative_keys: tuple[str, ...],
    owner: str = "service:administrative-orchestrator",
) -> FactSnapshot:
    """Overlay authoritative HRIS fields without promoting request-only inputs."""

    if case.fact_snapshot is None:
        raise FactAcquisitionError("case has no current fact snapshot")
    if not record.value.get("present", False):
        raise FactAcquisitionError("authoritative HRIS reports employee absent")

    facts = dict(case.fact_snapshot.facts)
    assertions = _existing_assertions(case.fact_snapshot)
    for key in authoritative_keys:
        if key not in record.value:
            continue
        value = record.value[key]
        if value is None:
            # An authoritative source that reports no value for a field must
            # not erase a human-admitted claim for that field. The claim stays
            # the effective value until an authoritative value exists.
            continue
        facts[key] = value
        assertions[key] = FactAssertion(
            value=value,
            authority=FactAuthority.AUTHORITATIVE,
            source=record.source,
            owner=owner,
            source_ref=record.source_ref,
            source_version=record.source_version,
            observed_at=record.observed_at,
            digest=_value_digest(value),
        )

    digest = _snapshot_digest(facts, assertions)
    return FactSnapshot(
        source=source,
        owner=owner,
        # Conservative compatibility aggregate: mixed snapshots are never
        # globally promoted above their least-authoritative constituent.
        authority=FactAuthority.CLAIM,
        source_ref=record.source_ref,
        source_version=record.source_version,
        observed_at=record.observed_at,
        facts=facts,
        assertions=assertions,
        digest=digest,
    )


_ONBOARDING_AUTHORITATIVE_KEYS = (
    "employee_ref",
    "department_ref",
    "start_date",
    "employment_type",
    "manager_ref",
    "work_email",
    "active",
    "employment_state",
)

_OFFBOARDING_AUTHORITATIVE_KEYS = (
    "employee_ref",
    "department_ref",
    "employment_type",
    "termination_status",
    "termination_effective_at",
    "employment_episode_ref",
    "departing_principal_id",
    "active",
)


def merge_authoritative_onboarding_facts(
    case: AdministrativeCase,
    record: AuthoritativeRecord,
    *,
    owner: str = "service:administrative-orchestrator",
) -> FactSnapshot:
    """Overlay authoritative HRIS fields without promoting request-only inputs."""
    return _merge_authoritative_facts(
        case,
        record,
        source="composite:employee-onboarding",
        authoritative_keys=_ONBOARDING_AUTHORITATIVE_KEYS,
        owner=owner,
    )


def merge_authoritative_offboarding_facts(
    case: AdministrativeCase,
    record: AuthoritativeRecord,
    *,
    owner: str = "service:administrative-orchestrator",
) -> FactSnapshot:
    """Overlay authoritative HRIS termination facts for employee offboarding."""
    return _merge_authoritative_facts(
        case,
        record,
        source="composite:employee-offboarding",
        authoritative_keys=_OFFBOARDING_AUTHORITATIVE_KEYS,
        owner=owner,
    )


class AuthoritativeFactRevalidator:
    """Re-read current HRIS truth before governed execution/completion."""

    def __init__(self, source: HRFactSource, *, max_age_seconds: int) -> None:
        self.source = source
        self.max_age_seconds = max_age_seconds

    def validate(self, case: AdministrativeCase) -> ExternalFactValidation:
        return self.validate_with_dependencies(case, expected_change_keys=())

    def validate_with_dependencies(
        self, case: AdministrativeCase, *, expected_change_keys: tuple[str, ...] = ()
    ) -> ExternalFactValidation:
        """Re-read current HRIS truth, ignoring facts the approved effects change."""
        snapshot = case.fact_snapshot
        if snapshot is None:
            return ExternalFactValidation(False, ("case has no current fact snapshot",))
        expected = {
            key: assertion
            for key, assertion in snapshot.assertions.items()
            if assertion.authority is FactAuthority.AUTHORITATIVE
            and key not in expected_change_keys
            and key
            in {
                "employee_ref",
                "department_ref",
                "start_date",
                "employment_type",
                "manager_ref",
                "work_email",
                "active",
                "employment_state",
                "termination_status",
                "termination_effective_at",
                "employment_episode_ref",
            }
        }
        if not expected:
            return ExternalFactValidation(False, ("no authoritative HRIS fact dependencies recorded",))
        try:
            current = self.source.read_employee(case.subject_ref)
        except Exception as exc:
            return ExternalFactValidation(False, (f"authoritative HRIS read failed: {exc}",))
        now = utcnow()
        if not current.is_fresh_at(now, max_age_seconds=self.max_age_seconds):
            return ExternalFactValidation(False, ("authoritative HRIS observation is stale",))
        if not current.value.get("present", False):
            return ExternalFactValidation(False, ("authoritative HRIS reports subject absent",))

        reasons: list[str] = []
        for key, assertion in expected.items():
            if assertion.source != current.source:
                reasons.append(f"authoritative source changed for {key}")
                continue
            if assertion.source_ref != current.source_ref:
                reasons.append(f"authoritative source identity changed for {key}")
                continue
            if current.value.get(key) != assertion.value:
                reasons.append(f"authoritative value changed for {key}")
        return ExternalFactValidation(not reasons, tuple(reasons))


def _existing_assertions(snapshot: FactSnapshot) -> dict[str, FactAssertion]:
    if snapshot.assertions:
        return dict(snapshot.assertions)
    return {
        key: FactAssertion(
            value=value,
            authority=snapshot.authority,
            source=snapshot.source,
            owner=snapshot.owner,
            source_ref=snapshot.source_ref,
            source_version=snapshot.source_version,
            observed_at=snapshot.observed_at,
            digest=_value_digest(value),
        )
        for key, value in snapshot.facts.items()
    }


def _value_digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _snapshot_digest(facts: dict[str, Any], assertions: dict[str, FactAssertion]) -> str:
    payload = {
        "facts": facts,
        "assertions": {
            key: assertion.model_dump(mode="json") for key, assertion in sorted(assertions.items())
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


__all__ = [
    "AuthoritativeFactRevalidator",
    "ExternalFactValidation",
    "FactAcquisitionError",
    "build_hris_source",
    "merge_authoritative_onboarding_facts",
]
