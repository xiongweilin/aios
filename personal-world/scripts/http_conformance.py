from __future__ import annotations

import argparse
import json
import time
from uuid import uuid4

import httpx


def request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    token: str,
    purpose: str,
    json_body: object | None = None,
) -> httpx.Response:
    response = client.request(
        method,
        path,
        headers={
            "X-Service-Identity": "administrative-orchestrator",
            "X-Purpose": purpose,
            "Authorization": f"Bearer {token}",
        },
        json=json_body,
    )
    response.raise_for_status()
    return response


def wait_ready(client: httpx.Client) -> None:
    last: Exception | None = None
    for _ in range(50):
        try:
            response = client.get("/healthz")
            if response.status_code == 200:
                return
        except Exception as exc:  # pragma: no cover - only exercised on startup races
            last = exc
        time.sleep(0.1)
    raise RuntimeError("Personal World did not become ready") from last


def run(base_url: str, token: str) -> None:
    with httpx.Client(base_url=base_url, timeout=5.0) as client:
        wait_ready(client)

        contracts = request(client, "GET", "/v1/contracts", token=token, purpose="conformance").json()
        assert contracts["manifest"] == "personal-world-contracts-v1"
        assert contracts["package"] == "1.0.0"
        assert contracts["conformance"] == "personal-world-conformance-v1"
        assert contracts["semantic_language"] == "0.2.0"

        request(
            client,
            "PUT",
            "/v1/access-profiles",
            token=token,
            purpose="admin",
            json_body={
                "service_identity": "administrative-orchestrator",
                "allowed_purposes": ["*"],
                "allowed_kinds": ["fact", "preference", "relationship", "resource-link"],
                "max_sensitivity": 30,
            },
        )

        subject = str(uuid4())
        source = request(
            client,
            "POST",
            "/v1/sources",
            token=token,
            purpose="personal-context-write",
            json_body={
                "source_class": "human-explicit",
                "actor_ref": "human:self",
                "description": "conformance correction",
                "metadata": {},
            },
        ).json()

        fact = request(
            client,
            "POST",
            "/v1/facts",
            token=token,
            purpose="personal-context-write",
            json_body={
                "subject_id": subject,
                "semantic": {
                    "kind": "predicate",
                    "id": "home-city",
                    "namespace": "personal",
                    "version": "0.1",
                },
                "value": "Tokyo",
                "source_refs": [source["id"]],
            },
        ).json()

        projection = request(
            client,
            "POST",
            "/v1/context-projections",
            token=token,
            purpose="personal-context-read",
            json_body={"subject_id": subject, "purpose": "personal-context-read"},
        ).json()
        assert [item["value"] for item in projection["included_items"]] == ["Tokyo"]

        revised = request(
            client,
            "POST",
            f"/v1/records/{fact['id']}/revise",
            token=token,
            purpose="personal-context-write",
            json_body={
                "expected_revision": 1,
                "value": "Osaka",
                "source_refs": [source["id"]],
                "qualification_reason": "human correction",
            },
        ).json()
        assert revised["revision"] == 2

        projection = request(
            client,
            "POST",
            "/v1/context-projections",
            token=token,
            purpose="personal-context-read",
            json_body={"subject_id": subject, "purpose": "personal-context-read"},
        ).json()
        assert [item["value"] for item in projection["included_items"]] == ["Osaka"]

        request(
            client,
            "POST",
            "/v1/erasures",
            token=token,
            purpose="admin",
            json_body={"subject_id": subject, "reason": "conformance erasure"},
        )

        projection = request(
            client,
            "POST",
            "/v1/context-projections",
            token=token,
            purpose="personal-context-read",
            json_body={"subject_id": subject, "purpose": "personal-context-read"},
        ).json()
        assert projection["included_items"] == []
        assert projection["contested_items"] == []
        assert projection["stale_items"] == []

        bundle = request(client, "GET", "/v1/bundle", token=token, purpose="admin").json()
        serialized = json.dumps(bundle, ensure_ascii=False)
        assert "Tokyo" not in serialized
        assert "Osaka" not in serialized


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8090")
    parser.add_argument("--token", required=True)
    args = parser.parse_args()
    run(args.base_url, args.token)


if __name__ == "__main__":
    main()
