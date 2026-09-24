from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse


class ConnectorStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ConnectorResult:
    status: ConnectorStatus
    external_operation_ref: str | None = None
    observed_postcondition: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    reconciled: bool = False


class ConnectorConfigurationError(ValueError):
    pass


class _TransportUnknown(RuntimeError):
    pass


class _ApplicationRejected(RuntimeError):
    pass


def _validate_base_url(value: str, *, allow_insecure_http: bool) -> None:
    parsed = urlparse(value)
    allowed = {"https"} if not allow_insecure_http else {"http", "https"}
    if parsed.scheme not in allowed or not parsed.hostname:
        raise ConnectorConfigurationError("connector base URL is not permitted")


def _unknown_result(
    exc: Exception, *, reconciled: bool = False
) -> ConnectorResult:
    return ConnectorResult(
        ConnectorStatus.UNKNOWN,
        error_code=type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
        error_message=str(exc),
        reconciled=reconciled,
    )


def _unavailable_result(exc: Exception) -> ConnectorResult:
    return ConnectorResult(
        ConnectorStatus.UNAVAILABLE,
        error_code=type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__,
        error_message=str(exc),
    )


__all__ = [
    "ConnectorConfigurationError",
    "ConnectorResult",
    "ConnectorStatus",
]
