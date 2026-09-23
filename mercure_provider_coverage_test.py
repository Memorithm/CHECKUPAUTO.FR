import datetime
import os
import unittest
from unittest.mock import patch

import mercure_provider_coverage as coverage


class MercureProviderCoverageTest(unittest.TestCase):
    def setUp(self):
        self.today = datetime.date(2026, 9, 23)

    def _env(self, **values):
        base = {
            coverage.HISTORY_START_ENV: "",
            coverage.FUTURE_DAYS_ENV: "",
            coverage.EVIDENCE_SHA256_ENV: "",
        }
        base.update(values)
        return patch.dict(os.environ, base, clear=False)

    def test_unconfigured_boundary_never_claims_attestation(self):
        with self._env():
            result = coverage.boundary(self.today)
        self.assertEqual(result["state"], "unconfigured")
        self.assertFalse(result["attested"])
        self.assertEqual(result["reason"], "provider_boundary_not_attested")

    def test_complete_evidence_backed_boundary_is_attested(self):
        digest = "a" * 64
        with self._env(**{
            coverage.HISTORY_START_ENV: "2018-04-12",
            coverage.FUTURE_DAYS_ENV: "180",
            coverage.EVIDENCE_SHA256_ENV: digest,
        }):
            result = coverage.boundary(self.today)
        self.assertEqual(result, {
            "state": "attested",
            "attested": True,
            "historyStart": "2018-04-12",
            "futureDays": 180,
            "evidenceSha256": digest,
            "reason": "",
        })

    def test_partial_configuration_fails_closed_without_reflecting_values(self):
        with self._env(**{coverage.HISTORY_START_ENV: "2018-04-12"}):
            result = coverage.boundary(self.today)
        self.assertEqual(result["state"], "invalid")
        self.assertFalse(result["attested"])
        self.assertEqual(result["historyStart"], "")
        self.assertEqual(result["evidenceSha256"], "")

    def test_invalid_dates_horizon_and_evidence_fail_closed(self):
        cases = [
            ("not-a-date", "1", "a" * 64, "provider_history_start_invalid"),
            ("2027-01-01", "1", "a" * 64, "provider_history_start_in_future"),
            ("2020-01-01", "nope", "a" * 64, "provider_future_horizon_invalid"),
            ("2020-01-01", "3651", "a" * 64, "provider_future_horizon_out_of_range"),
            ("2020-01-01", "30", "secret-not-a-digest", "provider_evidence_hash_invalid"),
        ]
        for start, future, evidence, reason in cases:
            with self.subTest(reason=reason), self._env(**{
                coverage.HISTORY_START_ENV: start,
                coverage.FUTURE_DAYS_ENV: future,
                coverage.EVIDENCE_SHA256_ENV: evidence,
            }):
                result = coverage.boundary(self.today)
                self.assertEqual(result["state"], "invalid")
                self.assertFalse(result["attested"])
                self.assertEqual(result["reason"], reason)
                self.assertNotIn("secret-not-a-digest", repr(result))

    def test_capability_refuses_empty_result_as_exhaustion_proof(self):
        result = coverage.capability()
        self.assertTrue(result["requiresExplicitProviderBoundary"])
        self.assertTrue(result["requiresExternalEvidenceSha256"])
        self.assertFalse(result["rawEvidenceStoredInRepository"])
        self.assertFalse(result["emptyResultProvesHistoricalExhaustion"])


if __name__ == "__main__":
    unittest.main()
