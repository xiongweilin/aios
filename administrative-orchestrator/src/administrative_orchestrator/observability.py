from __future__ import annotations

import re
import time
from contextvars import ContextVar
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request, Response
from prometheus_client import Counter, Histogram, make_asgi_app

_CORRELATION_ID = ContextVar("administrative_correlation_id", default="")
_CORRELATION_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_IDENTITY_REVOKE_PATTERN = re.compile(r"^/v1/operations/identities/[^/]+/revoke$")
_PRINCIPAL_DEACTIVATE_PATTERN = re.compile(r"^/v1/operations/principals/[^/]+/deactivate$")
_ROLE_EXPIRE_PATTERN = re.compile(r"^/v1/operations/role-assignments/[^/]+/expire$")
_DELEGATION_EXPIRE_PATTERN = re.compile(r"^/v1/operations/delegations/[^/]+/expire$")

HTTP_REQUESTS = Counter(
    "administrative_http_requests_total",
    "Administrative HTTP requests by bounded service/method/status dimensions.",
    ("service", "method", "status"),
)
HTTP_LATENCY = Histogram(
    "administrative_http_request_duration_seconds",
    "Administrative HTTP request latency.",
    ("service", "method"),
)
AUTHORITATIVE_REFRESH = Counter(
    "administrative_authoritative_fact_refresh_total",
    "Authoritative fact refresh attempts.",
    ("result",),
)
GOVERNANCE_REVALIDATION = Counter(
    "administrative_governance_revalidation_total",
    "Governance revalidation outcomes before reality transitions.",
    ("result",),
)
CONNECTOR_OUTCOME = Counter(
    "administrative_connector_outcome_total",
    "Production connector outcomes without request-identity cardinality.",
    ("system", "operation", "outcome"),
)
IDENTITY_LIFECYCLE = Counter(
    "administrative_identity_lifecycle_total",
    "Identity lifecycle semantic transitions.",
    ("event",),
)
RESPONSIBILITY_DISCHARGE = Counter(
    "administrative_responsibility_discharge_total",
    "Kernel responsibility discharge workflow outcomes without case identity labels.",
    ("result",),
)
INVESTIGATIONS = Counter(
    "administrative_investigations_total",
    "Bounded Administrative investigation lifecycle events.",
    ("trigger_type", "result"),
)
INVESTIGATION_FAILURES = Counter(
    "administrative_investigation_failures_total",
    "Administrative investigation advisory failures by bounded trigger type.",
    ("trigger_type",),
)
REOPEN_ASSESSMENTS = Counter(
    "administrative_reopen_assessments_total",
    "Administrative reopen assessments by bounded disposition.",
    ("disposition",),
)
REOPENS = Counter(
    "administrative_reopens_total",
    "Authorized Administrative reopen transitions.",
    (),
)
INVESTIGATION_DURATION = Histogram(
    "administrative_investigation_duration_seconds",
    "Bounded investigation advisory duration by trigger type.",
    ("trigger_type",),
)


def current_correlation_id() -> str:
    return _CORRELATION_ID.get()


def record_authoritative_refresh(*, success: bool) -> None:
    AUTHORITATIVE_REFRESH.labels(result="success" if success else "failure").inc()


def record_governance_revalidation(*, valid: bool) -> None:
    GOVERNANCE_REVALIDATION.labels(result="valid" if valid else "stale").inc()


def record_connector_outcome(*, system: str, operation: str, outcome: str) -> None:
    CONNECTOR_OUTCOME.labels(system=system, operation=operation, outcome=outcome).inc()


def record_identity_lifecycle(event: str) -> None:
    IDENTITY_LIFECYCLE.labels(event=event).inc()


def record_responsibility_discharge(*, result: str) -> None:
    if result not in {"pending", "discharged"}:
        result = "pending"
    RESPONSIBILITY_DISCHARGE.labels(result=result).inc()


def record_investigation_request(*, trigger_type: str, result: str) -> None:
    INVESTIGATIONS.labels(trigger_type=trigger_type, result=result).inc()


def record_investigation_failure(*, trigger_type: str) -> None:
    INVESTIGATION_FAILURES.labels(trigger_type=trigger_type).inc()


def record_reopen_assessment(*, disposition: str) -> None:
    REOPEN_ASSESSMENTS.labels(disposition=disposition).inc()


def record_reopen() -> None:
    REOPENS.inc()


def observe_investigation_duration(*, trigger_type: str, seconds: float) -> None:
    INVESTIGATION_DURATION.labels(trigger_type=trigger_type).observe(seconds)


def install_observability(app: FastAPI, *, service_name: str) -> None:
    """Install bounded request telemetry and correlation propagation once per app."""

    if getattr(app.state, "administrative_observability_installed", False):
        return
    app.state.administrative_observability_installed = True
    app.mount("/metrics", make_asgi_app())

    @app.middleware("http")
    async def _observe(request: Request, call_next):
        supplied = request.headers.get("X-Correlation-ID", "").strip()
        correlation_id = supplied if _CORRELATION_PATTERN.fullmatch(supplied) else str(uuid4())
        token = _CORRELATION_ID.set(correlation_id)
        started = time.perf_counter()
        status_code = 500
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        except Exception:
            structlog.get_logger("administrative.http").exception(
                "request_failed",
                service=service_name,
                correlation_id=correlation_id,
                method=request.method,
                path=request.url.path,
            )
            raise
        finally:
            duration = time.perf_counter() - started
            HTTP_REQUESTS.labels(
                service=service_name,
                method=request.method,
                status=str(status_code),
            ).inc()
            HTTP_LATENCY.labels(service=service_name, method=request.method).observe(duration)
            _record_operations_semantics(request.method, request.url.path, status_code)
            structlog.get_logger("administrative.http").info(
                "request_completed",
                service=service_name,
                correlation_id=correlation_id,
                method=request.method,
                path=request.url.path,
                status=status_code,
                duration_seconds=duration,
            )
            _CORRELATION_ID.reset(token)


def _record_operations_semantics(method: str, path: str, status_code: int) -> None:
    if method != "POST":
        return
    success = status_code < 400
    if path.endswith("/authoritative-facts/refresh"):
        record_authoritative_refresh(success=success)
        return
    if not success:
        return
    if path == "/v1/operations/identities/bind":
        record_identity_lifecycle("identity_binding.created")
    elif _IDENTITY_REVOKE_PATTERN.fullmatch(path):
        record_identity_lifecycle("identity_binding.revoked")
    elif _PRINCIPAL_DEACTIVATE_PATTERN.fullmatch(path):
        record_identity_lifecycle("principal.deactivated")
    elif _ROLE_EXPIRE_PATTERN.fullmatch(path):
        record_identity_lifecycle("role_assignment.expired")
    elif _DELEGATION_EXPIRE_PATTERN.fullmatch(path):
        record_identity_lifecycle("delegation.expired")


__all__ = [
    "current_correlation_id",
    "install_observability",
    "record_authoritative_refresh",
    "record_connector_outcome",
    "record_governance_revalidation",
    "record_identity_lifecycle",
    "record_investigation_failure",
    "record_investigation_request",
    "record_reopen",
    "record_reopen_assessment",
    "record_responsibility_discharge",
    "observe_investigation_duration",
]
