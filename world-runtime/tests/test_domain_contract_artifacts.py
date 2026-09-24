from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from semantic_language import Responsibility

from world_runtime import WorldRuntime
from world_runtime.contracts import contract_schema, domain_conformance_vectors
from world_runtime.domain_protocol import DomainReportCommand
from world_runtime.domains import DomainAssignment
from world_runtime.service import create_app


def test_domain_contract_schemas_are_canonical_and_strict() -> None:
    assignment = contract_schema("domain_assignment")
    report = contract_schema("domain_report")

    assert assignment["title"] == "DomainAssignment v3"
    assert assignment["additionalProperties"] is False
    assert report["title"] == "DomainReport v3"
    assert report["additionalProperties"] is False
    assert "id" in report["required"]
    assert report["$defs"]["evidenceRef"]["properties"]["kind"]["const"] == "evidence"
    assert report["$defs"]["outcomeRef"]["properties"]["kind"]["const"] == "outcome"


def _client_for_state(state: str) -> tuple[TestClient, str]:
    runtime = WorldRuntime.sqlite()
    runtime.identity.bind_bearer_token(
        principal="controller:test-domain",
        token="domain-contract-token",
        credential_id="credential:domain-contract",
    )
    responsibility = Responsibility(
        id=f"responsibility:vector:{state}",
        principal="controller:test",
        subject="protocol vector",
    )
    runtime.responsibility.create(responsibility, domain="test-domain")
    assignment = DomainAssignment(
        id=f"assignment:vector:{state}",
        responsibility_ref=responsibility.id,
        domain="test-domain",
        controller="controller:test-domain",
    )
    runtime.domains.offer(assignment)
    if state == "active":
        runtime.domains.report(
            assignment.id,
            kind="accepted",
            report_id=f"{assignment.id}:accepted",
        )
    return TestClient(
        create_app(runtime),
        headers={"Authorization": "Bearer domain-contract-token"},
    ), assignment.id


def test_domain_protocol_vectors_are_executable_across_schema_http_and_runtime() -> None:
    suite = domain_conformance_vectors()
    assert suite["runtime_protocol"] == "4.0"
    assert suite["contracts"]["domain_assignment"] == "domain-assignment-v3"
    assert suite["contracts"]["domain_report"] == "domain-report-v3"

    schema = contract_schema("domain_report")
    validator = Draft202012Validator(schema)

    for vector in suite["vectors"]:
        payload = vector["payload"]
        expect = vector["expect"]

        schema_errors = list(validator.iter_errors(payload))
        try:
            DomainReportCommand.model_validate(payload)
        except ValidationError:
            pydantic_valid = False
        else:
            pydantic_valid = True

        if expect == "validation-error":
            assert schema_errors, vector["id"]
            assert pydantic_valid is False, vector["id"]
            client, assignment_id = _client_for_state(vector.get("from", "offered"))
            response = client.post(
                f"/v1/domain-assignments/{assignment_id}/reports",
                json=payload,
            )
            assert response.status_code == 422, vector["id"]
            continue

        assert schema_errors == [], vector["id"]
        assert pydantic_valid is True, vector["id"]
        client, assignment_id = _client_for_state(vector.get("from", "offered"))
        response = client.post(
            f"/v1/domain-assignments/{assignment_id}/reports",
            json=payload,
        )
        if expect == "semantic-error":
            assert response.status_code == 409, vector["id"]
        else:
            assert expect == "accepted", vector["id"]
            assert response.status_code == 200, vector["id"]


def test_domain_protocol_vectors_cover_required_failure_classes() -> None:
    ids = {item["id"] for item in domain_conformance_vectors()["vectors"]}
    assert {
        "positive-accepted",
        "report-id-required",
        "extra-field-rejected",
        "unknown-universal-kind-rejected",
        "outcome-candidate-evidence-is-typed",
        "outcome-candidate-outcome-is-namespaced",
        "rejected-only-from-offered",
        "completion-requires-active",
    } <= ids
