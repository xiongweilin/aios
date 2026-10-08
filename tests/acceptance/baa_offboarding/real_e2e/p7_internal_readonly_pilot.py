"""Four-hour, supervised, GET-only P7 maintenance observation pilot.

Activation requires a private external approval record. This program never
infers permission from repository state, runner reachability, or a prior run.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from p7_shadow_readonly import qualified_contract_fingerprint  # noqa: E402

from scripts.check_p7_internal_readonly_pilot import CONTRACT, validate_contract  # noqa: E402

SCHEMA = "aios-p7-internal-readonly-pilot-v1"
ACTIVATION_SCHEMA = "aios-p7-internal-readonly-pilot-activation-v1"
PREFLIGHT_SCHEMA = "aios-p7-internal-readonly-pilot-preflight-v1"
SOURCES = ("runtime_health", "runtime_capabilities", "keycloak_realm", "odoo_root")
METHOD = "GET"
PILOT_WINDOW_SECONDS = 14_400
INTERVAL_SECONDS = 60
PLANNED_ROUNDS = 240
PLANNED_SLOTS = 960
REQUEST_TIMEOUT_SECONDS = 3.0
MAX_CAPABILITY_BODY_BYTES = 1_048_576
INSTRUMENT_PATH = Path(__file__).resolve()
MAX_PRESTART_ACK_SECONDS = 60
TOKEN_ENV = {
    "runtime_capabilities": "BAA_P7_RUNTIME_TOKEN",
    "keycloak_realm": "BAA_P7_KEYCLOAK_BEARER_TOKEN",
    "odoo_root": "BAA_P7_ODOO_BEARER_TOKEN",
}
REFERENCE_KEYS = (
    "approval",
    "accountable_owner",
    "on_duty_operator",
    "private_contact_route",
    "written_read_authorization",
    "credential_scope_attestation",
    "resource_inventory",
    "independent_stop_access",
    "credential_revocation",
    "evidence_access_retention_review",
)
ATTESTATION_KEYS = (
    "named_accountable_owner_verified",
    "named_on_duty_operator_verified",
    "written_scoped_staging_read_authorization_verified",
    "four_source_inventory_verified",
    "read_only_credential_scope_verified",
    "independent_stop_access_verified",
    "pilot_credential_revocation_verified",
    "private_contact_route_verified",
    "evidence_access_and_14_day_retention_approved",
    "no_production_data_or_mutation_authorized",
)
EXPECTED_PATHS = {
    "runtime_health": "/healthz",
    "runtime_capabilities": "/v1/capabilities",
    "odoo_root": "/",
}
VALID_RESULTS = frozenset({"ok", "http_error", "transport_unknown", "schema_unknown", "not_attempted"})
SAFE_CLASSIFICATIONS = frozenset({
    "transport_unavailable",
    "capability_response_too_large",
    "invalid_capability_response",
    "security_contract_incomplete",
    "unexpected_redirect",
    "uncategorized_observation",
    "probe_runtime_error",
    "preflight_stopped",
    "manual_stop",
    "security_contract_invalid_or_weakened",
    "security_contract_fingerprint_drift",
    "resource_scope_change",
    "unqualified_start_baseline_failed",
    "non_ok_probe_fraction_over_threshold",
    "observation_reacquisition_over_300_seconds",
    "sample_gap_over_120_seconds",
    "time_budget_exceeded",
    "operator_unavailable",
    "cost_budget_exceeded",
    "pilot_window_incomplete",
    "evidence_integrity_failure",
})


def _safe_classification(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and (
        value in SAFE_CLASSIFICATIONS or re.fullmatch(r"http_[1-5][0-9]{2}", value)
    ):
        return value
    return "uncategorized_observation"
class PilotError(RuntimeError):
    """A fail-closed readiness, integrity, or qualification error."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise PilotError("invalid_approval_window")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PilotError("invalid_approval_window") from exc
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise PilotError("invalid_approval_window")
    return result.astimezone(UTC)


def _reference(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value))


def _delegation_reference(value: Any) -> bool:
    return isinstance(value, str) and bool(
        re.fullmatch(r"(?:delegation:)?[A-Za-z0-9._-]{1,128}", value)
    )


def _repo_path(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT.resolve())
        return True
    except ValueError:
        return False


def _validate_url(source: str, url: Any, realm: str) -> str:
    if not isinstance(url, str) or not url or any(ch.isspace() for ch in url):
        raise PilotError("invalid_resource_inventory")
    try:
        parts = urllib.parse.urlsplit(url)
        _ = parts.port
    except ValueError as exc:
        raise PilotError("invalid_resource_inventory") from exc
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise PilotError("invalid_resource_inventory")
    if source == "keycloak_realm":
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", realm) or realm in {".", ".."}:
            raise PilotError("invalid_approved_realm")
        expected = "/realms/" + realm
    else:
        expected = EXPECTED_PATHS[source]
    if parts.path != expected:
        raise PilotError("resource_scope_change")
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, "", ""))


def _is_loopback_url(url: str) -> bool:
    host = urllib.parse.urlsplit(url).hostname
    if host is None:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class Activation:
    references: dict[str, str]
    resources: dict[str, str]
    auth_modes: dict[str, str]
    runtime_delegation_id: str
    approved_realm: str
    preflight_start: datetime
    preflight_end: datetime
    pilot_start: datetime
    pilot_end: datetime
    resource_inventory_sha256: str


def load_activation(path_value: str | Path) -> Activation:
    path = Path(path_value).expanduser().resolve()
    if _repo_path(path) or not path.is_file():
        raise PilotError("external_activation_evidence_required")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PilotError("invalid_external_activation_evidence") from exc
    if not isinstance(data, dict) or data.get("schema") != ACTIVATION_SCHEMA:
        raise PilotError("invalid_external_activation_evidence")

    references = data.get("references")
    attestations = data.get("attestations")
    if not isinstance(references, dict) or set(references) != set(REFERENCE_KEYS):
        raise PilotError("activation_references_incomplete")
    if not all(_reference(references.get(key)) for key in REFERENCE_KEYS):
        raise PilotError("activation_references_invalid")
    if not isinstance(attestations, dict) or set(attestations) != set(ATTESTATION_KEYS):
        raise PilotError("activation_attestations_incomplete")
    if any(attestations.get(key) is not True for key in ATTESTATION_KEYS):
        raise PilotError("activation_attestation_not_verified")

    realm = data.get("approved_realm")
    if not isinstance(realm, str):
        raise PilotError("invalid_approved_realm")
    raw_resources = data.get("resources")
    if not isinstance(raw_resources, dict) or set(raw_resources) != set(SOURCES):
        raise PilotError("invalid_resource_inventory")
    resources = {source: _validate_url(source, raw_resources[source], realm) for source in SOURCES}
    inventory_payload = json.dumps(resources, sort_keys=True, separators=(",", ":")).encode("utf-8")
    inventory_sha = hashlib.sha256(inventory_payload).hexdigest()

    auth_modes = data.get("auth_modes")
    if not isinstance(auth_modes, dict) or set(auth_modes) != {
        "runtime_capabilities", "keycloak_realm", "odoo_root"
    }:
        raise PilotError("invalid_read_only_auth_configuration")
    if auth_modes.get("runtime_capabilities") != "bearer" or any(
        auth_modes.get(source) not in {"none", "bearer"}
        for source in ("keycloak_realm", "odoo_root")
    ):
        raise PilotError("invalid_read_only_auth_configuration")
    if any(
        auth_modes[source] == "bearer"
        and not resources[source].startswith("https://")
        and not _is_loopback_url(resources[source])
        for source in auth_modes
    ):
        raise PilotError("authenticated_resource_requires_https")

    delegation = data.get("runtime_delegation_id")
    if not _delegation_reference(delegation):
        raise PilotError("invalid_runtime_delegation_reference")
    preflight_window = data.get("preflight_window")
    pilot_window = data.get("pilot_window")
    if not isinstance(preflight_window, dict) or set(preflight_window) != {"start_utc", "end_utc"}:
        raise PilotError("invalid_preflight_window")
    if not isinstance(pilot_window, dict) or set(pilot_window) != {"start_utc", "end_utc"}:
        raise PilotError("invalid_approval_window")
    pf_start = parse_utc(preflight_window.get("start_utc"), "preflight_start_utc")
    pf_end = parse_utc(preflight_window.get("end_utc"), "preflight_end_utc")
    pilot_start = parse_utc(pilot_window.get("start_utc"), "pilot_start_utc")
    pilot_end = parse_utc(pilot_window.get("end_utc"), "pilot_end_utc")
    if (
        pf_start >= pf_end
        or pf_end > pilot_start
        or (pilot_end - pilot_start).total_seconds() != PILOT_WINDOW_SECONDS
    ):
        raise PilotError("invalid_approval_window")

    return Activation(
        references=dict(references),
        resources=resources,
        auth_modes=dict(auth_modes),
        runtime_delegation_id=delegation,
        approved_realm=realm,
        preflight_start=pf_start,
        preflight_end=pf_end,
        pilot_start=pilot_start,
        pilot_end=pilot_end,
        resource_inventory_sha256=inventory_sha,
    )


