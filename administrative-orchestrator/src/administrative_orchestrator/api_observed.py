from __future__ import annotations

from .api import app
from .observability import install_observability
from .telemetry import configure_telemetry

install_observability(app, service_name="administrative-api")
configure_telemetry(app, service_name="administrative-api")

__all__ = ["app"]
