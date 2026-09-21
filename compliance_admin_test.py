import tempfile
import unittest
from pathlib import Path

import compliance_admin
import compliance_operations
import compliance_store


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

    def test_withdrawal_ready_still_fails_closed_for_remaining_phase2_controls(self):
        identity = {key: "value" for key in compliance_store.SETTINGS_FIELDS}
        identity.update({
            "controllerName": "Example SAS",
            "legalForm": "SAS",
            "registeredAddress": "1 rue Exemple, 75000 Paris",
            "registrationId": "RCS PARIS 000 000 000",
            "publicationDirector": "Direction",
            "contactEmail": "contact@example.test",
            "privacyContact": "privacy@example.test",
            "mediatorName": "Médiateur test",
            "mediatorUrl": "https://example.test/mediation",
            "hostName": "Hébergeur test",
            "hostAddress": "2 rue Exemple, 75000 Paris",
            "approvalAuthority": "Autorité compétente test",
        })
        compliance_store.save_settings(identity, self.db)
        for doc_type, meta in compliance_store.DOCUMENT_TYPES.items():
            compliance_store.save_document({
                "type": doc_type,
                "version": "1.0",
                "title": meta["label"],
                "body": ("Document juridiquement validé pour le test. " * 6) + doc_type,
                "action": "publish",
            }, self.db)
        compliance_operations.upsert_processing_activity(self.activity(), self.db)

        state = compliance_admin.snapshot(self.db)
        self.assertTrue(state["summary"]["checkoutAcceptanceBound"])
        self.assertTrue(state["summary"]["withdrawalFunctionBound"])
        self.assertTrue(state["summary"]["operationalRegistersReady"])
        self.assertFalse(state["summary"]["dataSubjectExecutionBound"])
        self.assertFalse(state["summary"]["retentionEnforcementBound"])
        self.assertFalse(state["summary"]["readyForPublicContracting"])
        self.assertEqual(state["withdrawal"]["path"], "/retractation")

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
