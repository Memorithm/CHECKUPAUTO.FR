import tempfile
import unittest
from pathlib import Path

import compliance_admin
import compliance_operations


class ComplianceAdminSnapshotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "compliance.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def activity(self, **overrides):
        payload = {
            "name": "Gestion des rendez-vous",
            "role": "controller",
            "purposes": ["Planifier et exécuter les contrôles techniques"],
            "dataCategories": ["coordonnées", "données véhicule"],
            "dataSubjects": ["clients"],
            "legalBases": ["contrat"],
            "recipients": ["équipe du centre"],
            "transfers": [],
            "retention": "Durée documentée dans la politique de conservation applicable",
            "securityControls": ["contrôle d'accès", "journalisation"],
            "systems": ["CheckupAuto", "Mercure"],
            "owner": "Responsable conformité",
            "riskLevel": "standard",
            "dpiaStatus": "not_required",
            "reviewDueAt": "2099-12-31",
            "status": "active",
        }
        payload.update(overrides)
        return payload

    def test_empty_processing_register_fails_closed(self):
        state = compliance_admin.snapshot(self.db)
        self.assertFalse(state["summary"]["operationalRegistersReady"])
        self.assertIn(
            "processing_register_missing",
            {item["type"] for item in state["summary"]["operationalBlockers"]},
        )
        self.assertFalse(state["summary"]["readyForPublicContracting"])
        self.assertEqual(state["operations"]["summary"]["activeActivityCount"], 0)

    def test_complete_activity_makes_operational_register_ready(self):
        compliance_operations.upsert_processing_activity(self.activity(), self.db)
        state = compliance_admin.snapshot(self.db)
        self.assertTrue(state["summary"]["operationalRegistersReady"])
        self.assertEqual(state["summary"]["operationalBlockers"], [])
        self.assertIn("settings", state)
        self.assertIn("documentTypes", state)
        # Contracting remains blocked by the existing CGV/withdrawal gates.
        self.assertFalse(state["summary"]["readyForPublicContracting"])

    def test_high_risk_pending_dpia_is_visible_in_same_snapshot(self):
        compliance_operations.upsert_processing_activity(
            self.activity(riskLevel="high", dpiaStatus="required_pending"), self.db
        )
        state = compliance_admin.snapshot(self.db)
        self.assertFalse(state["summary"]["operationalRegistersReady"])
        self.assertIn(
            "dpia_unresolved",
            {item["type"] for item in state["summary"]["operationalBlockers"]},
        )


if __name__ == "__main__":
    unittest.main()
