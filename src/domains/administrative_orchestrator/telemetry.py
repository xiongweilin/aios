from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

_INSTRUMENTED = False


def configure_telemetry(app: FastAPI, service_name: str = "administrative-api") -> bool:
    """Attach OTLP tracing when an OTLP endpoint is configured.

    Without OTEL_EXPORTER_OTLP_ENDPOINT this is a no-op, so local runs, tests and
    CI behave exactly as before. Returns True when instrumentation was applied.
    """
    global _INSTRUMENTED
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return False
    # 按规范，OTEL_EXPORTER_OTLP_ENDPOINT 是 base URL，但显式
    # exporter constructor 不会像 SDK 的
    # env-var handling 那样自动追加 signal path。
    endpoint = endpoint.rstrip("/")
    if not endpoint.endswith("/v1/traces"):
        endpoint = f"{endpoint}/v1/traces"
    if _INSTRUMENTED:
        return True

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {SERVICE_NAME: os.getenv("OTEL_SERVICE_NAME", service_name)}
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()

    _INSTRUMENTED = True
    return True
