from __future__ import annotations

import os
from pathlib import Path

import httpx
from world_runtime import WorldRuntime
from world_runtime.execution import (
    CapabilityEffectRule,
    CapabilityRequest,
    CapabilityResult,
    InvocationContext,
    ProviderDescriptor,
    ProviderHealth,
)

from administrative_orchestrator.config import get_settings
from administrative_orchestrator.integrations.credentials import (
    CredentialRef,
    EnvironmentOrFileCredentialResolver,
    read_credential_file,
)
from administrative_orchestrator.integrations.production_effects import (
    AdministrativeCommunicationEffectConnection,
    AdministrativeCommunicationEffectConnector,
    ConnectorResult,
    ConnectorStatus,
    FeishuCommunicationVerifier,
    KeycloakEffectConnection,
    KeycloakIdentityDisableConnector,
    KeycloakIdentityDisableVerifier,
    KeycloakIdentityEffectConnector,
    KeycloakIdentityVerifier,
    KeycloakSessionRevokeConnector,
    KeycloakSessionVerifier,
    OdooEffectConnection,
    OdooEmployeeDeactivateConnector,
    OdooEmployeeDeactivateVerifier,
    OdooEmployeeEffectConnector,
    OdooEmployeeVerifier,
    OdooFinancialEffectConnector,
    OdooFinancialVerifier,
)
from administrative_orchestrator.integrations.runtime_capabilities import (
    ADMINISTRATIVE_COMMUNICATION_MESSAGE_SEND,
    ADMINISTRATIVE_ERP_EXPENSE_REPORT_CREATE,
    ADMINISTRATIVE_ERP_PURCHASE_ORDER_CONFIRM,
    ADMINISTRATIVE_ERP_PURCHASE_ORDER_CREATE_DRAFT,
    ADMINISTRATIVE_ERP_VENDOR_BILL_CREATE_DRAFT,
    ADMINISTRATIVE_HRIS_EMPLOYEE_CREATE,
    ADMINISTRATIVE_HRIS_EMPLOYEE_DEACTIVATE,
    ADMINISTRATIVE_IAM_IDENTITY_CREATE,
    ADMINISTRATIVE_IAM_IDENTITY_DISABLE,
    ADMINISTRATIVE_IAM_SESSIONS_REVOKE,
)
from administrative_orchestrator.production_verification import (
    complete_readback_postcondition,
    readback_satisfies_expected,
)

IAM_CAPABILITY = ADMINISTRATIVE_IAM_IDENTITY_CREATE


def _verification_capability(effect_capability: str) -> str:
    return f"{effect_capability}.verify"


class ProductionEffectProvider:
    def __init__(
        self,
        *,
        provider_id: str,
        name: str,
        capability: str,
        family: str,
        execution_domain: str,
        credential_configuration_ref: str,
        network_domain: str,
        connector,
        operation: str | None = None,
        reversibility: str = "compensatable",
    ) -> None:
        self.connector = connector
        self.operation = operation
        self._descriptor = ProviderDescriptor(
            id=provider_id,
            name=name,
            version="2026.09-m5",
            capabilities=[capability],
            effect_semantics="reconcilable",
            side_effect_class="reconcilable",
            reversibility=reversibility,
            provider_family=family,
            operator="administrative-production",
            execution_domain=execution_domain,
            credential_domain=credential_configuration_ref,
            data_source_domain=execution_domain,
            network_domain=network_domain,
            trust_boundary="enterprise-production",
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider_id=self.descriptor.id, available=True)

    async def invoke(
        self,
        request: CapabilityRequest,
        context: InvocationContext,
    ) -> CapabilityResult:
        del context
        # World Runtime carries the governed subject identity into the frozen intent.
        # Keep it separate from business payload fields such as employee_ref;
        # financial transactions may legitimately have a transaction subject
        # while targeting an existing employee record.
        subject_ref = request.parameters.get("subject_ref")
        if not isinstance(subject_ref, str) or not subject_ref:
            subject_ref = request.parameters.get("employee_ref")
        if not isinstance(subject_ref, str) or not subject_ref:
            raise ValueError("production administrative effect requires subject identity")
        invoke_kwargs = {
            "request_ref": request.id,
            "subject_ref": subject_ref,
            "parameters": dict(request.parameters),
        }
        if self.operation is not None:
            invoke_kwargs["operation"] = self.operation
        result: ConnectorResult = await self.connector.invoke(**invoke_kwargs)
        return _capability_result(request.id, self.descriptor.id, result)

    async def cancel(self, request_id: str) -> None:
        del request_id

    async def reconcile(self, request_id: str) -> CapabilityResult | None:
        reconcile_kwargs = {"request_ref": request_id}
        if self.operation is not None:
            reconcile_kwargs["operation"] = self.operation
        result: ConnectorResult | None = await self.connector.reconcile(**reconcile_kwargs)
        if result is None:
            return None
        return _capability_result(request_id, self.descriptor.id, result)


