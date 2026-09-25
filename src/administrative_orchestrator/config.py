from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ADMIN_", extra="ignore")

    database_url: str = "sqlite+pysqlite:///:memory:"
    worker_database_url: str | None = None
    dbos_system_database_url: str | None = None
    sandbox_database_url: str = "sqlite+pysqlite:///:memory:"
    sandbox_base_url: str = "http://127.0.0.1:8010"
    provider_timeout_seconds: float = 10.0
    worker_poll_seconds: float = 1.0
    outbox_batch: int = 20
    outbox_lease_seconds: int = 30
    outbox_max_attempts: int = 10
    log_level: str = "INFO"
    external_effects_enabled: bool = False
    auto_create_schema: bool = True

    intake_artifact_root: str = ""
    # Outbound communication uses a provider-neutral transport contract.
    communication_gateway_base_url: str = ""
    communication_transport_secret: SecretStr | None = None
    communication_transport_secret_file: str = ""
    communication_transport_secret_env: str = "ADMIN_COMMUNICATION_TRANSPORT_SECRET"
    communication_gateway_timeout_seconds: float = 10.0
    intake_model_url: str = ""
    intake_model_api_key: SecretStr | None = None
    intake_model_protocol: Literal["json", "openai-chat", "openai-responses"] = "json"
    intake_model_name: str = ""
    intake_model_max_tokens: int = 2400
    intake_model_provider: str = "configured-model-gateway"
    intake_model_identity: str = "configured-model"
    intake_model_version: str = "configured"
    intake_model_profile_ref: str = "candidate-intake-v1"
    intake_model_schema_ref: str = "candidate-interpretation-v1"
    # Optional advisory-only investigation adapter.  A blank URL keeps the
    # Administrative deployment available while investigation remains
    # fail-closed and records the advisory failure.
    investigation_client_url: str = ""
    investigation_client_timeout_seconds: float = 10.0
    investigation_client_api_key: SecretStr | None = None
    investigation_client_api_key_file: str = ""
    investigation_model_url: str = ""
    # Direct model routing, when enabled, has its own credential owner. It is
    # never populated from the advisory-service credential above.
    investigation_model_api_key: SecretStr | None = None
    investigation_model_api_key_file: str = ""
    investigation_model_protocol: Literal["openai-chat", "openai-responses"] = "openai-chat"
    investigation_model_name: str = ""
    investigation_model_max_tokens: int = 2000
    investigation_model_provider: str = "configured-model-gateway"
    investigation_model_version: str = "configured"
    investigation_model_prompt_ref: str = "adaptive-investigation-v1"
    intake_model_instruction: str = (
        "Extract a candidate administrative intent and candidate facts only. "
        "Never authorize, execute, or communicate on behalf of the system. "
        "For document-driven M8 work, use only these candidate intent values: "
        "procurement-request, invoice-ap-preparation, expense-reimbursement, or unknown. "
        "For procurement-request documents, use only these additional candidate fact keys: "
        "description, requested_quantity, estimated_amount, candidate_vendor, vendor_ref, "
        "vendor_tax_id, cost_center, needed_by, quote_ref. "
        "For invoice-ap-preparation documents, use only these additional candidate fact keys: "
        "vendor_name, vendor_ref, vendor_tax_id, invoice_number, invoice_date, total, "
        "po_number, line_items, document_revision, document_digest. "
        "For expense-reimbursement documents, use only these additional candidate fact keys: "
        "employee_ref, merchant, expense_date, amount, category, business_purpose, receipt_ref. "
        "For monetary values use an object with amount as a decimal string and currency as a "
        "three-letter code; never use binary floating point. For quantities use decimal strings. "
        "Use evidence_span_refs only from the evidence catalog included in the source text. "
        "Candidate facts are claims, never authoritative facts. "
        "For employee-onboarding requests, use only these candidate fact keys: "
        "employee_ref, department_ref, manager_principal_id, start_date, "
        "employment_type, requested_systems, requires_privileged_access. "
        "For employee-offboarding requests, use only these additional candidate "
        "fact keys: requested_termination_date, reason, successor_principal_id. "
        "Put every requested account or system into requested_systems. "
        "Do not invent other fact keys."
    )

    runtime_profile: Literal["test", "development", "governed", "staging", "production"] = "development"

    # The Administrative domain keeps business truth and verification. World Runtime
    # owns generic persistent responsibility, authorization and physical invocation.
    world_runtime_mode: Literal["disabled", "cutover"] = "disabled"
    world_runtime_base_url: str = "http://127.0.0.1:8020"
    world_runtime_timeout_seconds: float = 3.0
    world_runtime_principal: str = "service:administrative-orchestrator"
    world_runtime_bearer_token: SecretStr | None = None
    world_runtime_delegation_id: str = ""

    # Authentication. `jwt` is retained only for compatibility/test fixtures;
    # the production profile requires OIDC/JWKS and asymmetric verification.
    auth_mode: Literal["development", "jwt", "oidc"] = "jwt"
    jwt_secret: str | None = None
    jwt_issuer: str = "administrative-orchestrator"
    jwt_audience: str = "administrative-orchestrator"

    oidc_issuer: str = ""
    oidc_audience: str = "administrative-orchestrator"
    oidc_allowed_algorithms: str = "RS256,ES256"
    # Optional service-network endpoints for an externally issued OIDC token.
    # The issuer remains the authoritative external identity provider URL;
    # these endpoints only avoid a broken container-to-host backchannel.
    oidc_metadata_url: str = ""
    oidc_jwks_url: str = ""
    oidc_jwks_cache_ttl_seconds: int = 300
    oidc_clock_skew_seconds: int = 60
    oidc_http_timeout_seconds: float = 5.0
    oidc_allow_insecure_http: bool = False

    # Authoritative read adapters. Credentials are referenced by environment
    # variable name and resolved only inside connector processes; secret values
    # are never persisted in domain or Kernel records.
    hris_source_kind: Literal["disabled", "odoo"] = "disabled"
    odoo_base_url: str = ""
    odoo_database: str = ""
    odoo_reader_username: str = ""
    odoo_reader_secret_env: str = "ADMIN_ODOO_READER_SECRET"
    odoo_writer_username: str = ""
    odoo_writer_secret_env: str = "ADMIN_ODOO_WRITER_SECRET"
    odoo_verifier_username: str = ""
    odoo_verifier_secret_env: str = "ADMIN_ODOO_VERIFIER_SECRET"
    odoo_financial_writer_username: str = ""
    odoo_financial_writer_secret_env: str = "ADMIN_ODOO_FINANCIAL_WRITER_SECRET"
    odoo_financial_verifier_username: str = ""
    odoo_financial_verifier_secret_env: str = "ADMIN_ODOO_FINANCIAL_VERIFIER_SECRET"
    odoo_request_ref_field: str = "x_administrative_request_ref"
    odoo_deactivate_request_ref_field: str = (
        "x_administrative_deactivate_request_ref"
    )
    odoo_termination_status_field: str = "x_administrative_termination_status"
    odoo_termination_effective_at_field: str = (
        "x_administrative_termination_effective_at"
    )
    odoo_employment_episode_field: str = "x_administrative_employment_episode_ref"
    odoo_principal_id_field: str = "x_administrative_principal_id"
    odoo_transaction_request_ref_field: str = "x_administrative_transaction_request_ref"
    odoo_transaction_confirm_request_ref_field: str = (
        "x_administrative_transaction_confirm_request_ref"
    )
    odoo_transaction_subject_ref_field: str = "x_administrative_transaction_subject_ref"
    odoo_transaction_payload_field: str = "x_administrative_m8_payload_json"

    iam_source_kind: Literal["disabled", "keycloak"] = "disabled"
    keycloak_base_url: str = ""
    keycloak_realm: str = ""
    keycloak_reader_client_id: str = ""
    keycloak_reader_secret_env: str = "ADMIN_KEYCLOAK_READER_SECRET"
    keycloak_writer_client_id: str = ""
    keycloak_writer_secret_env: str = "ADMIN_KEYCLOAK_WRITER_SECRET"
    keycloak_verifier_client_id: str = ""
    keycloak_verifier_secret_env: str = "ADMIN_KEYCLOAK_VERIFIER_SECRET"
    keycloak_request_ref_attribute: str = "administrative_request_ref"
    keycloak_disable_request_ref_attribute: str = (
        "administrative_disable_request_ref"
    )
    keycloak_session_revoke_request_ref_attribute: str = (
        "administrative_session_revoke_request_ref"
    )

    connector_timeout_seconds: float = 10.0
    authoritative_fact_max_age_seconds: int = 300

    # Compatibility switch for tests/development. Governed/production profiles
    # always force authority enforcement on.
    authority_enforcement_enabled: bool = False

    # One-shot bootstrap input used only by the foundation bootstrap command.
    bootstrap_authority_json: str = ""

    @property
    def oidc_algorithms(self) -> tuple[str, ...]:
        return tuple(item.strip() for item in self.oidc_allowed_algorithms.split(",") if item.strip())

    @model_validator(mode="after")
    def fail_closed_profiles(self) -> Settings:
        if self.runtime_profile in {"governed", "staging", "production"}:
            object.__setattr__(self, "authority_enforcement_enabled", True)
        if self.world_runtime_timeout_seconds <= 0:
            raise ValueError("world_runtime_timeout_seconds must be positive")
        if self.connector_timeout_seconds <= 0:
            raise ValueError("connector_timeout_seconds must be positive")
        if self.communication_gateway_timeout_seconds <= 0:
            raise ValueError("communication_gateway_timeout_seconds must be positive")
        if self.investigation_client_timeout_seconds <= 0:
            raise ValueError("investigation_client_timeout_seconds must be positive")
        if self.investigation_model_max_tokens <= 0:
            raise ValueError("investigation_model_max_tokens must be positive")
        if self.authoritative_fact_max_age_seconds <= 0:
            raise ValueError("authoritative_fact_max_age_seconds must be positive")
        if self.intake_model_max_tokens <= 0:
            raise ValueError("intake_model_max_tokens must be positive")
        if self.runtime_profile in {"staging", "production"}:
            if self.auth_mode != "oidc":
                raise ValueError(f"{self.runtime_profile} runtime requires ADMIN_AUTH_MODE=oidc")
            if not self.oidc_issuer.strip() or not self.oidc_audience.strip():
                raise ValueError(f"{self.runtime_profile} OIDC issuer and audience are required")
            if self.runtime_profile == "production" and not self.oidc_issuer.startswith("https://"):
                raise ValueError("production OIDC issuer must use HTTPS")
            if self.runtime_profile == "production" and self.oidc_allow_insecure_http:
                raise ValueError("production OIDC cannot allow insecure HTTP")
            if self.oidc_issuer.startswith("http://") and not self.oidc_allow_insecure_http:
                raise ValueError(
                    f"{self.runtime_profile} OIDC HTTP requires ADMIN_OIDC_ALLOW_INSECURE_HTTP=true"
                )
            disallowed = set(self.oidc_algorithms) - {"RS256", "ES256"}
            if disallowed or not self.oidc_algorithms:
                raise ValueError("production OIDC algorithms are restricted to RS256/ES256")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
