from __future__ import annotations

from fastapi.testclient import TestClient

from world_runtime import WorldRuntime
from world_runtime.identity import DelegationGrant
from world_runtime.service import create_app


OWNER = {"Authorization": "Bearer owner-token"}
OTHER = {"Authorization": "Bearer other-token"}
CONTROLLER = {"Authorization": "Bearer controller-token"}


def _runtime_client() -> tuple[WorldRuntime, TestClient]:
    runtime = WorldRuntime.sqlite(
        runtime_id="runtime:protocol-3-acceptance",
        root_principal="principal:owner",
    )
    runtime.identity.bind_bearer_token(
        principal="principal:owner",
        token="owner-token",
        credential_id="credential:owner",
    )
    runtime.identity.bind_bearer_token(
        principal="principal:other",
        token="other-token",
        credential_id="credential:other",
    )
    runtime.identity.bind_bearer_token(
        principal="controller:domain",
        token="controller-token",
        credential_id="credential:controller",
    )
    return runtime, TestClient(create_app(runtime))


def _post_decision(
    client: TestClient,
    *,
    decision_id: str,
    target_ref: str,
    operation: str,
    selected: dict[str, object] | None = None,
) -> None:
    payload = {
        "id": decision_id,
        "subject": target_ref,
        "decided_by": "principal:owner",
        "selected": {
            "target_ref": target_ref,
            "operation": operation,
            **dict(selected or {}),
        },
        "basis_refs": [f"evidence:{decision_id}"],
    }
    response = client.post("/v1/decisions", json=payload, headers=OWNER)
    assert response.status_code == 200, response.text


def _create_owner_responsibility(client: TestClient, identifier: str) -> None:
    response = client.post(
        "/v1/responsibilities",
        json={
            "id": identifier,
            "principal": "principal:owner",
            "subject": identifier,
            "domain": "integration",
            "scope": {},
        },
        headers=OWNER,
    )
    assert response.status_code == 200, response.text


def _create_owner_mandate(client: TestClient, identifier: str) -> None:
    response = client.post(
        "/v1/mandates",
        json={
            "id": identifier,
            "principal": "principal:owner",
            "scope": {"subject": "company"},
            "authority_ceiling": {"action": "*", "resource": "*"},
        },
        headers=OWNER,
    )
    assert response.status_code == 200, response.text