class ProductionReadbackVerifier:
    def __init__(
        self,
        *,
        provider_id: str,
        name: str,
        effect_capability: str,
        family: str,
        credential_configuration_ref: str,
        network_domain: str,
        verifier,
    ) -> None:
        self.effect_capability = effect_capability
        self.verifier = verifier
        self._descriptor = ProviderDescriptor(
            id=provider_id,
            name=name,
            version="2026.09-m5",
            capabilities=[_verification_capability(effect_capability)],
            effect_semantics="pure",
            side_effect_class="pure",
            reversibility="unknown",
            provider_family=family,
            operator="administrative-production",
            execution_domain="verification",
            credential_domain=credential_configuration_ref,
            data_source_domain=family,
            evaluation_domain="objective-postcondition",
            network_domain=network_domain,
            trust_boundary="enterprise-production",
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider_id=self.descriptor.id, available=True)

    async def invoke(
        self,
        request: CapabilityRequest,
        context: InvocationContext,
    ) -> CapabilityResult:
        del context
        scope = request.parameters.get("verification_scope")
        if not isinstance(scope, dict):
            raise ValueError("verification_scope required")
        capability = scope.get("effect_capability")
        subject_ref = scope.get("subject_ref")
        expected = scope.get("expected_postcondition")
        if capability != self.effect_capability:
            raise ValueError("verification effect capability rebound")
        if not isinstance(subject_ref, str) or not isinstance(expected, dict):
            raise ValueError("verification scope is incomplete")
        result: ConnectorResult = await self.verifier.observe(
            subject_ref=subject_ref,
            expected_postcondition=dict(expected),
        )
        if result.status is ConnectorStatus.UNAVAILABLE:
            return CapabilityResult(
                request_id=request.id,
                provider_id=self.descriptor.id,
                status="unavailable",
                error={
                    "code": result.error_code or "VerificationUnavailable",
                    "message": result.error_message or "verification unavailable",
                },
            )
        observed = complete_readback_postcondition(
            expected,
            result.observed_postcondition,
        )
        objective = "pass" if readback_satisfies_expected(expected, observed) else "fail"
        return CapabilityResult(
            request_id=request.id,
            provider_id=self.descriptor.id,
            status="succeeded",
            metadata={
                "observed_postcondition": observed,
                "verification_result": objective,
                "verification_message": "independent production administrative readback",
            },
        )

    async def cancel(self, request_id: str) -> None:
        del request_id

    async def reconcile(self, request_id: str) -> CapabilityResult | None:
        del request_id
        return None


def _capability_result(
    request_id: str,
    provider_id: str,
    result: ConnectorResult,
) -> CapabilityResult:
    if result.status is ConnectorStatus.SUCCEEDED:
        return CapabilityResult(
            request_id=request_id,
            provider_id=provider_id,
            status="succeeded",
            external_operation_ref=result.external_operation_ref,
            reconciled=result.reconciled,
        )
    if result.status is ConnectorStatus.FAILED:
        status = "failed"
    elif result.status is ConnectorStatus.UNAVAILABLE:
        status = "unavailable"
    else:
        status = "unknown"
    return CapabilityResult(
        request_id=request_id,
        provider_id=provider_id,
        status=status,
        reconciled=result.reconciled,
        error={
            "code": result.error_code or "ConnectorFailure",
            "message": result.error_message or result.status.value,
        },
    )


