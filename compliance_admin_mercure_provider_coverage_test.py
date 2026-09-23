import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import compliance_admin
import mercure_provider_coverage


class ComplianceAdminMercureProviderCoverageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "compliance.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def provider_env(self, history_start="", future_days="", evidence_sha256=""):
        return {
            mercure_provider_coverage.HISTORY_START_ENV: history_start,
            mercure_provider_coverage.FUTURE_DAYS_ENV: future_days,
            mercure_provider_coverage.EVIDENCE_SHA256_ENV: evidence_sha256,
        }

    def test_unconfigured_provider_boundary_is_visible_and_fail_closed(self):
        with mock.patch.dict(os.environ, self.provider_env(), clear=False):
            state = compliance_admin.snapshot(self.db)

        coverage = state["mercureProviderCoverage"]
        self.assertEqual(coverage["boundary"]["state"], "unconfigured")
        self.assertFalse(coverage["boundary"]["attested"])
        self.assertEqual(
            coverage["boundary"]["reason"],
            "provider_boundary_not_attested",
        )
        self.assertTrue(coverage["capability"]["requiresExplicitProviderBoundary"])
        self.assertTrue(coverage["capability"]["requiresAuthoritativeSourceEvidence"])
        self.assertFalse(coverage["capability"]["rawEvidenceStoredInRepository"])
        self.assertFalse(state["summary"]["mercureProviderCoverageAttested"])
        self.assertEqual(state["summary"]["mercureProviderCoverageState"], "unconfigured")

    def test_attested_boundary_exposes_only_bounded_non_secret_state(self):
        evidence_hash = "a" * 64
        with mock.patch.dict(
            os.environ,
            self.provider_env(
                history_start="2020-01-01",
                future_days="730",
                evidence_sha256=evidence_hash,
            ),
            clear=False,
        ):
            state = compliance_admin.snapshot(self.db)

        coverage = state["mercureProviderCoverage"]
        self.assertEqual(coverage["boundary"]["state"], "attested")
        self.assertTrue(coverage["boundary"]["attested"])
        self.assertEqual(coverage["boundary"]["historyStart"], "2020-01-01")
        self.assertEqual(coverage["boundary"]["futureDays"], 730)
        self.assertEqual(coverage["boundary"]["evidenceSha256"], evidence_hash)
        self.assertEqual(coverage["boundary"]["reason"], "")
        self.assertEqual(
            set(coverage["boundary"]),
            {"state", "attested", "historyStart", "futureDays", "evidenceSha256", "reason"},
        )
        self.assertTrue(state["summary"]["mercureProviderCoverageAttested"])
        self.assertEqual(state["summary"]["mercureProviderCoverageState"], "attested")
        self.assertNotIn("provider contract body", repr(coverage))

    def test_invalid_partial_boundary_is_reported_without_becoming_attested(self):
        with mock.patch.dict(
            os.environ,
            self.provider_env(history_start="2020-01-01", future_days="365"),
            clear=False,
        ):
            state = compliance_admin.snapshot(self.db)

        coverage = state["mercureProviderCoverage"]
        self.assertEqual(coverage["boundary"]["state"], "invalid")
        self.assertFalse(coverage["boundary"]["attested"])
        self.assertEqual(
            coverage["boundary"]["reason"],
            "provider_boundary_configuration_incomplete",
        )
        self.assertFalse(state["summary"]["mercureProviderCoverageAttested"])
        self.assertEqual(state["summary"]["mercureProviderCoverageState"], "invalid")


if __name__ == "__main__":
    unittest.main()