def credential_headers(activation: Activation) -> dict[str, dict[str, str]]:
    headers: dict[str, dict[str, str]] = {source: {} for source in SOURCES}
    for source, env_name in TOKEN_ENV.items():
        needed = source == "runtime_capabilities" or activation.auth_modes[source] == "bearer"
        if not needed:
            continue
        value = os.environ.get(env_name)
        if not value:
            raise PilotError("required_scoped_read_credential_missing")
        headers[source]["Authorization"] = "Bearer " + value
    headers["runtime_capabilities"]["X-World-Runtime-Delegation"] = activation.runtime_delegation_id
    return headers


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


@dataclass(frozen=True)
class ProbeResult:
    result: str
    fingerprint: str | None = None
    error_class: str | None = None
    terminal_reason: str | None = None


def probe_once(
    source: str,
    activation: Activation,
    headers: dict[str, dict[str, str]],
    *,
    timeout_s: float = REQUEST_TIMEOUT_SECONDS,
    open_request: Callable[..., Any] | None = None,
) -> ProbeResult:
    if source not in SOURCES:
        return ProbeResult("schema_unknown", error_class="uncategorized_observation", terminal_reason="uncategorized_observation")
    opener = open_request or urllib.request.build_opener(NoRedirectHandler()).open
    request = urllib.request.Request(activation.resources[source], headers=headers[source], method=METHOD)
    try:
        response = opener(request, timeout=timeout_s)
        try:
            status = int(response.status)
            if 300 <= status < 400:
                return ProbeResult(
                    "http_error",
                    error_class="unexpected_redirect",
                    terminal_reason="unexpected_redirect",
                )
            if status != 200:
                return ProbeResult("http_error", error_class=f"http_{status}")
            if source != "runtime_capabilities":
                return ProbeResult("ok")
            body = response.read(MAX_CAPABILITY_BODY_BYTES + 1)
            if len(body) > MAX_CAPABILITY_BODY_BYTES:
                return ProbeResult(
                    "schema_unknown",
                    error_class="capability_response_too_large",
                    terminal_reason="security_contract_invalid_or_weakened",
                )
            try:
                payload = json.loads(body.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                return ProbeResult(
                    "schema_unknown",
                    error_class="invalid_capability_response",
                    terminal_reason="security_contract_invalid_or_weakened",
                )
            fingerprint = qualified_contract_fingerprint(payload)
            if fingerprint is None:
                return ProbeResult(
                    "schema_unknown",
                    error_class="security_contract_incomplete",
                    terminal_reason="security_contract_invalid_or_weakened",
                )
            return ProbeResult("ok", fingerprint=fingerprint)
        finally:
            response.close()
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code in {401, 403}:
            return ProbeResult("http_error", error_class=f"http_{exc.code}", terminal_reason=f"http_{exc.code}")
        if 300 <= exc.code < 400:
            return ProbeResult("http_error", error_class="unexpected_redirect", terminal_reason="unexpected_redirect")
        return ProbeResult("http_error", error_class=f"http_{exc.code}")
    except (urllib.error.URLError, OSError, TimeoutError, ConnectionError):
        return ProbeResult("transport_unknown", error_class="transport_unavailable")
    except Exception:
        return ProbeResult("schema_unknown", error_class="uncategorized_observation", terminal_reason="uncategorized_observation")


@dataclass(frozen=True)
class SlotRecord:
    slot_index: int
    sample_round: int
    source: str
    method: str
    attempted: bool
    started_ns: int | None
    completed_ns: int | None
    started_at_utc: str | None
    completed_at_utc: str | None
    classified_result: str
    fingerprint_or_null: str | None
    error_class_or_null: str | None

    def __post_init__(self) -> None:
        if (
            type(self.slot_index) is not int
            or self.slot_index < 0
            or type(self.sample_round) is not int
            or self.sample_round != self.slot_index // len(SOURCES)
            or self.source not in SOURCES
            or self.method != METHOD
            or self.classified_result not in VALID_RESULTS
            or type(self.attempted) is not bool
        ):
            raise ValueError("invalid_pilot_slot")
        if self.attempted != (self.started_ns is not None and self.completed_ns is not None):
            raise ValueError("invalid_pilot_attempt_timing")
        if self.attempted:
            if (
                type(self.started_ns) is not int
                or type(self.completed_ns) is not int
                or self.completed_ns < self.started_ns
                or not isinstance(self.started_at_utc, str)
                or not isinstance(self.completed_at_utc, str)
                or self.classified_result == "not_attempted"
            ):
                raise ValueError("invalid_pilot_attempt_timing")
            parse_utc(self.started_at_utc, "slot_started_at_utc")
            parse_utc(self.completed_at_utc, "slot_completed_at_utc")
            if self.fingerprint_or_null is not None and (
                self.source != "runtime_capabilities"
                or re.fullmatch(r"[0-9a-f]{64}", self.fingerprint_or_null) is None
            ):
                raise ValueError("invalid_capability_fingerprint")
        elif (
            self.started_at_utc is not None
            or self.completed_at_utc is not None
            or self.classified_result != "not_attempted"
            or self.fingerprint_or_null is not None
        ):
            raise ValueError("attempted_slot_marked_missing")
        if self.error_class_or_null is not None and (
            _safe_classification(self.error_class_or_null) != self.error_class_or_null
        ):
            raise ValueError("unsafe_error_classification")


class EvidenceJournal:
    """Append-only checkpoints; each complete slot is flushed before the next request."""

    def __init__(self, directory: Path, run_id: str) -> None:
        self.directory = directory
        self.run_id = run_id
        self.records_path = directory / "observations.jsonl"
        self.events_path = directory / "operator-events.jsonl"
        self.checkpoint_path = directory / "checkpoint.json"
        self._previous_hash = "0" * 64
        self._previous_event_hash = "0" * 64
        self._record_count = 0
        self._event_count = 0
        self.directory.mkdir(parents=True, exist_ok=False)
        self.records_path.touch(exist_ok=False)
        self.events_path.touch(exist_ok=False)
        self._write_checkpoint("running")

    @staticmethod
    def _append(path: Path, row: dict[str, Any]) -> None:
        data = (json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        with path.open("ab", buffering=0) as stream:
            view = memoryview(data)
            while view:
                view = view[stream.write(view):]
            os.fsync(stream.fileno())

    def append_slot(self, record: SlotRecord) -> None:
        payload = asdict(record)
        material = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        current_hash = hashlib.sha256(bytes.fromhex(self._previous_hash) + material).hexdigest()
        self._append(self.records_path, {**payload, "previous_hash": self._previous_hash, "chain_hash": current_hash})
        self._previous_hash = current_hash
        self._record_count += 1
        self._write_checkpoint("running")

    def append_event(self, event: dict[str, Any]) -> None:
        material = json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        current_hash = hashlib.sha256(bytes.fromhex(self._previous_event_hash) + material).hexdigest()
        self._append(
            self.events_path,
            {**event, "previous_hash": self._previous_event_hash, "chain_hash": current_hash},
        )
        self._previous_event_hash = current_hash
        self._event_count += 1
        self._write_checkpoint("running")

    def _write_checkpoint(self, status: str) -> None:
        data = {
            "schema": "aios-p7-internal-readonly-pilot-checkpoint-v1",
            "run_id": self.run_id,
            "status": status,
            "record_count": self._record_count,
            "event_count": self._event_count,
            "last_slot_index": self._record_count - 1 if self._record_count else None,
            "last_chain_hash": self._previous_hash,
            "last_event_hash": self._previous_event_hash,
        }
        temporary = self.checkpoint_path.with_suffix(".tmp")
        with temporary.open("wb") as stream:
            stream.write((json.dumps(data, sort_keys=True, indent=2) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.checkpoint_path)

    def finalize(self, manifest: dict[str, Any], qualification: dict[str, Any]) -> None:
        self._write_checkpoint(manifest["status"])
        self._write_json_atomic(self.directory / "manifest.json", manifest)
        self._write_json_atomic(self.directory / "qualification.json", qualification)
        checksums = []
        for name in ("observations.jsonl", "operator-events.jsonl", "checkpoint.json", "manifest.json", "qualification.json"):
            digest = hashlib.sha256((self.directory / name).read_bytes()).hexdigest()
            checksums.append(f"{digest}  {name}")
        with (self.directory / "SHA256SUMS").open("wb") as stream:
            stream.write(("\n".join(checksums) + "\n").encode("ascii"))
            stream.flush()
            os.fsync(stream.fileno())

    @staticmethod
    def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("wb") as stream:
            stream.write((json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)


class OperatorConsole:
    COMMANDS = {"ON-DUTY", "ACK", "ATTENTION START", "ATTENTION STOP", "ASSURANCE START", "ASSURANCE STOP", "STOP"}

    def __init__(self, journal: EvidenceJournal) -> None:
        if not sys.stdin.isatty():
            raise PilotError("interactive_on_duty_operator_required")
        self.journal = journal
        self.events: queue.Queue[tuple[str, int, datetime]] = queue.Queue()
        self.thread = threading.Thread(target=self._read, name="p7-operator-input", daemon=True)
        self.thread.start()

    def _read(self) -> None:
        while True:
            line = sys.stdin.readline()
            if not line:
                self.events.put(("EOF", time.monotonic_ns(), utc_now()))
                return
            self.events.put((line.strip().upper(), time.monotonic_ns(), utc_now()))

    def next_event(self, timeout_s: float) -> tuple[str, int, datetime] | None:
        try:
            return self.events.get(timeout=max(0.0, timeout_s))
        except queue.Empty:
            return None

    def drain(self) -> list[tuple[str, int, datetime]]:
        result = []
        while True:
            try:
                result.append(self.events.get_nowait())
            except queue.Empty:
                return result


class PilotRunner:
    def __init__(
        self,
        activation: Activation,
        journal: EvidenceJournal,
        probe: Callable[[str], ProbeResult],
        operator: Any,
        *,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        wall_clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.activation = activation
        self.journal = journal
        self.probe = probe
        self.operator = operator
        self.clock_ns = monotonic_ns
        self.wall_clock = wall_clock
        self.records: list[SlotRecord] = []
        self.operator_events: list[dict[str, Any]] = []
        self.stop_reason: str | None = None
        self.status = "running"
        self.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.acceptance_thresholds = self.contract["pilot_acceptance_thresholds"]
        self.horizon = self.contract["horizon"]
        self.baseline_fingerprint: str | None = None
        self.gap_started_ns: int | None = None
        self.clean_rounds_after_gap = 0
        self.pending_alerts: list[int] = []
        self.last_operator_ack_ns: int | None = None
        self.open_cost: tuple[str, int] | None = None
        self.cost_totals_ns = {"principal_attention": 0, "third_party_assurance_labor": 0}
        self.round_starts_ns: list[int] = []
        self.round_durations_ms: list[float] = []
        self.probe_durations_ms: list[float] = []
        self.reacquisition_durations_ns: list[int] = []
        self.unresolved_terminal = False
        self.window_end_mono_ns: int | None = None
        self.sampler_runtime_seconds = 0.0
        self.unresolved_gap_duration_ns = 0
        self.stop_requested = threading.Event()

    def request_stop(self, reason: str = "manual_stop") -> None:
        reason = _safe_classification(reason) or "uncategorized_observation"
        if self.stop_reason is None or self.stop_reason == "approved_window_complete":
            self.stop_reason = reason
        if self.status == "completed":
            self.status = "stopped"
        self.stop_requested.set()

    def _event(self, kind: str, mono_ns: int, when: datetime, **fields: Any) -> None:
        row = {"event": kind, "at_utc": utc_text(when), "monotonic_ns": mono_ns, **fields}
        self.journal.append_event(row)
        self.operator_events.append(row)

    def _handle_operator_events(self) -> None:
        for command, mono_ns, when in self.operator.drain():
            if command == "EOF":
                self._event("operator_unavailable", mono_ns, when)
                self.request_stop("operator_unavailable")
                continue
            if command == "STOP":
                self._event("manual_stop", mono_ns, when)
                self.request_stop("manual_stop")
                continue
            if command in {"ON-DUTY", "ACK"}:
                if command == "ON-DUTY" and self.last_operator_ack_ns is not None:
                    self._event("uncategorized_operator_command", mono_ns, when)
                    self.request_stop("uncategorized_observation")
                    continue
                late_heartbeat = (
                    self.last_operator_ack_ns is not None
                    and mono_ns - self.last_operator_ack_ns
                    > self.acceptance_thresholds["max_operator_acknowledgement_seconds"] * 1_000_000_000
                )
                self.last_operator_ack_ns = mono_ns
                if self.pending_alerts:
                    triggered = self.pending_alerts.pop(0)
                    response_seconds = max(0.0, (mono_ns - triggered) / 1_000_000_000)
                    self._event(
                        "operator_response",
                        mono_ns,
                        when,
                        response_seconds=response_seconds,
                    )
                    if response_seconds > self.acceptance_thresholds["max_operator_acknowledgement_seconds"]:
                        late_heartbeat = True
                else:
                    self._event("operator_presence_ack", mono_ns, when, command=command.lower())
                if late_heartbeat:
                    self._event("operator_acknowledgement_late", mono_ns, when)
                    self.request_stop("operator_unavailable")
                continue
            if command in {"ATTENTION START", "ASSURANCE START"}:
                if self.open_cost is not None:
                    self._event("invalid_cost_interval", mono_ns, when)
                    self.request_stop("uncategorized_observation")
                    continue
                role = "principal_attention" if command.startswith("ATTENTION") else "third_party_assurance_labor"
                self.open_cost = (role, mono_ns)
                self._event("cost_interval_start", mono_ns, when, cost_kind=role)
                continue
            if command in {"ATTENTION STOP", "ASSURANCE STOP"}:
                role = "principal_attention" if command.startswith("ATTENTION") else "third_party_assurance_labor"
                if self.open_cost is None or self.open_cost[0] != role:
                    self._event("invalid_cost_interval", mono_ns, when)
                    self.request_stop("uncategorized_observation")
                    continue
                _, start_ns = self.open_cost
                duration_ns = mono_ns - start_ns
                self.cost_totals_ns[role] += duration_ns
                self.open_cost = None
                self._event("cost_interval_end", mono_ns, when, cost_kind=role, duration_ns=duration_ns)
                limit_minutes = self.acceptance_thresholds[
                    "max_principal_attention_minutes"
                    if role == "principal_attention"
                    else "max_third_party_assurance_labor_minutes"
                ]
                if self.cost_totals_ns[role] > limit_minutes * 60_000_000_000:
                    self._event("cost_budget_exceeded", mono_ns, when, cost_kind=role)
                    self.request_stop("cost_budget_exceeded")
                continue
            self._event("uncategorized_operator_command", mono_ns, when)
            self.request_stop("uncategorized_observation")

    def _alert(self, reason: str, mono_ns: int, when: datetime) -> None:
        reason = _safe_classification(reason) or "uncategorized_observation"
        self.pending_alerts.append(mono_ns)
        self._event("operator_alert", mono_ns, when, alert_class=reason)
        print(f"P7 PILOT ALERT: {reason}. Follow the approved human stop/escalation procedure.", flush=True)

    def _operator_health(self) -> bool:
        self._handle_operator_events()
        now = self.clock_ns()
        if self.stop_requested.is_set():
            return False
        max_ack_ns = self.acceptance_thresholds["max_operator_acknowledgement_seconds"] * 1_000_000_000
        if self.last_operator_ack_ns is None or now - self.last_operator_ack_ns > max_ack_ns:
            self.request_stop("operator_unavailable")
            return False
        if self.pending_alerts and now - self.pending_alerts[0] > max_ack_ns:
            self.request_stop("operator_unavailable")
            return False
        if self.open_cost is not None:
            role, start_ns = self.open_cost
            threshold = self.acceptance_thresholds[
                "max_principal_attention_minutes"
                if role == "principal_attention"
                else "max_third_party_assurance_labor_minutes"
            ]
            if now - start_ns + self.cost_totals_ns[role] > threshold * 60_000_000_000:
                self.request_stop("cost_budget_exceeded")
                return False
        return True

    def _await_pending_operator_response(self) -> None:
        if not self.pending_alerts:
            return
        deadline_ns = min(
            event_ns + self.acceptance_thresholds["max_operator_acknowledgement_seconds"] * 1_000_000_000
            for event_ns in self.pending_alerts
        )
        if self.window_end_mono_ns is not None:
            deadline_ns = min(deadline_ns, self.window_end_mono_ns)
        while self.pending_alerts and not self.stop_requested.is_set() and self.clock_ns() < deadline_ns:
            remaining = (deadline_ns - self.clock_ns()) / 1_000_000_000
            event = self.operator.next_event(min(1.0, max(0.0, remaining)))
            if event is not None:
                self.operator.events.put(event)
                self._handle_operator_events()
        if self.pending_alerts and self.clock_ns() >= deadline_ns:
            if self.stop_reason == "approved_window_complete":
                self.stop_reason = "operator_unavailable"
                self.status = "stopped"
            self.request_stop("operator_unavailable")

    def _wait_until(self, target_ns: int) -> bool:
        while self.clock_ns() < target_ns:
            if not self._operator_health():
                return False
            remaining = (target_ns - self.clock_ns()) / 1_000_000_000
            event = self.operator.next_event(min(1.0, max(0.0, remaining)))
            if event is not None:
                command, mono_ns, when = event
                self.operator.events.put((command, mono_ns, when))
                self._handle_operator_events()
        return self._operator_health()

    def _record_not_attempted(self, slot_index: int, reason: str) -> None:
        record = SlotRecord(
            slot_index=slot_index,
            sample_round=slot_index // len(SOURCES),
            source=SOURCES[slot_index % len(SOURCES)],
            method=METHOD,
            attempted=False,
            started_ns=None,
            completed_ns=None,
            started_at_utc=None,
            completed_at_utc=None,
            classified_result="not_attempted",
            fingerprint_or_null=None,
            error_class_or_null=_safe_classification(reason),
        )
        self.records.append(record)
        self.journal.append_slot(record)

    def _fill_remaining(self) -> None:
        for slot_index in range(len(self.records), PLANNED_SLOTS):
            self._record_not_attempted(slot_index, self.stop_reason or "pilot_window_incomplete")

    def _attempt_slot(self, slot_index: int) -> ProbeResult:
        source = SOURCES[slot_index % len(SOURCES)]
        start_ns, start_utc = self.clock_ns(), self.wall_clock()
        try:
            outcome = self.probe(source)
            if not isinstance(outcome, ProbeResult) or outcome.result not in VALID_RESULTS - {"not_attempted"}:
                outcome = ProbeResult("schema_unknown", error_class="uncategorized_observation", terminal_reason="uncategorized_observation")
            else:
                safe_error = _safe_classification(outcome.error_class)
                safe_terminal = _safe_classification(outcome.terminal_reason)
                bad_fingerprint = outcome.fingerprint is not None and (
                    source != "runtime_capabilities"
                    or re.fullmatch(r"[0-9a-f]{64}", outcome.fingerprint) is None
                )
                if (
                    safe_error != outcome.error_class
                    or safe_terminal != outcome.terminal_reason
                    or bad_fingerprint
                ):
                    outcome = ProbeResult(
                        "schema_unknown",
                        error_class="uncategorized_observation",
                        terminal_reason="uncategorized_observation",
                    )
        except Exception:
            outcome = ProbeResult("transport_unknown", error_class="probe_runtime_error")
        end_ns, end_utc = self.clock_ns(), self.wall_clock()
        duration_ms = max(0.0, (end_ns - start_ns) / 1_000_000)
        self.probe_durations_ms.append(duration_ms)
        record = SlotRecord(
            slot_index=slot_index,
            sample_round=slot_index // len(SOURCES),
            source=source,
            method=METHOD,
            attempted=True,
            started_ns=start_ns,
            completed_ns=end_ns,
            started_at_utc=utc_text(start_utc),
            completed_at_utc=utc_text(end_utc),
            classified_result=outcome.result,
            fingerprint_or_null=outcome.fingerprint,
            error_class_or_null=outcome.error_class,
        )
        self.records.append(record)
        self.journal.append_slot(record)
        if outcome.terminal_reason:
            self.unresolved_terminal = True
        if outcome.result != "ok":
            self._alert(outcome.terminal_reason or outcome.error_class or "uncategorized_observation", end_ns, end_utc)
            if self.gap_started_ns is None:
                self.gap_started_ns = end_ns
                self.clean_rounds_after_gap = 0
        return outcome

    def run(self) -> tuple[dict[str, Any], dict[str, Any]]:
        self._handle_operator_events()
        if self.last_operator_ack_ns is None:
            raise PilotError("on_duty_operator_confirmation_required")
        now_utc = self.wall_clock()
        now_mono = self.clock_ns()
        if now_utc > self.activation.pilot_start:
            self.stop_reason = "time_budget_exceeded"
            pilot_start_mono = now_mono
        else:
            pilot_start_mono = now_mono + int(
                (self.activation.pilot_start - now_utc).total_seconds() * 1_000_000_000
            )
        if now_utc < self.activation.pilot_start:
            print("Waiting for the approved UTC pilot start; operator coverage remains required.", flush=True)
            if not self._wait_until(pilot_start_mono):
                self.stop_reason = self.stop_reason or "operator_unavailable"

        self.window_end_mono_ns = pilot_start_mono + PILOT_WINDOW_SECONDS * 1_000_000_000
        pilot_start_utc = self.wall_clock()
        if (
            pilot_start_utc < self.activation.pilot_start
            or pilot_start_utc >= self.activation.pilot_end
        ):
            self.stop_reason = self.stop_reason or "time_budget_exceeded"
        baseline_ok = False

        for round_number in range(PLANNED_ROUNDS):
            if self.stop_reason:
                break
            target_ns = pilot_start_mono + round_number * INTERVAL_SECONDS * 1_000_000_000
            if not self._wait_until(target_ns):
                self.stop_reason = self.stop_reason or "operator_unavailable"
                break
            round_started_ns = self.clock_ns()
            if (
                self.round_starts_ns
                and round_started_ns - self.round_starts_ns[-1]
                > self.acceptance_thresholds["max_unscheduled_sample_gap_seconds"] * 1_000_000_000
            ):
                self.stop_reason = "sample_gap_over_120_seconds"
                self.unresolved_terminal = True
                self._alert(self.stop_reason, round_started_ns, self.wall_clock())
                break
            self.round_starts_ns.append(round_started_ns)
            round_outcomes: list[ProbeResult] = []
            for offset in range(len(SOURCES)):
                if not self._operator_health():
                    self.stop_reason = self.stop_reason or "operator_unavailable"
                    break
                if (
                    self.clock_ns() >= self.window_end_mono_ns
                    or self.wall_clock() >= self.activation.pilot_end
                ):
                    self.stop_reason = "time_budget_exceeded"
                    break
                outcome = self._attempt_slot(round_number * len(SOURCES) + offset)
                round_outcomes.append(outcome)
                if (
                    round_number > 0
                    and SOURCES[offset] == "runtime_capabilities"
                    and outcome.fingerprint is not None
                    and self.baseline_fingerprint is not None
                    and outcome.fingerprint != self.baseline_fingerprint
                ):
                    self.stop_reason = "security_contract_fingerprint_drift"
                    self.unresolved_terminal = True
                    self._alert(self.stop_reason, self.clock_ns(), self.wall_clock())
                    break
                if outcome.terminal_reason:
                    self.stop_reason = outcome.terminal_reason
                    break
                if round_number == 0 and outcome.result != "ok" and outcome.error_class in {"http_401", "http_403"}:
                    self.stop_reason = outcome.error_class
                    self.unresolved_terminal = True
                    break
                non_ok = sum(row.classified_result != "ok" for row in self.records if row.attempted)
                if non_ok / PLANNED_SLOTS > self.acceptance_thresholds["max_non_ok_probe_fraction"]:
                    self.stop_reason = "non_ok_probe_fraction_over_threshold"
                    self.unresolved_terminal = True
                    self._alert(self.stop_reason, self.clock_ns(), self.wall_clock())
                    break
            round_end_ns = self.clock_ns()
            if len(round_outcomes) == len(SOURCES):
                self.round_durations_ms.append(max(0.0, (round_end_ns - round_started_ns) / 1_000_000))
            if round_number == 0:
                baseline_row = next((row for row in self.records if row.source == "runtime_capabilities"), None)
                baseline_ok = (
                    len(round_outcomes) == len(SOURCES)
                    and all(item.result == "ok" for item in round_outcomes)
                    and baseline_row is not None
                    and bool(baseline_row.fingerprint_or_null)
                )
                if baseline_ok:
                    self.baseline_fingerprint = baseline_row.fingerprint_or_null
                else:
                    self.status = "unqualified_start"
                    if self.stop_reason is None:
                        self.stop_reason = "unqualified_start_baseline_failed"
                        self._alert(self.stop_reason, self.clock_ns(), self.wall_clock())
            else:
                if all(item.result == "ok" for item in round_outcomes) and self.gap_started_ns is not None:
                    self.clean_rounds_after_gap += 1
                    if self.clean_rounds_after_gap >= self.horizon["clean_reacquisition_rounds"]:
                        reacquisition_ns = max(0, self.clock_ns() - self.gap_started_ns)
                        if reacquisition_ns > (
                            self.acceptance_thresholds["max_observation_reacquisition_seconds"]
                            * 1_000_000_000
                        ):
                            self.stop_reason = "observation_reacquisition_over_300_seconds"
                            self.unresolved_terminal = True
                            self._alert(self.stop_reason, self.clock_ns(), self.wall_clock())
                        else:
                            self.reacquisition_durations_ns.append(reacquisition_ns)
                            self.gap_started_ns = None
                            self.clean_rounds_after_gap = 0
                elif any(item.result != "ok" for item in round_outcomes):
                    self.clean_rounds_after_gap = 0
            if (
                self.gap_started_ns is not None
                and self.stop_reason is None
                and self.clock_ns() - self.gap_started_ns
                > self.acceptance_thresholds["max_observation_reacquisition_seconds"] * 1_000_000_000
            ):
                self.stop_reason = self.stop_reason or "observation_reacquisition_over_300_seconds"
                self.unresolved_terminal = True
                self._alert(self.stop_reason, self.clock_ns(), self.wall_clock())
            if self.stop_reason:
                break
            if self.clock_ns() >= self.window_end_mono_ns:
                self.stop_reason = "time_budget_exceeded"
                break
            self._handle_operator_events()

        if self.stop_requested.is_set() and self.stop_reason is None:
            self.stop_reason = "manual_stop"
        if not self.stop_reason:
            end_ns = self.window_end_mono_ns
            if not self._wait_until(int(end_ns)):
                self.stop_reason = self.stop_reason or "operator_unavailable"
            else:
                self.stop_reason = "approved_window_complete"
                self.status = "completed"

        sampler_stopped_ns = self.window_end_mono_ns if self.status == "completed" else self.clock_ns()
        self.sampler_runtime_seconds = min(
            PILOT_WINDOW_SECONDS,
            max(0.0, (sampler_stopped_ns - pilot_start_mono) / 1_000_000_000),
        )
        if self.gap_started_ns is not None:
            self.unresolved_gap_duration_ns = max(0, sampler_stopped_ns - self.gap_started_ns)
        self._await_pending_operator_response()
        if self.status == "running" and self.stop_reason is not None:
            self.status = "stopped"

        if self.open_cost is not None:
            role, started = self.open_cost
            duration = max(0, self.clock_ns() - started)
            self.cost_totals_ns[role] += duration
            self._event("cost_interval_closed_at_stop", self.clock_ns(), self.wall_clock(), cost_kind=role, duration_ns=duration)
            self.open_cost = None
        self._fill_remaining()
        finished = self.wall_clock()
        record_integrity = verify_observation_chain(self.journal.records_path)
        event_integrity = verify_event_chain(self.journal.events_path)
        checkpoint_integrity = verify_checkpoint(
            self.journal.checkpoint_path,
            self.journal.run_id,
            record_integrity,
            event_integrity,
        )
        evidence_integrity = (
            record_integrity["valid"]
            and event_integrity["valid"]
            and checkpoint_integrity["valid"]
        )
        if not evidence_integrity:
            self.status = "evidence_integrity_failure"
            self.stop_reason = "evidence_integrity_failure"
        qualification = qualify_run(
            self.records,
            self.operator_events,
            self.activation,
            self.probe_durations_ms,
            self.round_durations_ms,
            self.round_starts_ns,
            self.cost_totals_ns,
            status=self.status,
            stop_reason=self.stop_reason,
            baseline_ok=baseline_ok,
            integrity=evidence_integrity,
            terminal_unresolved=(
                self.unresolved_terminal
                or self.gap_started_ns is not None
                or not evidence_integrity
            ),
            reacquisition_durations_ns=self.reacquisition_durations_ns,
            sampler_runtime_seconds=self.sampler_runtime_seconds,
            unresolved_gap_duration_ns=self.unresolved_gap_duration_ns,
        )
        manifest = {
            "schema": SCHEMA,
            "run_id": self.journal.run_id,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "started_at_utc": utc_text(pilot_start_utc),
            "finished_at_utc": utc_text(finished),
            "approved_window_start_utc": utc_text(self.activation.pilot_start),
            "approved_window_end_utc": utc_text(self.activation.pilot_end),
            "approved_window_start_monotonic_ns": pilot_start_mono,
            "approved_window_end_monotonic_ns": self.window_end_mono_ns,
            "approval_reference": self.activation.references["approval"],
            "credential_scope_reference": self.activation.references["credential_scope_attestation"],
            "resource_inventory_reference": self.activation.references["resource_inventory"],
            "operator_reference": self.activation.references["on_duty_operator"],
            "accountable_owner_reference": self.activation.references["accountable_owner"],
            "independent_stop_reference": self.activation.references["independent_stop_access"],
            "credential_revocation_reference": self.activation.references["credential_revocation"],
            "evidence_access_retention_reference": self.activation.references["evidence_access_retention_review"],
            "resource_inventory_sha256": self.activation.resource_inventory_sha256,
            "baseline_capability_fingerprint": self.baseline_fingerprint,
            "contract_sha256": _contract_sha256(),
            "repo_revision": _repo_revision(),
            "instrument_sha256": hashlib.sha256(INSTRUMENT_PATH.read_bytes()).hexdigest(),
            "planned_rounds": PLANNED_ROUNDS,
            "planned_slots": PLANNED_SLOTS,
            "automated_monitor_runtime_seconds": self.sampler_runtime_seconds,
            "external_readback_count": qualification["attempted_get_count"],
            "evidence_integrity": {
                "observation_chain": record_integrity,
                "operator_event_chain": event_integrity,
                "checkpoint": checkpoint_integrity,
            },
            "lineage": {
                "source": "approved private activation record plus four allowlisted HTTP GET sources",
                "state": "pending_independent_review",
                "owner": "P7 internal read-only pilot contract v1; activation owner/operator references above",
                "validation": "contract checker, observation/event chains, checkpoint reconciliation, frozen acceptance evaluator",
                "lineage_version": "aios-p7-internal-readonly-pilot-v1",
                "allowed_use": "this supervised internal staging pilot only; not a production SLO or delegation claim",
            },
        }
        self.journal.finalize(manifest, qualification)
        return manifest, qualification


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) * q + 0.999999999) - 1)))
    return ordered[index]


