from __future__ import annotations

from .observability import install_observability
from .operations_api import app
from .telemetry import configure_telemetry

install_observability(app, service_name="administrative-operations")
configure_telemetry(app, service_name="administrative-operations")

__all__ = ["app"]
