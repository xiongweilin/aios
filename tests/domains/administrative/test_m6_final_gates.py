from __future__ import annotations

import ast
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src" / "administrative_orchestrator"
_FORBIDDEN_MODEL_FIELDS = {
    "authority",
    "approval_satisfaction",
    "decision",
    "execution_grant",
    "kernel_work",
    "tool_calls",
}
_FORBIDDEN_CALL_NAMES = {
    "AdministrativeCase",
    "AdministrativeExecutionGrant",
    "AdministrativeRequest",
    "ApprovalSatisfaction",
    "Decision",
    "ExecutionAuthorization",
    "FactAssertion",
    "FactSnapshot",
    "KernelShadowProjection",
    "KernelWorkAdmissionReceipt",
    "create_case",
    "derive_effect_intent",
    "derive_execution_grant",
    "mint_execution_authorization",
    "mint_execution_authorization_from_approval",
    "project_to_kernel",
    "record_decision",
    "replace_facts_and_apply_policy",
}
_FORBIDDEN_IMPORT_SUFFIXES = {
    "integrations.kernel",
    "onboarding_execution",
    "unit_of_work",
    "workflows",
}
















def test_candidate_intake_modules_do_not_call_formal_authority_or_kernel_symbols() -> None:
    paths = sorted((_SOURCE_ROOT / "intake").rglob("*.py"))
    violations: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else None
                )
                if name in _FORBIDDEN_CALL_NAMES:
                    violations.append(f"{path}:{node.lineno}: forbidden call {name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if any(
                    node.module.endswith(suffix) or f".{suffix}." in node.module
                    for suffix in _FORBIDDEN_IMPORT_SUFFIXES
                ):
                    violations.append(f"{path}:{node.lineno}: forbidden import {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if any(
                        alias.name.endswith(suffix) or f".{suffix}." in alias.name
                        for suffix in _FORBIDDEN_IMPORT_SUFFIXES
                    ):
                        violations.append(f"{path}:{node.lineno}: forbidden import {alias.name}")
    assert violations == []

def test_production_worker_uses_provider_neutral_intake_configuration() -> None:
    compose = (_REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")
    production_env = (_REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8")
    worker_block = compose.split("  administrative-worker:\n", maxsplit=1)[1].split(
        "\n  autodev-migrate:", maxsplit=1
    )[0]
    assert "<<: *administrative-environment" in worker_block
    assert "ADMIN_INTAKE_ARTIFACT_ROOT:" in compose
    assert "ADMIN_INTAKE_MODEL_URL:" in compose
    assert "ADMIN_INTAKE_ARTIFACT_ROOT=" in production_env
    assert "ADMIN_INTAKE_MODEL_API_KEY=" in production_env