def verify_observation_chain(path: Path) -> dict[str, Any]:
    previous = "0" * 64
    count = 0
    saw_not_attempted = False
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                chain_hash = row.pop("chain_hash")
                prior_hash = row.pop("previous_hash")
                if prior_hash != previous:
                    return {"valid": False, "record_count": count}
                material = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
                expected = hashlib.sha256(bytes.fromhex(previous) + material).hexdigest()
                if chain_hash != expected:
                    return {"valid": False, "record_count": count}
                if set(row) != set(SlotRecord.__dataclass_fields__):
                    return {"valid": False, "record_count": count}
                record = SlotRecord(**row)
                if (
                    record.slot_index != count
                    or record.sample_round != count // len(SOURCES)
                    or record.source != SOURCES[count % len(SOURCES)]
                    or (saw_not_attempted and record.attempted)
                ):
                    return {"valid": False, "record_count": count}
                saw_not_attempted = saw_not_attempted or not record.attempted
                previous = chain_hash
                count += 1
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, PilotError):
        return {"valid": False, "record_count": count}
    return {"valid": True, "record_count": count, "final_chain_hash": previous}


def verify_event_chain(path: Path) -> dict[str, Any]:
    previous = "0" * 64
    count = 0
    last_monotonic_ns = -1
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                chain_hash = row.pop("chain_hash")
                prior_hash = row.pop("previous_hash")
                if prior_hash != previous or not isinstance(row.get("event"), str):
                    return {"valid": False, "event_count": count}
                monotonic_ns = row.get("monotonic_ns")
                if type(monotonic_ns) is not int or monotonic_ns < last_monotonic_ns:
                    return {"valid": False, "event_count": count}
                parse_utc(row.get("at_utc"), "operator_event_at_utc")
                material = json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
                expected = hashlib.sha256(bytes.fromhex(previous) + material).hexdigest()
                if chain_hash != expected:
                    return {"valid": False, "event_count": count}
                previous = chain_hash
                last_monotonic_ns = monotonic_ns
                count += 1
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, PilotError):
        return {"valid": False, "event_count": count}
    return {"valid": True, "event_count": count, "final_chain_hash": previous}


