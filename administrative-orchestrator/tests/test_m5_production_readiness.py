from __future__ import annotations

import httpx
import pytest

from administrative_orchestrator.config import Settings
from administrative_orchestrator.integrations.runtime_capabilities import (
    WORLD_RUNTIME_EFFECT_CAPABILITIES,
)
from administrative_orchestrator.production_readiness import (
    ProductionReadinessError,
    validate_production_connector_isolation,
    validate_production_control_plane,
    validate_world_runtime_compatibility,
)


def _production_settings(**overrides) -> Settings:
    values = {
        "runtime_profile": "production",
        "auth_mode": "oidc",
        "oidc_issuer": "https://idp.example.test",
        "oidc_audience": "administrative-orchestrator",
        "database_url": "postgresql+psycopg://admin:secret@db/admin",
        "worker_database_url": "postgresql+psycopg://worker:secret@db/admin",
        "dbos_system_database_url": "postgresql+psycopg://dbos:secret@db/admin_dbos",
        "auto_create_schema": False,
        "external_effects_enabled": True,
        "world_runtime_mode": "cutover",
        "world_runtime_base_url": "http://world-runtime:8020",
        "hris_source_kind": "odoo",
        "odoo_base_url": "https://odoo.example.test",
        "odoo_database": "company",
        "odoo_reader_username": "admin-reader",
        "odoo_writer_username": "runtime-writer",
        "odoo_verifier_username": "runtime-verifier",
        "odoo_reader_secret_env": "ADMIN_ODOO_READER_SECRET",
        "odoo_writer_secret_env": "ADMIN_ODOO_WRITER_SECRET",
        "odoo_verifier_secret_env": "ADMIN_ODOO_VERIFIER_SECRET",
        "odoo_financial_writer_username": "financial-writer",
        "odoo_financial_verifier_username": "financial-verifier",
        "odoo_financial_writer_secret_env": "ADMIN_ODOO_FINANCIAL_WRITER_SECRET",
        "odoo_financial_verifier_secret_env": "ADMIN_ODOO_FINANCIAL_VERIFIER_SECRET",
        "iam_source_kind": "keycloak",
        "keycloak_base_url": "https://keycloak.example.test",
        "keycloak_realm": "company",
        "keycloak_reader_client_id": "admin-reader",
        "keycloak_writer_client_id": "runtime-writer",
        "keycloak_verifier_client_id": "runtime-verifier",
        "keycloak_reader_secret_env": "ADMIN_KEYCLOAK_READER_SECRET",
        "keycloak_writer_secret_env": "ADMIN_KEYCLOAK_WRITER_SECRET",
        "keycloak_verifier_secret_env": "ADMIN_KEYCLOAK_VERIFIER_SECRET",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_readiness_accepts_runtime_cutover_with_isolated_connectors():
    settings = _production_settings()
    validate_production_control_plane(settings)
    validate_production_connector_isolation(settings)


def test_production_control_plane_rejects_non_cutover_or_sqlite():
    with pytest.raises(ProductionReadinessError, match="World Runtime cutover mode"):
        validate_production_control_plane(
            _production_settings(world_runtime_mode="disabled")
        )
    with pytest.raises(ProductionReadinessError, match="ADMIN_DATABASE_URL must use PostgreSQL"):
        validate_production_control_plane(
            _production_settings(database_url="sqlite:///admin.db")
        )


def test_world_runtime_compatibility_requires_all_effect_rules(monkeypatch):
    settings = _production_settings()
    rules = [{"capability": item} for item in sorted(WORLD_RUNTIME_EFFECT_CAPABILITIES)]

    def ok(*args, **kwargs):
        del args, kwargs
        return httpx.Response(
            200,
            json={"runtime_id": "runtime:test", "effect_rules": rules},
            request=httpx.Request("GET", settings.world_runtime_base_url),
        )

    monkeypatch.setattr(httpx, "get", ok)
    payload = validate_world_runtime_compatibility(settings)
    assert payload["runtime_id"] == "runtime:test"

    missing = rules[:-1]

    def incomplete(*args, **kwargs):
        del args, kwargs
        return httpx.Response(
            200,
            json={"runtime_id": "runtime:test", "effect_rules": missing},
            request=httpx.Request("GET", settings.world_runtime_base_url),
        )

    monkeypatch.setattr(httpx, "get", incomplete)
    with pytest.raises(ProductionReadinessError, match="missing required"):
        validate_world_runtime_compatibility(settings)


def test_production_connector_isolation_rejects_shared_writer_verifier_identity():
    with pytest.raises(ProductionReadinessError, match="Odoo writer and verifier identities"):
        validate_production_connector_isolation(
            _production_settings(odoo_verifier_username="runtime-writer")
        )
    with pytest.raises(ProductionReadinessError, match="Keycloak writer and verifier identities"):
        validate_production_connector_isolation(
            _production_settings(keycloak_verifier_client_id="runtime-writer")
        )
    with pytest.raises(
        ProductionReadinessError,
        match="Odoo financial writer and verifier identities",
    ):
        validate_production_connector_isolation(
            _production_settings(odoo_financial_verifier_username="financial-writer")
        )


def test_production_connector_isolation_rejects_shared_secret_reference():
    with pytest.raises(ProductionReadinessError, match="Odoo writer and verifier secret references"):
        validate_production_connector_isolation(
            _production_settings(odoo_verifier_secret_env="ADMIN_ODOO_WRITER_SECRET")
        )
    with pytest.raises(
        ProductionReadinessError,
        match="Keycloak writer and verifier secret references",
    ):
        validate_production_connector_isolation(
            _production_settings(
                keycloak_verifier_secret_env="ADMIN_KEYCLOAK_WRITER_SECRET"
            )
        )
    with pytest.raises(
        ProductionReadinessError,
        match="Odoo financial writer and verifier secret references",
    ):
        validate_production_connector_isolation(
            _production_settings(
                odoo_financial_verifier_secret_env="ADMIN_ODOO_FINANCIAL_WRITER_SECRET"
            )
        )
