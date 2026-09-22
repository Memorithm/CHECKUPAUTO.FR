from __future__ import annotations

import json
import unittest
from unittest import mock

import compliance_admin_http


class ComplianceAdminHTTPTest(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "activityId": "high-risk-ai-assistance",
            "expectedActivityHash": "a" * 64,
            "securityStatus": "approved",
            "privacyStatus": "approved",
            "evidence": "internal-review-reference:2026-09-22",
        }
        self.review = {
            "activityId": "high-risk-ai-assistance",
            "name": "Assistance automatisée à risque élevé",
            "currentActivityHash": "a" * 64,
            "reviewedActivityHash": "a" * 64,
            "securityStatus": "approved",
            "privacyStatus": "approved",
            "stale": False,
            "reviewedAt": "2026-09-22T17:00:00+00:00",
            "sourceEvidenceHash": "b" * 64,
            "reviewEvidenceHash": "c" * 64,
        }

    def test_success_preserves_bounded_review_without_raw_evidence(self):
        with mock.patch.object(
            compliance_admin_http.compliance_admin,
            "review_high_risk_processing",
            return_value=self.review,
        ) as action:
            status, body = compliance_admin_http.review_high_risk_processing(self.payload)
        self.assertEqual(status, 201)
        self.assertEqual(body, {"ok": True, "review": self.review})
        action.assert_called_once_with(self.payload)
        self.assertNotIn(self.payload["evidence"], json.dumps(body, sort_keys=True))

    def test_unknown_activity_is_sanitized(self):
        with mock.patch.object(
            compliance_admin_http.compliance_admin,
            "review_high_risk_processing",
            side_effect=LookupError("activité de traitement inconnue"),
        ):
            status, body = compliance_admin_http.review_high_risk_processing(self.payload)
        self.assertEqual(status, 404)
        self.assertEqual(body, {"ok": False, "error": "compliance_processing_review_not_found"})

    def test_stale_or_incompatible_activity_is_conflict(self):
        with mock.patch.object(
            compliance_admin_http.compliance_admin,
            "review_high_risk_processing",
            side_effect=RuntimeError("l'activité a changé depuis la revue"),
        ):
            status, body = compliance_admin_http.review_high_risk_processing(self.payload)
        self.assertEqual(status, 409)
        self.assertEqual(body, {"ok": False, "error": "compliance_processing_review_conflict"})

    def test_invalid_payload_is_sanitized(self):
        with mock.patch.object(
            compliance_admin_http.compliance_admin,
            "review_high_risk_processing",
            side_effect=ValueError("empreinte d'activité invalide"),
        ):
            status, body = compliance_admin_http.review_high_risk_processing(self.payload)
        self.assertEqual(status, 400)
        self.assertEqual(body, {"ok": False, "error": "compliance_processing_review_invalid"})

    def test_unexpected_failure_does_not_leak_internal_error(self):
        marker = "database-path:/private/runtime.sqlite3"
        with mock.patch.object(
            compliance_admin_http.compliance_admin,
            "review_high_risk_processing",
            side_effect=OSError(marker),
        ):
            status, body = compliance_admin_http.review_high_risk_processing(self.payload)
        self.assertEqual(status, 500)
        self.assertEqual(body, {"ok": False, "error": "compliance_processing_review_failed"})
        self.assertNotIn(marker, json.dumps(body, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