def verify_checkpoint(
    path: Path,
    run_id: str,
    observation_integrity: dict[str, Any],
    event_integrity: dict[str, Any],
) -> dict[str, Any]:
    try:
        checkpoint = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"valid": False}
    matches = (
        isinstance(checkpoint, dict)
        and checkpoint.get("schema") == "aios-p7-internal-readonly-pilot-checkpoint-v1"
        and checkpoint.get("run_id") == run_id
        and checkpoint.get("status") in {
            "running", "completed", "stopped", "unqualified_start", "evidence_integrity_failure"
        }
        and checkpoint.get("record_count") == observation_integrity.get("record_count")
        and checkpoint.get("event_count") == event_integrity.get("event_count")
        and checkpoint.get("last_slot_index") == (
            observation_integrity.get("record_count", 0) - 1
            if observation_integrity.get("record_count", 0)
            else None
        )
        and checkpoint.get("last_chain_hash") == observation_integrity.get("final_chain_hash")
        and checkpoint.get("last_event_hash") == event_integrity.get("final_chain_hash")
        and observation_integrity.get("valid") is True
        and event_integrity.get("valid") is True
    )
    return {
        "valid": matches,
        "status": checkpoint.get("status") if isinstance(checkpoint, dict) else None,
        "record_count": checkpoint.get("record_count") if isinstance(checkpoint, dict) else None,
        "event_count": checkpoint.get("event_count") if isinstance(checkpoint, dict) else None,
    }


