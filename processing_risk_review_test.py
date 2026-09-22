from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import compliance_operations
import compliance_store
import processing_risk_review


class ProcessingRiskReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "compliance.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def activity(self, **overrides):
        payload = {
            "name": "Profilage de rappel à risque élevé",
            "role": "controller",
            "purposes": ["Prioriser les rappels véhicule"],
            "dataCategories": ["coordonnées", "données véhicule"],
            "dataSubjects": ["clients"],
            "legalBases": ["intérêt légitime documenté"],
            "recipients": ["équipe CheckupAuto"],
            "transfers": [],
            "retention": "Politique de conservation documentée",
            "securityControls": ["contrôle d'accès", "journalisation"],
            "systems": ["CheckupAuto"],
            "owner": "Responsable conformité",
            "riskLevel": "high",
            "dpiaStatus": "approved",
            "reviewDueAt": "2099-12-31",
            "status": "active",
        }
        payload.update(overrides)
        return payload

    def create_activity(self):
        return compliance_operations.upsert_processing_activity(self.activity(), self.db)

    def test_missing_reviews_fail_closed_for_high_risk_activity(self):
        activity = self.create_activity()
        state = processing_risk_review.status(self.db)

        self.assertTrue(state["required"])
        self.assertFalse(state["ready"])
        self.assertEqual(state["highRiskActivityCount"], 1)
        row = state["activities"][0]
        self.assertEqual(row["activityId"], activity["id"])
        self.assertEqual(row["securityStatus"], "not_reviewed")
        self.assertEqual(row["privacyStatus"], "not_reviewed")
        blockers = {item["type"] for item in state["blockers"]}
        self.assertIn("processing_security_review_not_approved", blockers)
        self.assertIn("processing_privacy_review_not_approved", blockers)

    def test_review_rejects_stale_activity_hash(self):
        activity = self.create_activity()
        current = processing_risk_review.activity_hash(activity)
        stale = ("0" if current[0] != "0" else "1") + current[1:]

        with self.assertRaises(RuntimeError):
            processing_risk_review.record_review(
                activity["id"],
                expected_activity_hash=stale,
                security_status="approved",
                privacy_status="approved",
                evidence=b"review-evidence",
                db_path=self.db,
            )

        state = processing_risk_review.status(self.db)
        self.assertEqual(state["reviewedActivityCount"], 0)
        self.assertFalse(state["ready"])

    def test_approved_review_is_bounded_and_does_not_persist_raw_evidence(self):
        activity = self.create_activity()
        raw_evidence = b"security-and-privacy-review-sensitive-reference"
        current = processing_risk_review.activity_hash(activity)

        state = processing_risk_review.record_review(
            activity["id"],
            expected_activity_hash=current,
            security_status="approved",
            privacy_status="approved",
            evidence=raw_evidence,
            db_path=self.db,
        )

        self.assertTrue(state["ready"])
        self.assertEqual(state["blockers"], [])
        row = state["activities"][0]
        self.assertEqual(row["currentActivityHash"], current)
        self.assertEqual(row["reviewedActivityHash"], current)
        self.assertEqual(row["securityStatus"], "approved")
        self.assertEqual(row["privacyStatus"], "approved")
        self.assertFalse(row["stale"])
        self.assertNotIn(raw_evidence.decode(), str(state))
        self.assertFalse(state["rawEvidencePersisted"])

        with compliance_store.connect(self.db) as db:
            stored = dict(db.execute("SELECT * FROM processing_risk_review").fetchone())
        self.assertNotIn(raw_evidence.decode(), str(stored))
        self.assertEqual(len(stored["source_evidence_hash"]), 64)
        self.assertEqual(len(stored["review_evidence_hash"]), 64)

    def test_activity_edit_invalidates_previous_review(self):
        activity = self.create_activity()
        current = processing_risk_review.activity_hash(activity)
        processing_risk_review.record_review(
            activity["id"],
            expected_activity_hash=current,
            security_status="approved",
            privacy_status="approved",
            evidence=b"review-evidence",
            db_path=self.db,
        )

        compliance_operations.upsert_processing_activity(
            self.activity(id=activity["id"], systems=["CheckupAuto", "ReminderEngine"]),
            self.db,
        )
        state = processing_risk_review.status(self.db)

        self.assertFalse(state["ready"])
        self.assertTrue(state["activities"][0]["stale"])
        self.assertIn(
            "processing_risk_review_stale",
            {item["type"] for item in state["blockers"]},
        )

    def test_changes_required_remains_blocking(self):
        activity = self.create_activity()
        current = processing_risk_review.activity_hash(activity)
        state = processing_risk_review.record_review(
            activity["id"],
            expected_activity_hash=current,
            security_status="changes_required",
            privacy_status="approved",
            evidence=b"review-evidence",
            db_path=self.db,
        )

        self.assertFalse(state["ready"])
        self.assertIn(
            "processing_security_review_not_approved",
            {item["type"] for item in state["blockers"]},
        )
        self.assertNotIn(
            "processing_privacy_review_not_approved",
            {item["type"] for item in state["blockers"]},
        )


if __name__ == "__main__":
    unittest.main()
