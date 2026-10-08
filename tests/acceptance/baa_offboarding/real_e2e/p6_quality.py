"""P6 isolated E2E quality measurement, not a production SLO.

The recorder sees only coarse operation labels, a monotonic duration, and a
closed-set status. It never includes subject IDs, OAuth tokens, provider
payloads, response bodies or exception text. Recording does not change
admission, execution, read-back, or reconciliation decisions.

This is a *small-sample* instrument. Tail percentiles are descriptive only
and cannot establish production P95/P99 or reliable failure rates.
"""
from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

KNOWN_OPERATIONS = frozenset({
    "identity.disable",
    "sessions.revoke",
    "employee.deactivate",
})
STAGES = frozenset({
    "engine_drive",
    "gate_execute_including_admission_dispatch_readback",
    "gate_observe_including_independent_readback",
})
RESULTS = frozenset({
    "succeeded",
    "failed",
    "outcome_unknown",
    "deferred",
    "available",
    "unavailable",
    "unknown",
    "not_applicable",
    "exception",
})


@dataclass(frozen=True)
class StageObservation:
    stage: str
    operation: str
    duration_ns: int
    result: str
    exception_class: str | None = None

    def __post_init__(self) -> None:
        if self.stage not in STAGES:
            raise ValueError("unknown stage")
        if self.operation not in KNOWN_OPERATIONS | {"none", "other"}:
            raise ValueError("non-allowlisted operation")
        if self.duration_ns < 0:
            raise ValueError("negative monotonic duration")
        if self.result not in RESULTS:
            raise ValueError("non-allowlisted result")


def _clean_operation(operation: object) -> str:
    return operation if isinstance(operation, str) and operation in KNOWN_OPERATIONS else "other"


def _clean_result(value: object) -> str:
    raw = getattr(value, "value", value)
    return raw if isinstance(raw, str) and raw in RESULTS else "not_applicable"


def _percentile(sorted_values: list[float], rank: float) -> float | None:
    if not sorted_values:
        return None
    pos = (len(sorted_values) - 1) * rank
    left, right = math.floor(pos), math.ceil(pos)
    return round(
        sorted_values[left] + (sorted_values[right] - sorted_values[left]) * (pos - left),
        6,
    )


class QualityRecorder:
    def __init__(
        self,
        *,
        max_observations: int = 4096,
        clock_ns: Callable[[], int] = time.perf_counter_ns,
    ) -> None:
        if max_observations < 1:
            raise ValueError("max_observations must be positive")
        self.clock_ns = clock_ns
        self.max_observations = max_observations
        self._observations: list[StageObservation] = []
        self._overflow = 0
        self._lock = threading.Lock()

    def measure(
        self,
        stage: str,
        operation: str,
        action: Callable[[], Any],
        *,
        status_from: Callable[[Any], object] | None = None,
    ) -> Any:
        if stage not in STAGES:
            raise ValueError("invalid stage")
        safe_operation = "none" if stage == "engine_drive" else _clean_operation(operation)
        start = self.clock_ns()
        result = "not_applicable"
        exc_class: str | None = None
        try:
            value = action()
            if status_from is not None:
                result = _clean_result(status_from(value))
            return value
        except Exception as exc:
            result = "exception"
            exc_class = type(exc).__name__
            raise
        finally:
            elapsed = self.clock_ns() - start
            # Monotonic clocks should not go backwards. If the test clock is
            # invalid, preserve a counterexample instead of recording zero.
            if elapsed < 0:
                raise RuntimeError("nonmonotonic quality clock")
            entry = StageObservation(
                stage=stage,
                operation=safe_operation,
                duration_ns=elapsed,
                result=result,
                exception_class=exc_class,
            )
            with self._lock:
                if len(self._observations) < self.max_observations:
                    self._observations.append(entry)
                else:
                    self._overflow += 1

    def report(self, *, scenario: str) -> dict[str, Any]:
        with self._lock:
            observations = tuple(self._observations)
            overflow = self._overflow
        groups: dict[str, list[StageObservation]] = {}
        for item in observations:
            groups.setdefault(item.stage, []).append(item)
        summaries: dict[str, dict[str, Any]] = {}
        for stage in sorted(STAGES):
            values = sorted(i.duration_ns / 1_000_000 for i in groups.get(stage, []))
            n = len(values)
            summaries[stage] = {
                "n": n,
                "min_ms": round(values[0], 6) if n else None,
                "p50_ms": _percentile(values, 0.50),
                "p95_ms": _percentile(values, 0.95),
                "p99_ms": _percentile(values, 0.99),
                "max_ms": round(values[-1], 6) if n else None,
                "percentiles_are_descriptive_only": True,
                "tail_latency_qualified": False,
                "result_counts": {
                    status: sum(i.result == status for i in groups.get(stage, []))
                    for status in sorted({i.result for i in groups.get(stage, [])})
                },
            }
        return {
            "schema": "aios-baa-isolated-quality-v1",
            "scenario": scenario if scenario in {
                "normal", "lost_ack", "readback_outage", "runtime_bypass"
            } else "other",
            "measurement": "process-local monotonic elapsed time",
            "units": {"duration_ns": "ns", "summary_latency": "ms"},
            "scope": "ephemeral real-product E2E per-case observations",
            "workload_model": "one isolated offboarding case / test scenario; not a load model",
            "sample_count": len(observations),
            "overflow_count": overflow,
            "instrument_complete": overflow == 0,
            "slo_pre_registered": False,
            "percentiles_establish_production_slo": False,
            "human_attention_measured": False,
            "assurance_labor_measured": False,
            "separate_admission_latency_measured": False,
            "stage_summaries": summaries,
            "records": [
                {
                    "stage": item.stage,
                    "operation": item.operation,
                    "duration_ns": item.duration_ns,
                    "result": item.result,
                    "exception_class": item.exception_class,
                }
                for item in observations
            ],
        }

    def write(self, path: Path, *, scenario: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.report(scenario=scenario), sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )


class TimedEffectProvider:
    """Opaque delegation wrapper: preserve provider return values and errors."""

    def __init__(self, provider: Any, recorder: QualityRecorder) -> None:
        self.provider = provider
        self.recorder = recorder

    def execute(self, effect: Any, payload: dict[str, Any]) -> Any:
        return self.recorder.measure(
            "gate_execute_including_admission_dispatch_readback",
            getattr(effect, "operation", ""),
            lambda: self.provider.execute(effect, payload),
            status_from=lambda response: getattr(response, "status", None),
        )

    def observe(self, effect: Any) -> Any:
        return self.recorder.measure(
            "gate_observe_including_independent_readback",
            getattr(effect, "operation", ""),
            lambda: self.provider.observe(effect),
            status_from=lambda response: getattr(response, "availability", None),
        )


__all__ = ["QualityRecorder", "StageObservation", "TimedEffectProvider"]