def qualify_run(
    records: list[SlotRecord],
    operator_events: list[dict[str, Any]],
    activation: Activation,
    probe_durations_ms: list[float],
    round_durations_ms: list[float],
    round_starts_ns: list[int],
    cost_totals_ns: dict[str, int],
    *,
    status: str,
    stop_reason: str | None,
    baseline_ok: bool,
    integrity: bool,
    terminal_unresolved: bool,
    reacquisition_durations_ns: list[int],
    sampler_runtime_seconds: float,
    unresolved_gap_duration_ns: int,
) -> dict[str, Any]:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    threshold = contract["pilot_acceptance_thresholds"]
    required_slots = threshold["planned_slots_accounted_exactly"]
    required_rounds = threshold["min_complete_rounds"]
    indexed = {record.slot_index: record for record in records}
    complete_slots = (
        len(records) == required_slots
        and len(indexed) == required_slots
        and set(indexed) == set(range(required_slots))
    )
    complete_rounds = sum(
        all(
            indexed.get(r * len(SOURCES) + i) is not None
            and indexed[r * len(SOURCES) + i].attempted
            for i in range(len(SOURCES))
        )
        for r in range(required_rounds)
    )
    attempted = [row for row in records if row.attempted]
    non_ok = sum(row.classified_result != "ok" for row in attempted)
    unclassified = sum(row.classified_result not in VALID_RESULTS for row in records)
    missing_rounds = sum(
        not all(indexed.get(r * len(SOURCES) + i) is not None for i in range(len(SOURCES)))
        for r in range(required_rounds)
    )
    gap_seconds = [
        max(0.0, (current - previous) / 1_000_000_000)
        for previous, current in zip(round_starts_ns, round_starts_ns[1:], strict=False)
    ]
    max_gap = max(gap_seconds, default=0.0)
    response_seconds = [
        event["response_seconds"] for event in operator_events if event.get("event") == "operator_response"
    ]
    terminal_unresolved_count = int(terminal_unresolved)
    reacquisition_seconds = [duration / 1_000_000_000 for duration in reacquisition_durations_ns]
    max_reacquisition_seconds = max(reacquisition_seconds, default=0.0)
    alert_count = sum(event.get("event") == "operator_alert" for event in operator_events)
    attention_minutes = cost_totals_ns["principal_attention"] / 60_000_000_000
    assurance_minutes = cost_totals_ns["third_party_assurance_labor"] / 60_000_000_000
    checks = {
        "planned_slots_accounted": complete_slots,
        "min_complete_rounds": complete_rounds >= threshold["min_complete_rounds"],
        "unclassified_slots": unclassified <= threshold["max_unclassified_slots"],
        "missing_evidence_rounds": missing_rounds <= threshold["max_missing_evidence_rounds"],
        "max_unscheduled_sample_gap": max_gap <= threshold["max_unscheduled_sample_gap_seconds"],
        "probe_p95": _percentile(probe_durations_ms, 0.95) is not None and _percentile(probe_durations_ms, 0.95) <= threshold["max_probe_p95_ms"],
        "round_p95": _percentile(round_durations_ms, 0.95) is not None and _percentile(round_durations_ms, 0.95) <= threshold["max_round_p95_ms"],
        "non_ok_probe_fraction": non_ok / required_slots <= threshold["max_non_ok_probe_fraction"],
        "contract_drift": not any(
            event.get("event") == "operator_alert"
            and event.get("alert_class") == "security_contract_fingerprint_drift"
            for event in operator_events
        ),
        "unauthorized_or_effectful_calls": len(attempted) == sum(row.method == "GET" for row in attempted),
        "terminal_unresolved": terminal_unresolved_count <= threshold["max_terminal_unresolved"],
        "principal_attention": attention_minutes <= threshold["max_principal_attention_minutes"],
        "third_party_assurance_labor": assurance_minutes <= threshold["max_third_party_assurance_labor_minutes"],
        "operator_acknowledgement": (
            len(response_seconds) == alert_count
            and all(value <= threshold["max_operator_acknowledgement_seconds"] for value in response_seconds)
        ),
        "observation_reacquisition": max_reacquisition_seconds <= threshold["max_observation_reacquisition_seconds"],
        "baseline_valid": baseline_ok,
        "evidence_integrity": integrity,
        "approved_window_completed": status == "completed" and stop_reason == "approved_window_complete",
        "external_business_effects": (
            threshold["expected_external_business_effect_count"] == 0
            and all(row.method == METHOD for row in attempted)
        ),
    }
    accepted = all(checks.values())
    return {
        "schema": "aios-p7-internal-readonly-pilot-qualification-v1",
        "contract_sha256": _contract_sha256(),
        "status": "operational_pilot_acceptance_passed" if accepted else "not_qualified",
        "acceptance_passed": accepted,
        "claim_scope": "one supervised internal staging read-only pilot only; not production SLO or delegation evidence",
        "planned_rounds": required_rounds,
        "planned_slots": required_slots,
        "recorded_slots": len(indexed),
        "attempted_get_count": len(attempted),
        "complete_observed_rounds": complete_rounds,
        "missing_evidence_rounds": missing_rounds,
        "non_ok_attempted_slots": non_ok,
        "non_ok_fraction_of_planned_slots": non_ok / required_slots,
        "max_unscheduled_sample_gap_seconds": max_gap,
        "probe_p95_ms": _percentile(probe_durations_ms, 0.95),
        "probe_p95_n": len(probe_durations_ms),
        "round_p95_ms": _percentile(round_durations_ms, 0.95),
        "round_p95_n": len(round_durations_ms),
        "principal_attention_minutes": attention_minutes,
        "third_party_assurance_labor_minutes": assurance_minutes,
        "operator_response_seconds": response_seconds,
        "terminal_unresolved_count": terminal_unresolved_count,
        "observation_reacquisition_count": len(reacquisition_seconds),
        "max_observation_reacquisition_seconds": max_reacquisition_seconds,
        "unresolved_observation_gap_seconds": unresolved_gap_duration_ns / 1_000_000_000,
        "automated_monitor_runtime_seconds": sampler_runtime_seconds,
        "external_readback_count": len(attempted),
        "expected_external_business_effect_count": 0,
        "stop_reason": stop_reason,
        "checks": checks,
        "decision": "independent auditor must verify evidence, activation references, and all frozen thresholds",
    }


