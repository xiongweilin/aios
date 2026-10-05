from __future__ import annotations

import os

from administrative_orchestrator.integrations.credentials import CredentialRef
from administrative_orchestrator.integrations.effect_common import (
    ConnectorResult,
    ConnectorStatus,
)
from administrative_orchestrator.integrations.keycloak_effects import (
    KeycloakEffectConnection,
    KeycloakIdentityDisableConnector,
    KeycloakIdentityEffectConnector,
    KeycloakSessionRevokeConnector,
)
from administrative_orchestrator.integrations.odoo_effects import (
    OdooEffectConnection,
    OdooEmployeeDeactivateConnector,
    OdooEmployeeEffectConnector,
)
from administrative_orchestrator.integrations.runtime_capabilities import (
    ADMINISTRATIVE_HRIS_EMPLOYEE_DEACTIVATE,
    ADMINISTRATIVE_IAM_IDENTITY_DISABLE,
    ADMINISTRATIVE_IAM_SESSIONS_REVOKE,
)
from world_runtime import WorldRuntime
from world_runtime.execution import CapabilityEffectRule
from world_runtime.identity import DelegationGrant

from scripts.domains.administrative.production_world_runtime_stack import (
    ProductionEffectProvider,
)

CASE_ID = "00000000-0000-4000-8000-00000000baa4"
PRINCIPAL = "service:administrative-orchestrator"
CONTROLLER = "controller:administrative-orchestrator"
DELEGATION_ID = "delegation:baa-real-products-administrative"


class PostCommitUnknownConnector:
    """Acceptance shim that loses one successful provider acknowledgement."""

    def __init__(self, connector) -> None:
        self.connector = connector
        self.injected = False

    async def invoke(self, **kwargs) -> ConnectorResult:
        result: ConnectorResult = await self.connector.invoke(**kwargs)
        if not self.injected and result.status is ConnectorStatus.SUCCEEDED:
            self.injected = True
            return ConnectorResult(
                ConnectorStatus.UNKNOWN,
                external_operation_ref=result.external_operation_ref,
                error_code="InjectedLostAcknowledgement",
                error_message=(
                    "acceptance shim discarded the successful post-commit acknowledgement"
                ),
            )
        return result

    async def reconcile(self, request_ref: str) -> ConnectorResult | None:
        return await self.connector.reconcile(request_ref)


def build() -> WorldRuntime:
    state_path = os.environ["BAA_REAL_RUNTIME_STATE_PATH"]
    token = os.environ["BAA_REAL_RUNTIME_TOKEN"]

    runtime = WorldRuntime.sqlite(
        state_path,
        runtime_id="runtime:baa-real-products-acceptance",
        root_principal=PRINCIPAL,
    )

    bootstrap_token = f"bootstrap-{token}"
    runtime.identity.bind_bearer_token(
        principal=PRINCIPAL,
        token=bootstrap_token,
        credential_id="credential:baa-real-products-bootstrap",
    )
    runtime.identity.bind_bearer_token(
        principal=CONTROLLER,
        token=token,
        credential_id="credential:baa-real-products-controller",
    )
    grantor_context = runtime.identity.authenticate_bearer(
        f"Bearer {bootstrap_token}"
    )
    runtime.identity.grant_delegation(
        DelegationGrant(
            id=DELEGATION_ID,
            grantor=PRINCIPAL,
            grantee=CONTROLLER,
            scope={
                "case_id": CASE_ID,
                "authority_epoch": 1,
                "obligation_id": "*",
            },
            authority_ceiling={
                "operation": "*",
                "action": "*",
                "resource": "*",
            },
        ),
        context=grantor_context,
    )

    odoo_writer = OdooEmployeeEffectConnector(
        OdooEffectConnection(
            base_url=os.environ["BAA_REAL_ODOO_BASE_URL"],
            database=os.environ["BAA_REAL_ODOO_DATABASE"],
            username=os.environ["BAA_REAL_ODOO_WRITER_USERNAME"],
            credential=CredentialRef(
                "odoo:baa-real-products-writer",
                "BAA_REAL_ODOO_WRITER_SECRET",
            ),
            deactivate_request_ref_field="x_administrative_deactivate_request_ref",
            timeout_seconds=5.0,
            allow_insecure_http=True,
        )
    )
    keycloak_writer = KeycloakIdentityEffectConnector(
        KeycloakEffectConnection(
            base_url=os.environ["BAA_REAL_KEYCLOAK_BASE_URL"],
            realm=os.environ["BAA_REAL_KEYCLOAK_REALM"],
            client_id=os.environ["BAA_REAL_KEYCLOAK_WRITER_CLIENT_ID"],
            credential=CredentialRef(
                "keycloak:baa-real-products-writer",
                "BAA_REAL_KEYCLOAK_WRITER_SECRET",
            ),
            subject_ref_attribute="administrative_subject_ref",
            request_ref_attribute="administrative_request_ref",
            disable_request_ref_attribute="administrative_disable_request_ref",
            session_revoke_request_ref_attribute=(
                "administrative_session_revoke_request_ref"
            ),
            timeout_seconds=5.0,
            allow_insecure_http=True,
        )
    )

    identity_disable_connector = KeycloakIdentityDisableConnector(keycloak_writer)
    if os.environ.get("BAA_REAL_FAULT_MODE", "").strip() == "lost_ack":
        identity_disable_connector = PostCommitUnknownConnector(
            identity_disable_connector
        )

    providers = [
        ProductionEffectProvider(
            provider_id="provider:baa-real-products:odoo-deactivate-writer",
            name="BAA real-products Odoo employee deactivate writer",
            capability=ADMINISTRATIVE_HRIS_EMPLOYEE_DEACTIVATE,
            family="odoo",
            execution_domain="odoo:hris",
            credential_configuration_ref="odoo:baa-real-products-writer",
            network_domain="odoo",
            connector=OdooEmployeeDeactivateConnector(odoo_writer),
            reversibility="irreversible",
        ),
        ProductionEffectProvider(
            provider_id="provider:baa-real-products:keycloak-disable-writer",
            name="BAA real-products Keycloak identity disable writer",
            capability=ADMINISTRATIVE_IAM_IDENTITY_DISABLE,
            family="keycloak",
            execution_domain="keycloak:iam",
            credential_configuration_ref="keycloak:baa-real-products-writer",
            network_domain="keycloak",
            connector=identity_disable_connector,
            reversibility="irreversible",
        ),
        ProductionEffectProvider(
            provider_id="provider:baa-real-products:keycloak-session-writer",
            name="BAA real-products Keycloak session revoke writer",
            capability=ADMINISTRATIVE_IAM_SESSIONS_REVOKE,
            family="keycloak",
            execution_domain="keycloak:iam",
            credential_configuration_ref="keycloak:baa-real-products-writer",
            network_domain="keycloak",
            connector=KeycloakSessionRevokeConnector(keycloak_writer),
            reversibility="irreversible",
        ),
    ]
    for provider in providers:
        runtime.registry.register(provider)

    for capability in (
        ADMINISTRATIVE_HRIS_EMPLOYEE_DEACTIVATE,
        ADMINISTRATIVE_IAM_IDENTITY_DISABLE,
        ADMINISTRATIVE_IAM_SESSIONS_REVOKE,
    ):
        runtime.contract_registry.register_effect_rule(
            CapabilityEffectRule(
                capability=capability,
                impact_class="write-remote",
                authorization_required=True,
                resource_required=True,
                version_required=True,
                blast_radius=1,
                exposure=1,
            )
        )
    return runtime
