from __future__ import annotations

from .domain import AdministrativeCase
from .effect_provider import EffectProvider
from .fact_acquisition import AuthoritativeFactRevalidator
from .governance import GovernanceValidation
from .integrations.authoritative_sources import HRFactSource
from .observability import record_governance_revalidation
from .onboarding_execution import OnboardingExecutionEngine
from .persistence import SqlStore


class ProductionTrustOnboardingExecutionEngine(OnboardingExecutionEngine):
    """Onboarding execution guarded by current external authoritative HR truth.

    The base engine remains the business state machine. This production profile
    only strengthens its existing governance revalidation seam: before planning,
    after physical dispatch and before completion, the exact authoritative HRIS
    dependencies captured in the current FactSnapshot must still match a fresh
    read. A changed source identity/value or stale/unavailable observation is a
    governance failure, never permission to continue with previously valid facts.
    """

    def __init__(
        self,
        store: SqlStore,
        provider: EffectProvider,
        *,
        hris_source: HRFactSource,
        max_fact_age_seconds: int,
    ) -> None:
        super().__init__(store, provider)
        self.external_facts = AuthoritativeFactRevalidator(
            hris_source,
            max_age_seconds=max_fact_age_seconds,
        )

    def _validate_current_governance(
        self,
        case: AdministrativeCase,
    ) -> GovernanceValidation | None:
        domain_validation = super()._validate_current_governance(case)
        if domain_validation is not None and not domain_validation.valid:
            record_governance_revalidation(valid=False)
            return domain_validation

        external = self.external_facts.validate(case)
        if not external.valid:
            reasons = tuple(domain_validation.reasons if domain_validation else ()) + tuple(
                f"external-authoritative-fact: {reason}" for reason in external.reasons
            )
            record_governance_revalidation(valid=False)
            return GovernanceValidation(valid=False, reasons=reasons)

        record_governance_revalidation(valid=True)
        return domain_validation or GovernanceValidation(valid=True)


__all__ = ["ProductionTrustOnboardingExecutionEngine"]