def build() -> WorldRuntime:
    settings = get_settings()
    if settings.runtime_profile not in {"staging", "production"}:
        raise RuntimeError(
            "production World Runtime stack requires ADMIN_RUNTIME_PROFILE=staging or production"
        )
    state_path = os.getenv("WORLD_RUNTIME_ADMIN_PRODUCTION_STATE_PATH", "").strip()
    if not state_path:
        raise RuntimeError("WORLD_RUNTIME_ADMIN_PRODUCTION_STATE_PATH is required")
    communication_gateway_base_url = settings.communication_gateway_base_url.strip()

    runtime = WorldRuntime.sqlite(
        Path(state_path),
        runtime_id="runtime:administrative-production",
    )
    registry = runtime.registry

    odoo_writer = OdooEmployeeEffectConnector(
        OdooEffectConnection(
            base_url=settings.odoo_base_url,
            database=settings.odoo_database,
            username=settings.odoo_writer_username,
            credential=CredentialRef("odoo:hris-writer", settings.odoo_writer_secret_env),
            request_ref_field=settings.odoo_request_ref_field,
            deactivate_request_ref_field=settings.odoo_deactivate_request_ref_field,
            timeout_seconds=settings.connector_timeout_seconds,
            allow_insecure_http=settings.oidc_allow_insecure_http,
        )
    )
    odoo_verifier_connector = OdooEmployeeEffectConnector(
        OdooEffectConnection(
            base_url=settings.odoo_base_url,
            database=settings.odoo_database,
            username=settings.odoo_verifier_username,
            credential=CredentialRef("odoo:hris-verifier", settings.odoo_verifier_secret_env),
            request_ref_field=settings.odoo_request_ref_field,
            deactivate_request_ref_field=settings.odoo_deactivate_request_ref_field,
            timeout_seconds=settings.connector_timeout_seconds,
            allow_insecure_http=settings.oidc_allow_insecure_http,
        )
    )
    keycloak_writer = KeycloakIdentityEffectConnector(
        KeycloakEffectConnection(
            base_url=settings.keycloak_base_url,
            realm=settings.keycloak_realm,
            client_id=settings.keycloak_writer_client_id,
            credential=CredentialRef("keycloak:iam-writer", settings.keycloak_writer_secret_env),
            request_ref_attribute=settings.keycloak_request_ref_attribute,
            disable_request_ref_attribute=settings.keycloak_disable_request_ref_attribute,
            session_revoke_request_ref_attribute=(
                settings.keycloak_session_revoke_request_ref_attribute
            ),
            timeout_seconds=settings.connector_timeout_seconds,
            allow_insecure_http=settings.oidc_allow_insecure_http,
        )
    )
    keycloak_verifier_connector = KeycloakIdentityEffectConnector(
        KeycloakEffectConnection(
            base_url=settings.keycloak_base_url,
            realm=settings.keycloak_realm,
            client_id=settings.keycloak_verifier_client_id,
            credential=CredentialRef("keycloak:iam-verifier", settings.keycloak_verifier_secret_env),
            request_ref_attribute=settings.keycloak_request_ref_attribute,
            disable_request_ref_attribute=settings.keycloak_disable_request_ref_attribute,
            session_revoke_request_ref_attribute=(
                settings.keycloak_session_revoke_request_ref_attribute
            ),
            timeout_seconds=settings.connector_timeout_seconds,
            allow_insecure_http=settings.oidc_allow_insecure_http,
        )
    )
    financial_writer_username = getattr(
        settings, "odoo_financial_writer_username", settings.odoo_writer_username
    )
    financial_writer_secret_env = getattr(
        settings, "odoo_financial_writer_secret_env", settings.odoo_writer_secret_env
    )
    financial_verifier_username = getattr(
        settings, "odoo_financial_verifier_username", settings.odoo_verifier_username
    )
    financial_verifier_secret_env = getattr(
        settings, "odoo_financial_verifier_secret_env", settings.odoo_verifier_secret_env
    )
    transaction_request_ref_field = getattr(
        settings,
        "odoo_transaction_request_ref_field",
        "x_administrative_transaction_request_ref",
    )
    transaction_confirm_request_ref_field = getattr(
        settings,
        "odoo_transaction_confirm_request_ref_field",
        "x_administrative_transaction_confirm_request_ref",
    )
    transaction_subject_ref_field = getattr(
        settings,
        "odoo_transaction_subject_ref_field",
        "x_administrative_transaction_subject_ref",
    )
    transaction_payload_field = getattr(
        settings,
        "odoo_transaction_payload_field",
        "x_administrative_m8_payload_json",
    )
    odoo_financial_writer = OdooFinancialEffectConnector(
        OdooEffectConnection(
            base_url=settings.odoo_base_url,
            database=settings.odoo_database,
            username=financial_writer_username,
            credential=CredentialRef(
                "odoo:erp-writer", financial_writer_secret_env
            ),
            transaction_request_ref_field=transaction_request_ref_field,
            transaction_confirm_request_ref_field=transaction_confirm_request_ref_field,
            transaction_subject_ref_field=transaction_subject_ref_field,
            transaction_payload_field=transaction_payload_field,
            timeout_seconds=settings.connector_timeout_seconds,
            allow_insecure_http=settings.oidc_allow_insecure_http,
        )
    )
    odoo_financial_verifier_connector = OdooFinancialEffectConnector(
        OdooEffectConnection(
            base_url=settings.odoo_base_url,
            database=settings.odoo_database,
            username=financial_verifier_username,
            credential=CredentialRef(
                "odoo:erp-verifier", financial_verifier_secret_env
            ),
            transaction_request_ref_field=transaction_request_ref_field,
            transaction_confirm_request_ref_field=transaction_confirm_request_ref_field,
            transaction_subject_ref_field=transaction_subject_ref_field,
            transaction_payload_field=transaction_payload_field,
            timeout_seconds=settings.connector_timeout_seconds,
            allow_insecure_http=settings.oidc_allow_insecure_http,
        )
    )

    communication_provider = None
    communication_verifier = None
    if communication_gateway_base_url:
        transport_secret_env = getattr(
            settings,
            "communication_transport_secret_env",
            "ADMIN_COMMUNICATION_TRANSPORT_SECRET",
        )
        verifier_secret_env = getattr(
            settings,
            "communication_verifier_app_secret_env",
            "ADMIN_COMMUNICATION_VERIFIER_APP_SECRET",
        )
        communication_credentials = EnvironmentOrFileCredentialResolver(
            {
                transport_secret_env: getattr(
                    settings,
                    "communication_transport_secret_file",
                    "",
                ).strip(),
                verifier_secret_env: (
                    getattr(settings, "communication_verifier_app_secret_file", "").strip()
                    or getattr(settings, "feishu_app_secret_file", "").strip()
                ),
            }
        )
        communication_connection = AdministrativeCommunicationEffectConnection(
            gateway_base_url=communication_gateway_base_url,
            transport_credential=CredentialRef(
                "gateway:administrative-communication",
                transport_secret_env,
            ),
            artifact_root=Path(settings.feishu_artifact_root),
            timeout_seconds=getattr(settings, "communication_gateway_timeout_seconds", 10.0),
            allow_insecure_http=settings.oidc_allow_insecure_http,
        )
        communication_provider = ProductionEffectProvider(
            provider_id="provider:administrative-production:feishu-communication-writer",
            name="Administrative Feishu communication writer",
            capability=ADMINISTRATIVE_COMMUNICATION_MESSAGE_SEND,
            family="feishu-gateway",
            execution_domain="feishu:communication",
            credential_configuration_ref="gateway:administrative-communication",
            network_domain=_host(communication_gateway_base_url),
            connector=AdministrativeCommunicationEffectConnector(
                communication_connection,
                credentials=communication_credentials,
            ),
            reversibility="irreversible",
        )
        verifier_app_id = getattr(settings, "communication_verifier_app_id", "").strip()
        if not verifier_app_id:
            verifier_app_id_file = (
                getattr(settings, "communication_verifier_app_id_file", "").strip()
                or getattr(settings, "feishu_app_id_file", "").strip()
            )
            if verifier_app_id_file:
                verifier_app_id = read_credential_file(
                    verifier_app_id_file,
                    configuration_ref="feishu:communication-verifier",
                )
        if not verifier_app_id:
            raise RuntimeError(
                "M9 communication capability requires a configured verifier app id"
            )
        communication_verifier = ProductionReadbackVerifier(
                provider_id="provider:administrative-production:feishu-communication-verifier",
                name="Administrative Feishu communication independent verifier",
                effect_capability=ADMINISTRATIVE_COMMUNICATION_MESSAGE_SEND,
                family="feishu-readback",
                credential_configuration_ref="feishu:communication-verifier",
                network_domain=_host(settings.feishu_base_url),
                verifier=FeishuCommunicationVerifier(
                    base_url=settings.feishu_base_url,
                    app_id=verifier_app_id,
                    app_secret=CredentialRef(
                        "feishu:communication-verifier",
                        getattr(
                            settings,
                            "communication_verifier_app_secret_env",
                            "ADMIN_COMMUNICATION_VERIFIER_APP_SECRET",
                        ),
                    ),
                    gateway_base_url=communication_gateway_base_url,
                    gateway_secret=CredentialRef(
                        "gateway:communication-verifier",
                        getattr(
                            settings,
                            "communication_verifier_gateway_secret_env",
                            "ADMIN_COMMUNICATION_TRANSPORT_SECRET",
                        ),
                    ),
                    timeout_seconds=getattr(
                        settings, "communication_gateway_timeout_seconds", 10.0
                    ),
                    credentials=communication_credentials,
                ),
            )

    hris_provider = ProductionEffectProvider(
        provider_id="provider:administrative-production:odoo-writer",
        name="Administrative Odoo HRIS writer",
        capability=ADMINISTRATIVE_HRIS_EMPLOYEE_CREATE,
        family="odoo",
        execution_domain="odoo:hris",
        credential_configuration_ref="odoo:hris-writer",
        network_domain=_host(settings.odoo_base_url),
        connector=odoo_writer,
    )
    hris_verifier = ProductionReadbackVerifier(
        provider_id="provider:administrative-production:odoo-verifier",
        name="Administrative Odoo HRIS independent verifier",
        effect_capability=ADMINISTRATIVE_HRIS_EMPLOYEE_CREATE,
        family="odoo-readback",
        credential_configuration_ref="odoo:hris-verifier",
        network_domain=_host(settings.odoo_base_url),
        verifier=OdooEmployeeVerifier(odoo_verifier_connector),
    )
    iam_provider = ProductionEffectProvider(
        provider_id="provider:administrative-production:keycloak-writer",
        name="Administrative Keycloak IAM writer",
        capability=IAM_CAPABILITY,
        family="keycloak",
        execution_domain="keycloak:iam",
        credential_configuration_ref="keycloak:iam-writer",
        network_domain=_host(settings.keycloak_base_url),
        connector=keycloak_writer,
    )
    iam_verifier = ProductionReadbackVerifier(
        provider_id="provider:administrative-production:keycloak-verifier",
        name="Administrative Keycloak IAM independent verifier",
        effect_capability=IAM_CAPABILITY,
        family="keycloak-readback",
        credential_configuration_ref="keycloak:iam-verifier",
        network_domain=_host(settings.keycloak_base_url),
        verifier=KeycloakIdentityVerifier(keycloak_verifier_connector),
    )
    hris_deactivate_provider = ProductionEffectProvider(
        provider_id="provider:administrative-production:odoo-deactivate-writer",
        name="Administrative Odoo employee deactivate writer",
        capability=ADMINISTRATIVE_HRIS_EMPLOYEE_DEACTIVATE,
        family="odoo",
        execution_domain="odoo:hris",
        credential_configuration_ref="odoo:hris-writer",
        network_domain=_host(settings.odoo_base_url),
        connector=OdooEmployeeDeactivateConnector(odoo_writer),
        reversibility="irreversible",
    )
    hris_deactivate_verifier = ProductionReadbackVerifier(
        provider_id="provider:administrative-production:odoo-deactivate-verifier",
        name="Administrative Odoo employee deactivate verifier",
        effect_capability=ADMINISTRATIVE_HRIS_EMPLOYEE_DEACTIVATE,
        family="odoo-readback",
        credential_configuration_ref="odoo:hris-verifier",
        network_domain=_host(settings.odoo_base_url),
        verifier=OdooEmployeeDeactivateVerifier(
            OdooEmployeeDeactivateConnector(odoo_verifier_connector)
        ),
    )
    iam_disable_provider = ProductionEffectProvider(
        provider_id="provider:administrative-production:keycloak-disable-writer",
        name="Administrative Keycloak identity disable writer",
        capability=ADMINISTRATIVE_IAM_IDENTITY_DISABLE,
        family="keycloak",
        execution_domain="keycloak:iam",
        credential_configuration_ref="keycloak:iam-writer",
        network_domain=_host(settings.keycloak_base_url),
        connector=KeycloakIdentityDisableConnector(keycloak_writer),
        reversibility="irreversible",
    )
    iam_disable_verifier = ProductionReadbackVerifier(
        provider_id="provider:administrative-production:keycloak-disable-verifier",
        name="Administrative Keycloak identity disable verifier",
        effect_capability=ADMINISTRATIVE_IAM_IDENTITY_DISABLE,
        family="keycloak-readback",
        credential_configuration_ref="keycloak:iam-verifier",
        network_domain=_host(settings.keycloak_base_url),
        verifier=KeycloakIdentityDisableVerifier(keycloak_verifier_connector),
    )
    session_revoke_provider = ProductionEffectProvider(
        provider_id="provider:administrative-production:keycloak-session-revoke-writer",
        name="Administrative Keycloak session revoke writer",
        capability=ADMINISTRATIVE_IAM_SESSIONS_REVOKE,
        family="keycloak",
        execution_domain="keycloak:iam",
        credential_configuration_ref="keycloak:iam-writer",
        network_domain=_host(settings.keycloak_base_url),
        connector=KeycloakSessionRevokeConnector(keycloak_writer),
        reversibility="irreversible",
    )
    session_revoke_verifier = ProductionReadbackVerifier(
        provider_id="provider:administrative-production:keycloak-session-revoke-verifier",
        name="Administrative Keycloak session revoke verifier",
        effect_capability=ADMINISTRATIVE_IAM_SESSIONS_REVOKE,
        family="keycloak-readback",
        credential_configuration_ref="keycloak:iam-verifier",
        network_domain=_host(settings.keycloak_base_url),
        verifier=KeycloakSessionVerifier(keycloak_verifier_connector),
    )
    procurement_draft_provider = ProductionEffectProvider(
        provider_id="provider:administrative-production:odoo-purchase-order-draft-writer",
        name="Administrative Odoo purchase order draft writer",
        capability=ADMINISTRATIVE_ERP_PURCHASE_ORDER_CREATE_DRAFT,
        family="odoo",
        execution_domain="odoo:erp",
        credential_configuration_ref="odoo:erp-writer",
        network_domain=_host(settings.odoo_base_url),
        connector=odoo_financial_writer,
        operation="purchase_order.create_draft",
    )
    procurement_draft_verifier = ProductionReadbackVerifier(
        provider_id="provider:administrative-production:odoo-purchase-order-draft-verifier",
        name="Administrative Odoo purchase order draft verifier",
        effect_capability=ADMINISTRATIVE_ERP_PURCHASE_ORDER_CREATE_DRAFT,
        family="odoo-readback",
        credential_configuration_ref="odoo:erp-verifier",
        network_domain=_host(settings.odoo_base_url),
        verifier=OdooFinancialVerifier(
            odoo_financial_verifier_connector,
            operation="purchase_order.create_draft",
        ),
    )
    procurement_confirm_provider = ProductionEffectProvider(
        provider_id="provider:administrative-production:odoo-purchase-order-confirm-writer",
        name="Administrative Odoo purchase order confirmer",
        capability=ADMINISTRATIVE_ERP_PURCHASE_ORDER_CONFIRM,
        family="odoo",
        execution_domain="odoo:erp",
        credential_configuration_ref="odoo:erp-writer",
        network_domain=_host(settings.odoo_base_url),
        connector=odoo_financial_writer,
        operation="purchase_order.confirm",
        reversibility="irreversible",
    )
    procurement_confirm_verifier = ProductionReadbackVerifier(
        provider_id="provider:administrative-production:odoo-purchase-order-confirm-verifier",
        name="Administrative Odoo purchase order confirmation verifier",
        effect_capability=ADMINISTRATIVE_ERP_PURCHASE_ORDER_CONFIRM,
        family="odoo-readback",
        credential_configuration_ref="odoo:erp-verifier",
        network_domain=_host(settings.odoo_base_url),
        verifier=OdooFinancialVerifier(
            odoo_financial_verifier_connector,
            operation="purchase_order.confirm",
        ),
    )
    vendor_bill_provider = ProductionEffectProvider(
        provider_id="provider:administrative-production:odoo-vendor-bill-draft-writer",
        name="Administrative Odoo vendor bill draft writer",
        capability=ADMINISTRATIVE_ERP_VENDOR_BILL_CREATE_DRAFT,
        family="odoo",
        execution_domain="odoo:erp",
        credential_configuration_ref="odoo:erp-writer",
        network_domain=_host(settings.odoo_base_url),
        connector=odoo_financial_writer,
        operation="vendor_bill.create_draft",
    )
    vendor_bill_verifier = ProductionReadbackVerifier(
        provider_id="provider:administrative-production:odoo-vendor-bill-draft-verifier",
        name="Administrative Odoo vendor bill draft verifier",
        effect_capability=ADMINISTRATIVE_ERP_VENDOR_BILL_CREATE_DRAFT,
        family="odoo-readback",
        credential_configuration_ref="odoo:erp-verifier",
        network_domain=_host(settings.odoo_base_url),
        verifier=OdooFinancialVerifier(
            odoo_financial_verifier_connector,
            operation="vendor_bill.create_draft",
        ),
    )
    expense_provider = ProductionEffectProvider(
        provider_id="provider:administrative-production:odoo-expense-draft-writer",
        name="Administrative Odoo expense draft writer",
        capability=ADMINISTRATIVE_ERP_EXPENSE_REPORT_CREATE,
        family="odoo",
        execution_domain="odoo:erp",
        credential_configuration_ref="odoo:erp-writer",
        network_domain=_host(settings.odoo_base_url),
        connector=odoo_financial_writer,
        operation="expense_report.create",
    )
    expense_verifier = ProductionReadbackVerifier(
        provider_id="provider:administrative-production:odoo-expense-draft-verifier",
        name="Administrative Odoo expense draft verifier",
        effect_capability=ADMINISTRATIVE_ERP_EXPENSE_REPORT_CREATE,
        family="odoo-readback",
        credential_configuration_ref="odoo:erp-verifier",
        network_domain=_host(settings.odoo_base_url),
        verifier=OdooFinancialVerifier(
            odoo_financial_verifier_connector,
            operation="expense_report.create",
        ),
    )


    providers = [
        hris_provider,
        hris_verifier,
        iam_provider,
        iam_verifier,
        hris_deactivate_provider,
        hris_deactivate_verifier,
        iam_disable_provider,
        iam_disable_verifier,
        session_revoke_provider,
        session_revoke_verifier,
        procurement_draft_provider,
        procurement_draft_verifier,
        procurement_confirm_provider,
        procurement_confirm_verifier,
        vendor_bill_provider,
        vendor_bill_verifier,
        expense_provider,
        expense_verifier,
    ]
    if communication_provider is not None and communication_verifier is not None:
        providers.extend([communication_provider, communication_verifier])
    for provider in providers:
        registry.register(provider)

    effect_capabilities = [
        ADMINISTRATIVE_HRIS_EMPLOYEE_CREATE,
        ADMINISTRATIVE_HRIS_EMPLOYEE_DEACTIVATE,
        ADMINISTRATIVE_IAM_IDENTITY_CREATE,
        ADMINISTRATIVE_IAM_IDENTITY_DISABLE,
        ADMINISTRATIVE_IAM_SESSIONS_REVOKE,
        ADMINISTRATIVE_ERP_PURCHASE_ORDER_CREATE_DRAFT,
        ADMINISTRATIVE_ERP_PURCHASE_ORDER_CONFIRM,
        ADMINISTRATIVE_ERP_VENDOR_BILL_CREATE_DRAFT,
        ADMINISTRATIVE_ERP_EXPENSE_REPORT_CREATE,
        ADMINISTRATIVE_COMMUNICATION_MESSAGE_SEND,
    ]
    for capability in effect_capabilities:
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


def _host(url: str) -> str:
    try:
        return httpx.URL(url).host or "unconfigured"
    except Exception:
        return "unconfigured"


__all__ = ["IAM_CAPABILITY", "ProductionEffectProvider", "ProductionReadbackVerifier", "build"]
