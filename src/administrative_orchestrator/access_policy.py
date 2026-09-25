from __future__ import annotations

from enum import StrEnum

from .authority import AuthorityRepository
from .domain import AdministrativeCase


class AdministrativePermission(StrEnum):
    CASE_READ = "case.read"
    FACTS_READ = "case.facts.read"
    FACTS_ATTEST = "case.facts.attest"
    COMMITMENT_ATTEST = "commitment.fulfillment.attest"
    FACTS_REFRESH_AUTHORITATIVE = "case.facts.refresh_authoritative"
    DECISION_SUBMIT = "decision.submit"
    CASE_REASSESS = "case.reassess"
    POLICY_READ = "policy.read"
    POLICY_MANAGE = "policy.manage"
    AUDIT_READ = "audit.read"
    OPERATIONS_READ = "operations.read"
    INTAKE_REVIEW = "intake.review"
    INVESTIGATION_READ = "investigation.read"
    INVESTIGATION_REQUEST = "investigation.request"
    INVESTIGATION_REVIEW = "investigation.review"
    REOPEN_AUTHORIZE = "case.reopen.authorize"
    IDENTITY_MANAGE = "identity.manage"
    DEAD_LETTER_READ = "dead_letter.read"
    DEAD_LETTER_REPLAY = "dead_letter.replay"


class AccessDenied(PermissionError):
    pass


_CASE_READER_ROLES = {
    "hr_approver",
    "manager",
    "access_approver",
    "hr_operator",
    "administrative_operator",
    "administrative_auditor",
    "administrative_admin",
}
_FACT_ATTEST_ROLES = {"hr_operator", "administrative_operator", "administrative_admin"}
_REASSESS_ROLES = {"administrative_operator", "administrative_admin"}
_POLICY_READ_ROLES = {
    "policy_owner",
    "administrative_operator",
    "administrative_auditor",
    "administrative_admin",
}
_POLICY_MANAGE_ROLES = {"policy_owner", "administrative_admin"}
_AUDIT_READ_ROLES = {
    "administrative_operator",
    "administrative_auditor",
    "administrative_admin",
}
_OPERATIONS_READ_ROLES = {
    "administrative_operator",
    "administrative_auditor",
    "platform_operator",
    "administrative_admin",
}
_INTAKE_REVIEW_ROLES = {"administrative_operator", "administrative_admin"}
_INVESTIGATION_READ_ROLES = {
    "administrative_operator",
    "administrative_auditor",
    "administrative_admin",
    "platform_operator",
}
_INVESTIGATION_REQUEST_ROLES = {"administrative_operator", "administrative_admin"}
_INVESTIGATION_REVIEW_ROLES = {"administrative_operator", "administrative_admin"}
_REOPEN_AUTHORIZE_ROLES = {"administrative_operator", "administrative_admin"}
_IDENTITY_MANAGE_ROLES = {"administrative_admin"}
_PLATFORM_OPS_ROLES = {"platform_operator", "administrative_admin"}


class AdministrativeAccessPolicy:
    """Fail-closed resource authorization over current organizational roles.

    Authentication proves who the caller is. This policy separately proves
    whether that principal may inspect or mutate a particular administrative
    resource. Platform-operations authority is intentionally distinct from
    business approval authority.
    """

    def __init__(self, authority: AuthorityRepository) -> None:
        self.authority = authority

    def require(
        self,
        principal_id: str,
        permission: AdministrativePermission,
        *,
        case: AdministrativeCase | None = None,
        organization_scope: str | None = None,
    ) -> None:
        if not self.allows(
            principal_id,
            permission,
            case=case,
            organization_scope=organization_scope,
        ):
            raise AccessDenied(f"principal {principal_id} lacks {permission.value}")

    def allows(
        self,
        principal_id: str,
        permission: AdministrativePermission,
        *,
        case: AdministrativeCase | None = None,
        organization_scope: str | None = None,
    ) -> bool:
        if self.authority.get_principal(principal_id) is None:
            return False

        scope = organization_scope or (_case_scope(case) if case is not None else "*")
        roles = self.authority.roles_for(principal_id, organization_scope=scope)

        if permission in {AdministrativePermission.CASE_READ, AdministrativePermission.FACTS_READ}:
            return bool(case and case.requester_principal_id == principal_id) or bool(
                roles.intersection(_CASE_READER_ROLES)
            )
        if permission in {
            AdministrativePermission.FACTS_ATTEST,
            AdministrativePermission.FACTS_REFRESH_AUTHORITATIVE,
        }:
            return bool(roles.intersection(_FACT_ATTEST_ROLES))
        if permission == AdministrativePermission.COMMITMENT_ATTEST:
            return bool(case and case.requester_principal_id == principal_id) or bool(
                roles.intersection(_FACT_ATTEST_ROLES)
            )
        if permission == AdministrativePermission.DECISION_SUBMIT:
            return bool(roles)
        if permission == AdministrativePermission.CASE_REASSESS:
            return bool(roles.intersection(_REASSESS_ROLES))
        if permission == AdministrativePermission.POLICY_READ:
            return bool(roles.intersection(_POLICY_READ_ROLES))
        if permission == AdministrativePermission.POLICY_MANAGE:
            return bool(roles.intersection(_POLICY_MANAGE_ROLES))
        if permission == AdministrativePermission.AUDIT_READ:
            return bool(roles.intersection(_AUDIT_READ_ROLES))
        if permission == AdministrativePermission.OPERATIONS_READ:
            return bool(roles.intersection(_OPERATIONS_READ_ROLES))
        if permission == AdministrativePermission.INTAKE_REVIEW:
            return bool(roles.intersection(_INTAKE_REVIEW_ROLES))
        if permission == AdministrativePermission.INVESTIGATION_READ:
            return bool(roles.intersection(_INVESTIGATION_READ_ROLES))
        if permission == AdministrativePermission.INVESTIGATION_REQUEST:
            return bool(roles.intersection(_INVESTIGATION_REQUEST_ROLES))
        if permission == AdministrativePermission.INVESTIGATION_REVIEW:
            return bool(roles.intersection(_INVESTIGATION_REVIEW_ROLES))
        if permission == AdministrativePermission.REOPEN_AUTHORIZE:
            return bool(roles.intersection(_REOPEN_AUTHORIZE_ROLES))
        if permission == AdministrativePermission.IDENTITY_MANAGE:
            return bool(roles.intersection(_IDENTITY_MANAGE_ROLES))
        if permission in {
            AdministrativePermission.DEAD_LETTER_READ,
            AdministrativePermission.DEAD_LETTER_REPLAY,
        }:
            return bool(roles.intersection(_PLATFORM_OPS_ROLES))
        return False


def _case_scope(case: AdministrativeCase | None) -> str:
    if case is None or case.fact_snapshot is None:
        return "*"
    department = case.fact_snapshot.facts.get("department_ref")
    return str(department) if department else "*"


__all__ = [
    "AccessDenied",
    "AdministrativeAccessPolicy",
    "AdministrativePermission",
]