def test_protocol_3_strategy_lifecycle_is_authenticated_decision_bound_and_unit_safe() -> None:
    runtime, client = _runtime_client()
    try:
        _create_owner_mandate(client, "mandate:strategy")
        _create_owner_responsibility(client, "responsibility:strategy")

        issue_response = client.post(
            "/v1/strategy/issues",
            json={
                "id": "strategy-issue:1",
                "subject": "company",
                "question": "Which bounded strategy should be active?",
                "mandate_id": "mandate:strategy",
                "basis_refs": ["evidence:strategy-issue"],
            },
            headers=OWNER,
        )
        assert issue_response.status_code == 200, issue_response.text
        assert issue_response.json()["principal"] == "principal:owner"

        assert client.get("/v1/strategy/issues/strategy-issue:1").status_code == 401
        assert (
            client.get(
                "/v1/strategy/issues/strategy-issue:1",
                headers=OTHER,
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/v1/strategy/issues/strategy-issue:1",
                headers=OWNER,
            ).json()["status"]
            == "open"
        )

        option_response = client.post(
            "/v1/strategy/issues/strategy-issue:1/options",
            json={
                "id": "strategic-option:1",
                "hypothesis": {"path": "measured-growth"},
                "evaluation": {
                    "evidence_summary": "bounded upside with lower uncertainty",
                    "risk_class": "moderate",
                },
                "basis_refs": ["evidence:option"],
            },
            headers=OWNER,
        )
        assert option_response.status_code == 200, option_response.text
        assert option_response.json()["evaluation"]["risk_class"] == "moderate"

        proposal_response = client.post(
            "/v1/strategy/issues/strategy-issue:1/portfolio-proposals",
            json={
                "id": "portfolio-proposal:1",
                "option_ids": ["strategic-option:1"],
                "goal_refs": [],
                "resource_budget": {
                    "cash": {"amount": 100.0, "unit": "CNY"},
                },
                "basis_refs": ["evidence:portfolio-proposal"],
            },
            headers=OWNER,
        )
        assert proposal_response.status_code == 200, proposal_response.text

        no_decision = client.post(
            "/v1/strategy/portfolio-proposals/portfolio-proposal:1/activate",
            json={"id": "portfolio:1", "decision_id": "decision:missing"},
            headers=OWNER,
        )
        assert no_decision.status_code == 404

        _post_decision(
            client,
            decision_id="decision:activate",
            target_ref="portfolio-proposal:1",
            operation="activate-portfolio",
        )
        activated = client.post(
            "/v1/strategy/portfolio-proposals/portfolio-proposal:1/activate",
            json={"id": "portfolio:1", "decision_id": "decision:activate"},
            headers=OWNER,
        )
        assert activated.status_code == 200, activated.text
        assert activated.json()["resource_budget"] == {
            "cash": {"amount": 100.0, "unit": "CNY"}
        }
        assert client.get("/v1/strategy/portfolios/portfolio:1").status_code == 401
        assert (
            client.get("/v1/strategy/portfolios/portfolio:1", headers=OWNER).status_code
            == 200
        )

        _post_decision(
            client,
            decision_id="decision:wrong-unit",
            target_ref="portfolio:1",
            operation="allocate-resource",
            selected={
                "responsibility_id": "responsibility:strategy",
                "resource_type": "cash",
                "amount": 10.0,
                "unit": "USD",
            },
        )
        wrong_unit = client.post(
            "/v1/strategy/portfolios/portfolio:1/allocations",
            json={
                "id": "allocation:wrong-unit",
                "responsibility_id": "responsibility:strategy",
                "resource_type": "cash",
                "amount": 10.0,
                "unit": "USD",
                "decision_id": "decision:wrong-unit",
                "basis_refs": ["evidence:allocation"],
            },
            headers=OWNER,
        )
        assert wrong_unit.status_code == 409

        _post_decision(
            client,
            decision_id="decision:allocate",
            target_ref="portfolio:1",
            operation="allocate-resource",
            selected={
                "responsibility_id": "responsibility:strategy",
                "resource_type": "cash",
                "amount": 40.0,
                "unit": "CNY",
            },
        )
        allocation = client.post(
            "/v1/strategy/portfolios/portfolio:1/allocations",
            json={
                "id": "allocation:1",
                "responsibility_id": "responsibility:strategy",
                "resource_type": "cash",
                "amount": 40.0,
                "unit": "CNY",
                "decision_id": "decision:allocate",
                "basis_refs": ["evidence:allocation"],
            },
            headers=OWNER,
        )
        assert allocation.status_code == 200, allocation.text
        assert allocation.json()["unit"] == "CNY"

        _post_decision(
            client,
            decision_id="decision:close-too-early",
            target_ref="strategy-issue:1",
            operation="close-strategic-issue",
        )
        close_early = client.post(
            "/v1/strategy/issues/strategy-issue:1/close",
            json={
                "decision_id": "decision:close-too-early",
                "basis_refs": ["evidence:close"],
            },
            headers=OWNER,
        )
        assert close_early.status_code == 409

        _post_decision(
            client,
            decision_id="decision:retire",
            target_ref="portfolio:1",
            operation="retire-portfolio",
        )
        retired = client.post(
            "/v1/strategy/portfolios/portfolio:1/retire",
            json={
                "decision_id": "decision:retire",
                "basis_refs": ["evidence:retire"],
            },
            headers=OWNER,
        )
        assert retired.status_code == 200, retired.text
        assert retired.json()["status"] == "retired"

        _post_decision(
            client,
            decision_id="decision:close",
            target_ref="strategy-issue:1",
            operation="close-strategic-issue",
        )
        closed = client.post(
            "/v1/strategy/issues/strategy-issue:1/close",
            json={
                "decision_id": "decision:close",
                "basis_refs": ["evidence:close"],
            },
            headers=OWNER,
        )
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "closed"
    finally:
        client.close()
        runtime.close()


