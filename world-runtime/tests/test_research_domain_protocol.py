from fastapi.testclient import TestClient

from world_runtime import WorldRuntime
from world_runtime.service import create_app


def test_new_research_controller_uses_public_protocol_without_runtime_changes() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="runtime:research-protocol")
    runtime.identity.bind_bearer_token(
        principal="controller:research",
        token="research-runtime-token",
        credential_id="credential:research",
    )
    app = create_app(runtime)

    with TestClient(
        app,
        headers={"Authorization": "Bearer research-runtime-token"},
    ) as client:
        response = client.post(
            "/v1/responsibilities",
            json={
                "id": "responsibility:research-1",
                "principal": "controller:research",
                "subject": "determine whether hypothesis H is supported",
                "domain": "research",
                "scope": {"topic": "H"},
            },
        )
        assert response.status_code == 200

        response = client.post(
            "/v1/domain-assignments",
            json={
                "id": "research-assignment:1",
                "responsibility_ref": "responsibility:research-1",
                "domain": "research",
                "controller": "controller:research",
                "evidence_requirements": [{"kind": "primary-source"}],
                "review_conditions": [{"trigger": "material-counterevidence"}],
            },
        )
        assert response.status_code == 200

        response = client.post(
            "/v1/domain-assignments/research-assignment:1/reports",
            json={"id": "research-report:accepted", "kind": "accepted"},
        )
        assert response.status_code == 200

        response = client.post(
            "/v1/domain-assignments/research-assignment:1/reports",
            json={
                "id": "research-report:outcome",
                "kind": "outcome-candidate",
                "basis_refs": [
                    {
                        "kind": "paper",
                        "id": "paper:1",
                        "namespace": "research",
                        "version": "0.1",
                    }
                ],
                "evidence_refs": [
                    {
                        "kind": "evidence",
                        "id": "evidence:paper-1",
                        "namespace": "universal",
                        "version": "0.1",
                    }
                ],
                "outcome_refs": [
                    {
                        "kind": "outcome",
                        "id": "h-supported",
                        "namespace": "research",
                        "version": "0.1",
                    }
                ],
                "detail": {"confidence_class": "supported"},
            },
        )
        assert response.status_code == 200

    assignment = runtime.domains.get("research-assignment:1")
    assert assignment.status == "active"
    assert [report.kind for report in runtime.domains.reports(assignment.id)] == [
        "accepted",
        "outcome-candidate",
    ]
