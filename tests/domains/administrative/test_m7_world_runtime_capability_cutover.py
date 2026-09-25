from __future__ import annotations

import scripts.production_world_runtime_stack as stack
from administrative_orchestrator.config import Settings
from administrative_orchestrator.integrations.runtime_capabilities import (
    WORLD_RUNTIME_EFFECT_CAPABILITIES,
)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        runtime_profile="staging",
        auth_mode="oidc",
        oidc_issuer="https://issuer.example.test",
        oidc_audience="administrative-orchestrator",
        world_runtime_mode="cutover",
        odoo_base_url="https://odoo.example.test",
        odoo_database="company",
        odoo_writer_username="writer",
        odoo_verifier_username="verifier",
        odoo_financial_writer_username="financial-writer",
        odoo_financial_verifier_username="financial-verifier",
        keycloak_base_url="https://keycloak.example.test",
        keycloak_realm="company",
        keycloak_writer_client_id="writer",
        keycloak_verifier_client_id="verifier",
        communication_gateway_base_url="",
    )


def test_production_runtime_registers_all_administrative_effect_rules(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(stack, "get_settings", _settings)
    monkeypatch.setenv(
        "WORLD_RUNTIME_ADMIN_PRODUCTION_STATE_PATH",
        str(tmp_path / "runtime.db"),
    )

    runtime = stack.build()
    rules = {
        rule.capability: rule
        for rule in runtime.contract_registry.list_effect_rules()
    }
    assert set(rules) == set(WORLD_RUNTIME_EFFECT_CAPABILITIES)
    for capability in WORLD_RUNTIME_EFFECT_CAPABILITIES:
        rule = rules[capability]
        assert rule.authorization_required is True
        assert rule.resource_required is True
        assert rule.version_required is True
        writers = [
            item
            for item in runtime.registry.list()
            if capability in item.capabilities
        ]
        if capability == "administrative.communication.message.send.v1":
            assert len(writers) in {0, 1}
        else:
            assert len(writers) == 1


def test_runtime_stack_source_has_no_agent_kernel_dependency() -> None:
    source = __import__("inspect").getsource(stack)
    assert "agent_kernel" not in source
    assert "AGENT_KERNEL" not in source
