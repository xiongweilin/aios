"""Offline P3 protected-resource contract tests (no Keycloak needed)."""
from __future__ import annotations

import io
import json
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("P3_INTROSPECTION_CLIENT_ID", "test-verifier")
os.environ.setdefault("P3_INTROSPECTION_CLIENT_SECRET", "test-secret")
os.environ.setdefault("P3_ALLOWED_BEARER_CLIENT_ID", "baa-session-client")

import p3_protected_resource as resource  # noqa: E402


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


class OnlineIntrospectionTests(unittest.TestCase):
    def _read(self, payload):
        with patch.object(
            resource.urllib.request,
            "urlopen",
            return_value=FakeResponse(json.dumps(payload).encode("utf-8")),
        ):
            return resource.inspect("test-bearer-never-logged")

    def test_correct_active_session_client_and_subject_allows(self):
        outcome, body = self._read({
            "active": True,
            "client_id": "baa-session-client",
            "sub": "isolated-user-id",
        })
        self.assertEqual(outcome, "ALLOW")
        self.assertEqual(body["subject"], "isolated-user-id")

    def test_disabled_or_revoked_token_denied(self):
        outcome, _ = self._read({"active": False})
        self.assertEqual(outcome, "DENY")

    def test_active_but_wrong_client_or_subject_denied(self):
        for payload in (
            {"active": True, "client_id": "other", "sub": "isolated-user-id"},
            {"active": True, "client_id": "baa-session-client"},
        ):
            with self.subTest(payload=payload):
                outcome, _ = self._read(payload)
                self.assertEqual(outcome, "DENY")

    def test_network_failure_and_unknown_state_not_accepted_as_denial(self):
        with patch.object(
            resource.urllib.request, "urlopen",
            side_effect=resource.urllib.error.URLError("down")
        ):
            result = resource.inspect("token")
        self.assertEqual(result[0], "UNKNOWN")

        outcome, _ = self._read({"error": "invalid_token"})
        self.assertEqual(outcome, "UNKNOWN")

    def test_no_raw_token_returned_on_success_or_denial(self):
        decision, reply = self._read({
            "active": True,
            "client_id": "baa-session-client",
            "sub": "isolated-user-id",
            "access_token": "sensitive",
        })
        self.assertEqual(decision, "ALLOW")
        self.assertNotIn("access_token", reply)
        self.assertNotIn("sensitive", str(reply))


if __name__ == "__main__":
    unittest.main()
