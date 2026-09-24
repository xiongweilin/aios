from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from administrative_orchestrator.observability import install_observability


def _app() -> FastAPI:
    app = FastAPI()
    install_observability(app, service_name="m5-observability-test")

    @app.get("/ok")
    def ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/operations/cases/case-1/authoritative-facts/refresh")
    def refresh() -> dict[str, str]:
        return {"status": "refreshed"}

    @app.post("/v1/operations/identities/bind")
    def bind() -> dict[str, str]:
        return {"status": "bound"}

    return app


def test_correlation_id_is_propagated_without_becoming_metric_cardinality():
    client = TestClient(_app())

    response = client.get("/ok", headers={"X-Correlation-ID": "case.trace-42"})

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "case.trace-42"


def test_invalid_correlation_id_is_replaced():
    client = TestClient(_app())

    response = client.get("/ok", headers={"X-Correlation-ID": "contains spaces"})

    assert response.status_code == 200
    generated = response.headers["X-Correlation-ID"]
    assert generated
    assert generated != "contains spaces"


def test_metrics_expose_bounded_http_and_semantic_series():
    client = TestClient(_app())
    assert client.post("/v1/operations/cases/case-1/authoritative-facts/refresh").status_code == 200
    assert client.post("/v1/operations/identities/bind").status_code == 200

    metrics = client.get("/metrics").text

    assert "administrative_http_requests_total" in metrics
    assert "administrative_http_request_duration_seconds" in metrics
    assert "administrative_authoritative_fact_refresh_total" in metrics
    assert "administrative_identity_lifecycle_total" in metrics
    assert "case.trace-42" not in metrics
