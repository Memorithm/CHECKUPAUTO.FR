from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest import mock

import compliance_admin


class ComplianceAdminProcessingReviewTest(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "activityId": "high-risk-ai-assistance",
            "expectedActivityHash": "a" * 64,
            "securityStatus": "approved",
            "privacyStatus": "approved",
            "evidence": "internal-review-reference:2026-09-22",
        }
        self.core_state = {
            "ready": True,
            "blockerCount": 0,
            "activities": [
                {
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
            ],
        }

    def test_forwards_reviewed_digest_and_evidence_to_core_without_reflecting_evidence(self):
        db_path = Path("/tmp/compliance-admin-processing-review.sqlite3")
        with mock.patch.object(
            compliance_admin.processing_risk_review,
            "record_review",
            return_value=self.core_state,
        ) as record_review:
            result = compliance_admin.review_high_risk_processing(self.payload, db_path)

        record_review.assert_called_once_with(
            "high-risk-ai-assistance",
            expected_activity_hash="a" * 64,
            security_status="approved",
            privacy_status="approved",
            evidence="internal-review-reference:2026-09-22",
            db_path=db_path,
        )
        self.assertEqual(result["activityId"], "high-risk-ai-assistance")
        self.assertEqual(result["currentActivityHash"], "a" * 64)
        self.assertEqual(result["sourceEvidenceHash"], "b" * 64)
        self.assertNotIn(self.payload["evidence"], json.dumps(result, sort_keys=True))
        self.assertNotIn("evidence", result)

    def test_rejects_extra_fields_before_calling_core(self):
        payload = dict(self.payload, operatorNote="must not cross trust boundary")
        with mock.patch.object(
            compliance_admin.processing_risk_review,
            "record_review",
        ) as record_review:
            with self.assertRaises(ValueError):
                compliance_admin.review_high_risk_processing(payload)
        record_review.assert_not_called()

    def test_rejects_missing_fields_before_calling_core(self):
        payload = dict(self.payload)
        del payload["expectedActivityHash"]
        with mock.patch.object(
            compliance_admin.processing_risk_review,
            "record_review",
        ) as record_review:
            with self.assertRaises(ValueError):
                compliance_admin.review_high_risk_processing(payload)
        record_review.assert_not_called()

    def test_stale_activity_conflict_from_core_is_preserved(self):
        with mock.patch.object(
            compliance_admin.processing_risk_review,
            "record_review",
            side_effect=RuntimeError("l'activité a changé depuis la revue"),
        ):
            with self.assertRaisesRegex(RuntimeError, "changé depuis la revue"):
                compliance_admin.review_high_risk_processing(self.payload)

    def test_missing_review_row_fails_closed(self):
        with mock.patch.object(
            compliance_admin.processing_risk_review,
            "record_review",
            return_value={"ready": False, "blockerCount": 1, "activities": []},
        ):
            with self.assertRaisesRegex(RuntimeError, "preuve de revue"):
                compliance_admin.review_high_risk_processing(self.payload)


if __name__ == "__main__":
    unittest.main()
