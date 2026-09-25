from pathlib import Path

DBOS_ALLOWED = {
    Path("src/administrative_orchestrator/worker.py"),
    Path("src/administrative_orchestrator/workflows/bootstrap.py"),
    Path("src/administrative_orchestrator/workflows/definitions.py"),
    Path("src/administrative_orchestrator/workflows/relay.py"),
}

DOMAIN_CORE_MODULES = {
    Path("src/administrative_orchestrator/domain.py"),
    Path("src/administrative_orchestrator/policy.py"),
    Path("src/administrative_orchestrator/authority.py"),
    Path("src/administrative_orchestrator/financial.py"),
    Path("src/administrative_orchestrator/commitment_models.py"),
    Path("src/administrative_orchestrator/completion.py"),
}

FORBIDDEN_DOMAIN_IMPORTS = (
    "from .integrations",
    "from administrative_orchestrator.integrations",
    "from .providers",
    "from administrative_orchestrator.providers",
    "from .workflows",
    "from administrative_orchestrator.workflows",
    "from dbos import",
    "import dbos",
)

LEGACY_RAW_EXECUTION_CALLS = (
    ".append_realization(",
    ".append_outcome(",
)


def test_dbos_imports_stay_at_durable_orchestration_boundary() -> None:
    root = Path("src/administrative_orchestrator")
    violations: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if ("from dbos import" in text or "import dbos" in text) and path not in DBOS_ALLOWED:
            violations.append(str(path))
    assert violations == []


def test_domain_core_does_not_import_transport_or_orchestration_layers() -> None:
    violations: list[str] = []
    for path in DOMAIN_CORE_MODULES:
        text = path.read_text(encoding="utf-8")
        for snippet in FORBIDDEN_DOMAIN_IMPORTS:
            if snippet in text:
                violations.append(f"{path}: {snippet}")
    assert violations == []


def test_runtime_code_does_not_use_legacy_raw_execution_persistence() -> None:
    """Keep realization/outcome writes behind ExecutionRepository invariants."""
    root = Path("src/administrative_orchestrator")
    violations: list[str] = []
    for path in root.rglob("*.py"):
        if path == Path("src/administrative_orchestrator/persistence.py"):
            continue
        text = path.read_text(encoding="utf-8")
        for call in LEGACY_RAW_EXECUTION_CALLS:
            if call in text:
                violations.append(f"{path}: {call}")
    assert violations == []
