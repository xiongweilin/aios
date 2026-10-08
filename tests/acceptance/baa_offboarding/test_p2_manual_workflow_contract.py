"""Static guard for the manual-only BAA P2 model replay workflow.

This test does not dispatch a run or call the model, and therefore cannot
replace runtime source qualification or privacy review.
"""
from pathlib import Path
import unittest

WORKFLOW = (
    Path(__file__).resolve().parents[3]
    / ".github/workflows/baa-p2-readonly-maintenance-model-replay-v1.yml"
)


class P2ManualReadOnlyWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_manual_only_with_explicit_opt_in_and_bounded_calls(self):
        s = self.workflow
        self.assertIn("on:\n  workflow_dispatch:", s)
        self.assertNotIn("\n  pull_request:", s)
        self.assertNotIn("\n  push:", s)
        self.assertNotIn("\n  schedule:", s)
        self.assertIn("approve_finite_model_sampling:", s)
        self.assertIn('default: "no"', s)
        self.assertIn("if ($env:APPROVAL -ne \"yes\")", s)
        self.assertIn("--max-calls 96", s)
        self.assertIn("timeout-minutes: 180", s)
        self.assertIn("cancel-in-progress: false", s)

    def test_pin_bytes_and_refuse_model_until_source_qualified(self):
        s = self.workflow
        self.assertIn(
            "82370d7991eea9c288126610594a208efff06baa", s
        )
        self.assertIn("11526016609", s)
        self.assertIn(
            "dfafd340bd3a10f2c4768c578b908cad1756e6f1009e3c5b153d49046ec16b60",
            s,
        )
        self.assertIn("Get-FileHash -Algorithm SHA256", s)
        self.assertIn("--qualify-source-only", s)
        self.assertIn("--source-zip", s)
        self.assertLess(
            s.index("Offline source projection and P2 tool qualification"),
            s.index("Require already available local model gateway"),
        )
        self.assertLess(
            s.index("Require already available local model gateway"),
            s.index("Run finite real-model three-regime archived evidence replay"),
        )

    def test_model_network_scoped_to_own_loopback_and_no_prod_actions(self):
        s = self.workflow
        self.assertIn("BAA_GATEWAY_BASE: http://127.0.0.1:4101", s)
        self.assertIn("runs-on: [self-hosted, windows, x64]", s)
        self.assertIn("permissions:\n  contents: read\n  actions: read", s)
        self.assertNotIn("docker compose", s)
        self.assertNotIn("keycloak_base", s)
        self.assertNotIn("odoo_base", s)
        self.assertNotIn("secrets.PRODUCTION_", s)
        self.assertNotIn("secrets.KEYCLOAK_", s)
        self.assertIn("real_product_actions = 0", s)
        self.assertIn("Remove-Item -LiteralPath $env:BAA_SOURCE_ZIP", s)

    def test_all_expected_denominators_and_noncausal_guards(self):
        s = self.workflow
        self.assertIn("@($d.episodes).Count -ne 45", s)
        self.assertIn("$d.source_qualification.qualified -ne $true", s)
        self.assertIn("$d.randomized_episode_assignment -ne $false", s)
        self.assertIn(
            "$d.statistical_external_validity_qualified -ne $false", s
        )
        self.assertIn("$d.actual_principal_attention_observed -ne $false", s)


if __name__ == "__main__":
    unittest.main()