def test_protocol_3_continuous_qualification_requires_explicit_resolution() -> None:
    runtime, client = _runtime_client()
    try:
        registered = client.post(
            "/v1/qualification/dependencies",
            json={
                "id": "qualification-dependency:1",
                "principal": "principal:owner",
                "subject_ref": "decision:historical",
                "dependency_ref": "policy:risk",
                "dependency_version": "v1",
                "assumption": "risk policy remains applicable",
                "scope": {"use": "current-decision"},
                "review_policy": {"on_change": "reauthorize"},
                "basis_refs": ["evidence:policy-v1"],
            },
            headers=OWNER,
        )
        assert registered.status_code == 200, registered.text

        forged = client.post(
            "/v1/qualification/dependencies",
            json={
                "principal": "principal:owner",
                "subject_ref": "decision:forged",
                "dependency_ref": "policy:risk",
                "dependency_version": "v1",
                "assumption": "forged",
                "basis_refs": ["evidence:forged"],
            },
            headers=OTHER,
        )
        assert forged.status_code == 403

        changed = client.post(
            "/v1/qualification/changes",
            json={
                "dependency_ref": "policy:risk",
                "observed_version": "v2",
                "basis_refs": ["evidence:policy-v2"],
                "reason": "policy changed",
            },
            headers=OWNER,
        )
        assert changed.status_code == 200, changed.text
        review = changed.json()["reviews"][0]
        assert review["status"] == "open"
        review_id = review["id"]

        listed = client.get("/v1/qualification/reviews", headers=OWNER)
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["reviews"]] == [review_id]
        assert client.get("/v1/qualification/reviews").status_code == 401

        assessed = client.post(
            f"/v1/qualification/reviews/{review_id}/assess",
            json={
                "id": "qualification-assessment:1",
                "disposition": "reauthorize",
                "basis_refs": ["evidence:review"],
                "rationale": "authority basis materially changed",
            },
            headers=OWNER,
        )
        assert assessed.status_code == 200, assessed.text
        assert assessed.json()["review"]["status"] == "assessed"

        pending = client.get("/v1/qualification/reviews", headers=OWNER).json()["reviews"]
        assert pending[0]["status"] == "assessed"

        premature_advance = client.post(
            "/v1/qualification/dependencies/qualification-dependency:1/advance",
            json={
                "obligation_id": review_id,
                "assessment_id": "qualification-assessment:1",
                "new_version": "v2",
                "basis_refs": ["evidence:new-basis"],
                "successor_id": "qualification-dependency:2",
            },
            headers=OWNER,
        )
        assert premature_advance.status_code == 409

        resolved = client.post(
            f"/v1/qualification/reviews/{review_id}/resolve",
            json={
                "resolution_ref": "authorization:replacement",
                "basis_refs": ["evidence:reauthorized"],
            },
            headers=OWNER,
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["status"] == "resolved"

        advanced = client.post(
            "/v1/qualification/dependencies/qualification-dependency:1/advance",
            json={
                "obligation_id": review_id,
                "assessment_id": "qualification-assessment:1",
                "new_version": "v2",
                "basis_refs": ["evidence:new-basis"],
                "successor_id": "qualification-dependency:2",
            },
            headers=OWNER,
        )
        assert advanced.status_code == 200, advanced.text
        assert advanced.json()["dependency_version"] == "v2"
        assert client.get("/v1/qualification/reviews", headers=OWNER).json() == {
            "reviews": []
        }
    finally:
        client.close()
        runtime.close()


def test_protocol_3_state_and_domain_reads_enforce_ownership_boundaries() -> None:
    runtime, client = _runtime_client()
    try:
        _create_owner_responsibility(client, "responsibility:domain")
        owner_context = runtime.identity.authenticate_bearer("Bearer owner-token")
        runtime.identity.grant_delegation(
            DelegationGrant(
                id="delegation:domain",
                grantor="principal:owner",
                grantee="controller:domain",
                scope={"resource": "*"},
                authority_ceiling={"action": "*", "resource": "*"},
            ),
            context=owner_context,
        )

        offered = client.post(
            "/v1/domain-assignments",
            json={
                "id": "domain-assignment:1",
                "responsibility_ref": "responsibility:domain",
                "domain": "integration",
                "controller": "controller:domain",
            },
            headers=OWNER,
        )
        assert offered.status_code == 200, offered.text

        assert client.get("/v1/responsibilities/responsibility:domain").status_code == 401
        assert (
            client.get(
                "/v1/responsibilities/responsibility:domain",
                headers=OTHER,
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/v1/responsibilities/responsibility:domain",
                headers=OWNER,
            ).status_code
            == 200
        )

        relations_path = "/v1/responsibilities/responsibility:domain/relations"
        assert client.get(relations_path).status_code == 401
        assert client.get(relations_path, headers=OTHER).status_code == 403
        relations = client.get(relations_path, headers=OWNER)
        assert relations.status_code == 200
        assert relations.json() == {"relations": []}

        assert client.get("/v1/domain-assignments/domain-assignment:1").status_code == 401
        assert (
            client.get(
                "/v1/domain-assignments/domain-assignment:1",
                headers=OTHER,
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/v1/domain-assignments/domain-assignment:1",
                headers=CONTROLLER,
            ).status_code
            == 200
        )

        accepted = client.post(
            "/v1/domain-assignments/domain-assignment:1/reports",
            json={"id": "domain-report:accepted", "kind": "accepted"},
            headers=CONTROLLER,
        )
        assert accepted.status_code == 200, accepted.text
        assert (
            client.get(
                "/v1/domain-assignments/domain-assignment:1/reports",
                headers=CONTROLLER,
            ).json()["reports"][0]["kind"]
            == "accepted"
        )
        assert (
            client.post(
                "/v1/domain-assignments/domain-assignment:1/reports",
                json={"id": "domain-report:forged", "kind": "progress"},
                headers=OWNER,
            ).status_code
            == 403
        )

        root_export = client.get("/v1/state/export", headers=OWNER)
        assert root_export.status_code == 200
        assert client.get("/v1/state/export", headers=OTHER).status_code == 403
        delegated_headers = {
            "Authorization": "Bearer controller-token",
            "X-World-Runtime-Delegation": "delegation:domain",
        }
        assert client.get("/v1/state/export", headers=delegated_headers).status_code == 403
        assert client.get("/v1/capabilities").status_code == 401
        assert client.get("/v1/capabilities", headers=OWNER).status_code == 200

        unknown = client.post(
            "/v1/responsibilities",
            json={
                "id": "responsibility:unknown-field",
                "principal": "principal:owner",
                "subject": "closed schema",
                "domain": "integration",
                "provider_specific_mode": "green",
            },
            headers=OWNER,
        )
        assert unknown.status_code == 422
        assert runtime.ledger.project_get(
            "responsibility.current",
            "responsibility:unknown-field",
        ) is None
    finally:
        client.close()
        runtime.close()


def test_protocol_3_whole_agency_state_is_disabled_without_configured_root() -> None:
    runtime = WorldRuntime.sqlite(runtime_id="runtime:no-root")
    runtime.identity.bind_bearer_token(
        principal="principal:owner",
        token="owner-token",
        credential_id="credential:no-root-owner",
    )
    client = TestClient(create_app(runtime))
    try:
        assert client.get("/v1/state/export", headers=OWNER).status_code == 403
        assert (
            client.post(
                "/v1/state/import",
                json=runtime.state_bundle.export(),
                headers=OWNER,
            ).status_code
            == 403
        )
    finally:
        client.close()
        runtime.close()


def test_protocol_3_every_durable_v1_get_route_declares_request_context() -> None:
    runtime, client = _runtime_client()
    try:
        public_gets = {
            "/v1/contracts",
            "/v1/contracts/vectors",
        }
        for route in client.app.routes:
            methods = getattr(route, "methods", set())
            path = getattr(route, "path", "")
            if "GET" not in methods or not path.startswith("/v1/") or path in public_gets:
                continue
            endpoint = getattr(route, "endpoint", None)
            parameters = getattr(getattr(endpoint, "__signature__", None), "parameters", None)
            if parameters is None:
                import inspect

                parameters = inspect.signature(endpoint).parameters
            assert {"request", "http_request"} & set(parameters), (
                f"durable GET route {path} must declare an authenticated Request context"
            )
    finally:
        client.close()
        runtime.close()
