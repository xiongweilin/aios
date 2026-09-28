from __future__ import annotations

from typing import Any, Callable

from .conformance_agency import CHECKS as AGENCY_CHECKS
from .conformance_authority import CHECKS as AUTHORITY_CHECKS
from .conformance_continuity import CHECKS as CONTINUITY_CHECKS
from .conformance_execution import CHECKS as EXECUTION_CHECKS
from .conformance_support import (
    SUITE_VERSION,
    ConformanceResult,
    conformance_vectors,
)


CHECKS: dict[str, Callable[[], Any]] = {
    **AUTHORITY_CHECKS,
    **EXECUTION_CHECKS,
    **CONTINUITY_CHECKS,
    **AGENCY_CHECKS,
}


async def run_reference_conformance() -> tuple[ConformanceResult, ...]:
    results: list[ConformanceResult] = []
    for vector in conformance_vectors()["vectors"]:
        vector_id = str(vector["id"])
        try:
            outcome = CHECKS[vector_id]()
            if hasattr(outcome, "__await__"):
                await outcome
        except Exception as exc:
            results.append(ConformanceResult(vector_id, False, str(exc)))
        else:
            results.append(ConformanceResult(vector_id, True))
    return tuple(results)


__all__ = [
    "CHECKS",
    "ConformanceResult",
    "SUITE_VERSION",
    "conformance_vectors",
    "run_reference_conformance",
]
