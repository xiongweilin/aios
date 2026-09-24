from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request

from ..access_policy import AccessDenied, AdministrativeAccessPolicy, AdministrativePermission
from ..admission import IntakeAssessmentService, IntakePromotionService
from ..auth import AuthenticatedPrincipal, Authenticator
from ..authority import AuthorityRepository
from ..authority_lifecycle import AuthorityLifecycleRepository
from ..commitment_repository import CommitmentRepository
from ..commitment_service import MeetingCommitmentService
from ..config import Settings, get_settings
from ..conversation import ConversationMessageRow, ConversationRow
from ..domain import AdministrativeCase
from ..execution_repository import ExecutionRepository
from ..governance import GovernanceRepository
from ..intake.repository import IntakeRepository
from ..investigation_client import build_investigation_client
from ..investigation_reconciliation import LocalWorldRuntimeReconciliationVerifier
from ..investigation_repository import InvestigationRepository
from ..investigation_service import InvestigationService
from ..obligations import ObligationRepository
from ..persistence import SqlStore
from ..policy_plane import PolicyRepository
from ..transaction_repository import TransactionRepository
from ..unit_of_work import AdministrativeUnitOfWork

# Importing these mapped rows before optional schema creation preserves the
# legacy Operations process metadata-registration behavior.
_CONVERSATION_SCHEMA = (ConversationRow, ConversationMessageRow)


@dataclass(slots=True)
class OperationsRuntime:
    settings: Settings
    store: SqlStore
    authority: AuthorityRepository
    access: AdministrativeAccessPolicy
    authenticator: Authenticator
    lifecycle: AuthorityLifecycleRepository
    execution: ExecutionRepository
    governance: GovernanceRepository
    obligations: ObligationRepository
    policies: PolicyRepository
    transactions: TransactionRepository
    uow: AdministrativeUnitOfWork
    intake: IntakeRepository
    intake_assessments: IntakeAssessmentService
    intake_promotions: IntakePromotionService
    commitments: CommitmentRepository
    commitment_service: MeetingCommitmentService
    investigations: InvestigationRepository
    investigation_service: InvestigationService

    def actor(self, request: Request) -> AuthenticatedPrincipal:
        return self.authenticator.authenticate(request)

    def require(
        self,
        actor: AuthenticatedPrincipal,
        permission: AdministrativePermission,
        *,
        case: AdministrativeCase | None = None,
    ) -> None:
        try:
            self.access.require(
                actor.principal_id,
                permission,
                case=case,
                organization_scope="*" if case is None else None,
            )
        except AccessDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    def require_intake_review(self, actor: AuthenticatedPrincipal) -> None:
        self.require(actor, AdministrativePermission.INTAKE_REVIEW)


def build_operations_runtime(settings: Settings | None = None) -> OperationsRuntime:
    settings = settings or get_settings()
    store = SqlStore(settings.database_url)
    authority = AuthorityRepository(store)
    access = AdministrativeAccessPolicy(authority)
    authenticator = Authenticator(store, settings)
    lifecycle = AuthorityLifecycleRepository(store)
    execution = ExecutionRepository(store)
    governance = GovernanceRepository(store)
    obligations = ObligationRepository(store)
    policies = PolicyRepository(store)
    transactions = TransactionRepository(store)
    uow = AdministrativeUnitOfWork(store)
    intake = IntakeRepository(store)
    intake_assessments = IntakeAssessmentService(intake)
    intake_promotions = IntakePromotionService(store, intake)
    commitments = CommitmentRepository(store)
    commitment_service = MeetingCommitmentService(
        store,
        repository=commitments,
        authority=authority,
        uow=uow,
        policies=policies,
        settings=settings,
    )
    investigations = InvestigationRepository(store)
    runtime_reconciliation_verifier = LocalWorldRuntimeReconciliationVerifier(
        store=store,
        settings=settings,
    )
    investigation_service = InvestigationService(
        store,
        repository=investigations,
        client=build_investigation_client(settings),
        reconciliation_verifier=runtime_reconciliation_verifier,
    )
    if settings.auto_create_schema:
        store.init_schema()
    return OperationsRuntime(
        settings=settings,
        store=store,
        authority=authority,
        access=access,
        authenticator=authenticator,
        lifecycle=lifecycle,
        execution=execution,
        governance=governance,
        obligations=obligations,
        policies=policies,
        transactions=transactions,
        uow=uow,
        intake=intake,
        intake_assessments=intake_assessments,
        intake_promotions=intake_promotions,
        commitments=commitments,
        commitment_service=commitment_service,
        investigations=investigations,
        investigation_service=investigation_service,
    )


__all__ = ["OperationsRuntime", "build_operations_runtime"]
