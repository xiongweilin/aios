"""P3 prospective protected-resource access timeline, instrument-only.

An independently scheduled, read-only probe loop. Records request-time
envelopes and explicit UNKNOWN values, not transition/event times.

Even dense probes cannot establish interval-continuous authorization or an
exact subject-second outcome without additional qualified event/clock
assumptions. The candidate cutover bracket assumes a single monotone ALLOW ->
DENY transition; the assumption is NOT verified by this sampler.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from baa_protocol.temporal_outcome import AccessProbe


@dataclass(frozen=True)
class ProbeTarget:
    label: str
    read_access: Callable[[], AccessProbe]


@dataclass(frozen=True)
class ProbeRecord:
    label: str
    phase: str
    sequence: int
    mono_start_ns: int
    mono_end_ns: int
    wall_start_ns: int
    wall_end_ns: int
    access: AccessProbe
    error_type: str | None = None

    def __post_init__(self) -> None:
        if self.mono_end_ns < self.mono_start_ns:
            raise ValueError("monotonic clock moved backwards")
        if self.wall_end_ns < self.wall_start_ns:
            raise ValueError("wall clock moved backwards within probe envelope")

    def public_dict(self) -> dict[str, object]:
        return {
            "subject_label": self.label,
            "phase": self.phase,
            "sequence": self.sequence,
            "mono_start_ns": self.mono_start_ns,
            "mono_end_ns": self.mono_end_ns,
            "wall_start_ns": self.wall_start_ns,
            "wall_end_ns": self.wall_end_ns,
            "access": self.access.value,
            "error_type": self.error_type,
        }


def access_cutover_candidate(
    records: tuple[ProbeRecord, ...], label: str
) -> dict[str, object]:
    """A candidate bracket in LOCAL monotonic nanoseconds; NOT proof of cutover.

    The bracket is deliberately wide enough to include both request
    envelopes. UNKNOWN readings are never interpolated. Reverse transitions
    are reported, not smoothed away.
    """
    relevant = sorted(
        (r for r in records if r.label == label),
        key=lambda r: r.sequence,
    )
    last_allow: ProbeRecord | None = None
    first_deny: ProbeRecord | None = None
    reversals = 0
    previous_known: AccessProbe | None = None
    unknown = 0

    for entry in relevant:
        if entry.access is AccessProbe.UNKNOWN:
            unknown += 1
            continue
        if (
            previous_known is AccessProbe.DENY
            and entry.access is AccessProbe.ALLOW
        ):
            reversals += 1
        previous_known = entry.access
        if first_deny is None:
            if entry.access is AccessProbe.ALLOW:
                last_allow = entry
            elif entry.access is AccessProbe.DENY and last_allow is not None:
                first_deny = entry

    candidate = None
    if last_allow is not None and first_deny is not None:
        candidate = {
            "earliest_monotonic_ns": last_allow.mono_start_ns,
            "latest_monotonic_ns": first_deny.mono_end_ns,
            "width_seconds": (
                first_deny.mono_end_ns - last_allow.mono_start_ns
            ) / 1_000_000_000,
            "left_sample_sequence": last_allow.sequence,
            "right_sample_sequence": first_deny.sequence,
        }
    return {
        "subject_label": label,
        "sample_count": len(relevant),
        "unknown_count": unknown,
        "observed_deny_to_allow_reversals": reversals,
        "candidate_single_change_bracket": candidate,
        "single_change_assumption_qualified": False,
        "continuous_outcome_identified": False,
    }


class AccessTimelineSampler:
    """Monotonic timestamped independent loop with bounded memory and cleanup.

    Thread is separate from the AIOS driver; it shares only immutable bearer
    strings already kept in process memory. The runner never stores tokens in
    records, prints exceptions, or accepts unknown as access denial.
    """

    def __init__(
        self,
        targets: tuple[ProbeTarget, ...],
        *,
        interval_s: float = 0.15,
        max_rounds: int = 256,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        wall_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        if not targets or len({t.label for t in targets}) != len(targets):
            raise ValueError("targets must have unique nonempty labels")
        if any(not t.label.strip() for t in targets):
            raise ValueError("empty subject label")
        if interval_s < 0.01 or max_rounds < 2:
            raise ValueError("invalid polling cadence or bounded capacity")
        self.targets = targets
        self.interval_s = interval_s
        self.max_rounds = max_rounds
        self._mono = monotonic_ns
        self._wall = wall_ns
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._records: list[ProbeRecord] = []
        self._rounds = 0
        self._capacity_reached = False

    def capture_once(self, phase: str = "manual") -> tuple[ProbeRecord, ...]:
        """Capture one complete round. Intended for tests and preflight."""
        with self._lock:
            if self._rounds >= self.max_rounds:
                self._capacity_reached = True
                return ()
            self._rounds += 1
            sequence = self._rounds
        entries: list[ProbeRecord] = []
        for target in self.targets:
            mono_start = self._mono()
            wall_start = self._wall()
            failure: str | None = None
            access = AccessProbe.UNKNOWN
            try:
                observed = target.read_access()
                if not isinstance(observed, AccessProbe):
                    raise TypeError("probe did not return AccessProbe")
                access = observed
            except Exception as exc:
                failure = type(exc).__name__  # Never log exception text.
            finally:
                mono_end = self._mono()
                wall_end = self._wall()
            entries.append(
                ProbeRecord(
                    label=target.label,
                    phase=phase,
                    sequence=sequence,
                    mono_start_ns=mono_start,
                    mono_end_ns=mono_end,
                    wall_start_ns=wall_start,
                    wall_end_ns=wall_end,
                    access=access,
                    error_type=failure,
                )
            )
        with self._lock:
            self._records.extend(entries)
        return tuple(entries)

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("timeline already started")
        self._thread = threading.Thread(
            target=self._loop, name="p3-access-probe", daemon=True
        )
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not self.capture_once("background"):
                break
            if self._stop.wait(self.interval_s):
                break

    def stop(self, join_timeout_s: float = 20.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(join_timeout_s)
            if self._thread.is_alive():
                raise TimeoutError("probe thread did not stop; no qualified timeline")

    def snapshot(self) -> tuple[ProbeRecord, ...]:
        with self._lock:
            return tuple(self._records)

    def evidence(self) -> dict[str, object]:
        records = self.snapshot()
        return {
            "grade": "independent polling; point evidence only",
            "clock_model": (
                "single-host monotonic request envelopes; UTC wall-clock "
                "timestamps descriptive only; no external clock-error qualification"
            ),
            "sampling_interval_target_s": self.interval_s,
            "bounded_max_rounds": self.max_rounds,
            "rounds_sampled": self._rounds,
            "capacity_reached": self._capacity_reached,
            "records": [r.public_dict() for r in records],
            "cutover_candidates": {
                target.label: access_cutover_candidate(records, target.label)
                for target in self.targets
            },
            "claims_not_established": [
                "no actual effect transition timestamp",
                "no verified monotonic-access assumption",
                "no continuous joint state or exact subject-seconds",
                "no calibrated exposure or interaction penalty",
            ],
        }


__all__ = [
    "ProbeTarget",
    "ProbeRecord",
    "AccessTimelineSampler",
    "access_cutover_candidate",
]