def _repo_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PilotError("repository_provenance_unavailable") from exc
    revision = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
        raise PilotError("repository_provenance_invalid")
    return revision


def _contract_sha256() -> str:
    try:
        return hashlib.sha256(CONTRACT.read_bytes()).hexdigest()
    except OSError as exc:
        raise PilotError("frozen_pilot_contract_unavailable") from exc


def _external_output_dir(path_value: str | Path) -> Path:
    path = Path(path_value).expanduser().resolve()
    if _repo_path(path):
        raise PilotError("evidence_must_remain_outside_public_repository")
    return path


def _window_open(now: datetime, start: datetime, end: datetime) -> bool:
    return start <= now < end


def _preflight_payload(activation: Activation, outcomes: list[SlotRecord], qualified: bool) -> dict[str, Any]:
    return {
        "schema": PREFLIGHT_SCHEMA,
        "status": "qualified" if qualified else "unqualified_start",
        "scope": "one supervised, GET-only, four-source readiness round; not part of the 960-slot pilot denominator",
        "approval_reference": activation.references["approval"],
        "credential_scope_reference": activation.references["credential_scope_attestation"],
        "resource_inventory_reference": activation.references["resource_inventory"],
        "resource_inventory_sha256": activation.resource_inventory_sha256,
        "contract_sha256": _contract_sha256(),
        "repo_revision": _repo_revision(),
        "instrument_sha256": hashlib.sha256(INSTRUMENT_PATH.read_bytes()).hexdigest(),
        "planned_slots": 4,
        "attempted_get_count": sum(row.attempted for row in outcomes),
        "baseline_capability_fingerprint": next(
            (row.fingerprint_or_null for row in outcomes if row.source == "runtime_capabilities"), None
        ),
        "records": [asdict(row) for row in outcomes],
        "allowed_use": "readiness gate for the specified supervised staging pilot only",
    }


