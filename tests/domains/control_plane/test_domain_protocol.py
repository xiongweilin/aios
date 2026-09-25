from pathlib import Path

import pytest

from control_plane.runtime_bridge import WorldRuntimeBoundaryError, WorldRuntimeClient
from tests.domain_harness import make_harness
from tests.runtime_stub import contract_mismatch_transport


def test_personal_profile_creates_durable_domain_assignment(tmp_path: Path) -> None:
    harness = make_harness(tmp_path)
    try:
        state, _ = harness.bridge.begin(
            title="Investigate checkout alert",
            description="Determine whether checkout requires intervention",
            kind="incident",
            project="checkout",
        )

        assignment_id = f"control-plane-assignment:{state.responsibility_ref}"
        assignment = harness.stub.assignments[assignment_id]
        assert assignment["domain"] == "control-plane"
        assert assignment["controller"] == "controller:control-plane"
        assert assignment["status"] == "active"
        reports = [
            payload
            for method, path, payload in harness.stub.calls
            if method == "POST" and path == f"/v1/domain-assignments/{assignment_id}/reports"
        ]
        assert [item["kind"] for item in reports] == ["accepted"]
    finally:
        harness.close()


def test_runtime_handshake_fails_closed_on_protocol_mismatch() -> None:
    client = WorldRuntimeClient(
        "http://world-runtime",
        transport=contract_mismatch_transport(),
    )
    try:
        with pytest.raises(WorldRuntimeBoundaryError, match="protocol mismatch"):
            client.ensure_contracts()
    finally:
        client.close()
