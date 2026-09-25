from pathlib import Path

ADMIN_SRC = Path("src/domains/administrative_orchestrator")

DBOS_ALLOWED = {
    ADMIN_SRC / "worker.py",
    ADMIN_SRC / "workflows/bootstrap.py",
    ADMIN_SRC / "workflows/definitions.py",
    ADMIN_SRC / "workflows/relay.py",
}

DOMAIN_CORE_MODULES = {
    ADMIN_SRC / "domain.py",
    ADMIN_SRC / "policy.py",
    ADMIN_SRC / "authority.py",
    ADMIN_SRC / "financial.py",
    ADMIN_SRC / "commitment_models.py",
    ADMIN_SRC / "completion.py",
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
    violations: list[str] = []
    for path in ADMIN_SRC.rglob("*.py"):
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
    violations: list[str] = []
    for path in ADMIN_SRC.rglob("*.py"):
        if path == ADMIN_SRC / "persistence.py":
            continue
        text = path.read_text(encoding="utf-8")
        for call in LEGACY_RAW_EXECUTION_CALLS:
            if call in text:
                violations.append(f"{path}: {call}")
    assert violations == []