def run_preflight(activation: Activation, output_dir: Path) -> tuple[Path, bool]:
    if not _window_open(utc_now(), activation.preflight_start, activation.preflight_end):
        raise PilotError("preflight_outside_approved_window")
    output_dir = _external_output_dir(output_dir)
    headers = credential_headers(activation)
    output_dir.mkdir(parents=True, exist_ok=False)
    records: list[SlotRecord] = []
    for index, source in enumerate(SOURCES):
        start_ns, start_utc = time.monotonic_ns(), utc_now()
        outcome = probe_once(source, activation, headers)
        end_ns, end_utc = time.monotonic_ns(), utc_now()
        records.append(SlotRecord(
            slot_index=index,
            sample_round=0,
            source=source,
            method=METHOD,
            attempted=True,
            started_ns=start_ns,
            completed_ns=end_ns,
            started_at_utc=utc_text(start_utc),
            completed_at_utc=utc_text(end_utc),
            classified_result=outcome.result,
            fingerprint_or_null=outcome.fingerprint,
            error_class_or_null=outcome.error_class,
        ))
        if outcome.terminal_reason:
            break
    while len(records) < len(SOURCES):
        index = len(records)
        records.append(SlotRecord(index, 0, SOURCES[index], METHOD, False, None, None, None, None, "not_attempted", None, "preflight_stopped"))
    qualified = (
        all(row.classified_result == "ok" for row in records)
        and next((row.fingerprint_or_null for row in records if row.source == "runtime_capabilities"), None) is not None
    )
    payload = _preflight_payload(activation, records, qualified)
    path = output_dir / "preflight.json"
    EvidenceJournal._write_json_atomic(path, payload)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    sidecar = output_dir / "preflight.json.sha256"
    temporary = sidecar.with_suffix(sidecar.suffix + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(f"{digest}  preflight.json\n".encode("ascii"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, sidecar)
    return path, qualified


def verify_preflight(path_value: str | Path, activation: Activation) -> dict[str, Any]:
    path = Path(path_value).expanduser().resolve()
    if _repo_path(path) or not path.is_file():
        raise PilotError("qualified_preflight_evidence_required")
    try:
        sidecar = path.with_name(path.name + ".sha256").read_text(encoding="ascii").split()
        expected_hash = sidecar[0]
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, IndexError, json.JSONDecodeError) as exc:
        raise PilotError("preflight_evidence_integrity_failure") from exc
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash) or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
        raise PilotError("preflight_evidence_integrity_failure")
    records = payload.get("records")
    records_match = isinstance(records, list) and len(records) == len(SOURCES)
    if records_match:
        for index, (row, source) in enumerate(zip(records, SOURCES, strict=True)):
            if not isinstance(row, dict):
                records_match = False
                break
            try:
                started_at = parse_utc(row.get("started_at_utc"), "preflight_started_at_utc")
                completed_at = parse_utc(row.get("completed_at_utc"), "preflight_completed_at_utc")
            except PilotError:
                records_match = False
                break
            if (
                row.get("slot_index") != index
                or row.get("sample_round") != 0
                or row.get("source") != source
                or row.get("method") != METHOD
                or row.get("attempted") is not True
                or row.get("classified_result") != "ok"
                or type(row.get("started_ns")) is not int
                or type(row.get("completed_ns")) is not int
                or row["completed_ns"] - row["started_ns"] < 0
                or row["completed_ns"] - row["started_ns"]
                > REQUEST_TIMEOUT_SECONDS * 1_000_000_000
                or started_at < activation.preflight_start
                or completed_at > activation.preflight_end
                or completed_at < started_at
            ):
                records_match = False
                break
    matches = (
        payload.get("schema") == PREFLIGHT_SCHEMA
        and payload.get("status") == "qualified"
        and payload.get("approval_reference") == activation.references["approval"]
        and payload.get("credential_scope_reference") == activation.references["credential_scope_attestation"]
        and payload.get("resource_inventory_reference") == activation.references["resource_inventory"]
        and payload.get("resource_inventory_sha256") == activation.resource_inventory_sha256
        and payload.get("contract_sha256") == _contract_sha256()
        and payload.get("repo_revision") == _repo_revision()
        and payload.get("instrument_sha256") == hashlib.sha256(INSTRUMENT_PATH.read_bytes()).hexdigest()
        and payload.get("attempted_get_count") == 4
        and sidecar[1:] == [path.name]
        and records_match
        and all(
            isinstance(row.get("fingerprint_or_null"), str)
            and re.fullmatch(r"[0-9a-f]{64}", row["fingerprint_or_null"]) is not None
            if row.get("source") == "runtime_capabilities"
            else row.get("fingerprint_or_null") is None
            for row in records
        )
    )
    if not matches:
        raise PilotError("preflight_evidence_not_qualified_for_this_run")
    return payload


def start_observation(activation: Activation, preflight: dict[str, Any], output_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if not sys.stdin.isatty():
        raise PilotError("interactive_on_duty_operator_required")
    if utc_now() > activation.pilot_start:
        raise PilotError("pilot_must_start_at_approved_utc_start")
    if activation.pilot_start - utc_now() > timedelta(minutes=10):
        raise PilotError("pilot_window_not_imminent")
    output_dir = _external_output_dir(output_dir)
    if (
        preflight.get("schema") != PREFLIGHT_SCHEMA
        or preflight.get("status") != "qualified"
        or preflight.get("resource_inventory_sha256") != activation.resource_inventory_sha256
        or preflight.get("contract_sha256") != _contract_sha256()
        or preflight.get("approval_reference") != activation.references["approval"]
        or preflight.get("repo_revision") != _repo_revision()
        or preflight.get("instrument_sha256") != hashlib.sha256(INSTRUMENT_PATH.read_bytes()).hexdigest()
    ):
        raise PilotError("qualified_preflight_evidence_required")
    headers = credential_headers(activation)
    run_id = str(uuid.uuid4())
    journal = EvidenceJournal(output_dir / f"p7-pilot-{run_id}", run_id)
    print("P7 pilot operator console: ON-DUTY, ACK, ATTENTION START/STOP, ASSURANCE START/STOP, STOP", flush=True)
    print("Use ACK at least every 900 seconds. STOP halts sampling; use the separately approved stop/revoke route if this process cannot stop.", flush=True)
    operator = OperatorConsole(journal)
    print("Type ON-DUTY to confirm the named operator is present.", flush=True)
    first = operator.next_event(MAX_PRESTART_ACK_SECONDS)
    if first is None or first[0] != "ON-DUTY":
        raise PilotError("on_duty_operator_confirmation_missing")

    runner = PilotRunner(
        activation,
        journal,
        lambda source: probe_once(source, activation, headers),
        operator,
    )
    runner.last_operator_ack_ns = first[1]
    runner._event("operator_on_duty_confirmed", first[1], first[2])
    old_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, lambda _sig, _frame: runner.request_stop("manual_stop"))
    try:
        return runner.run()
    finally:
        signal.signal(signal.SIGINT, old_handler)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the separately authorized P7 internal read-only pilot.")
    parser.add_argument("mode", choices=("preflight", "observe"))
    parser.add_argument("--activation-file", required=True, help="Private external approval/inventory JSON; never store it in the repository.")
    parser.add_argument("--evidence-dir", required=True, help="Restricted evidence root outside the repository.")
    parser.add_argument("--preflight-proof", help="Qualified preflight.json path, required for observe mode.")
    args = parser.parse_args()
    try:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        errors = validate_contract(contract)
        if errors:
            raise PilotError("frozen_pilot_contract_invalid")
        activation = load_activation(args.activation_file)
        output_dir = _external_output_dir(args.evidence_dir)
        _repo_revision()
        if args.mode == "preflight":
            path, qualified = run_preflight(activation, output_dir)
            print(json.dumps({"status": "qualified" if qualified else "unqualified_start", "preflight_evidence": str(path)}, sort_keys=True))
            return 0 if qualified else 2
        if not args.preflight_proof:
            raise PilotError("qualified_preflight_evidence_required")
        proof = verify_preflight(args.preflight_proof, activation)
        manifest, qualification = start_observation(activation, proof, output_dir)
        print(json.dumps({"status": manifest["status"], "run_id": manifest["run_id"], "acceptance_passed": qualification["acceptance_passed"]}, sort_keys=True))
        return 0 if qualification["acceptance_passed"] else 2
    except PilotError as exc:
        print(json.dumps({"status": "not_started_or_not_qualified", "reason": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
