import tempfile
import unittest
from pathlib import Path

import compliance_operations as ops


class ComplianceOperationsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "compliance.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def activity_payload(self, **overrides):
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

    def processor_payload(self, **overrides):
        payload = {
            "name": "Prestataire exemple",
            "service": "Hébergement applicatif",
            "dpaStatus": "signed",
            "hostingLocation": "Lieu documenté par le contrat",
            "transferRequired": False,
            "transferMechanism": "",
            "subprocessors": [],
            "reviewDueAt": "2099-12-31",
            "status": "active",
        }
        payload.update(overrides)
        return payload

    def test_article_30_register_persists_required_operational_fields(self):
        saved = ops.upsert_processing_activity(self.activity_payload(), self.db)
        self.assertEqual(saved["name"], "Gestion des rendez-vous")
        self.assertEqual(saved["dataSubjects"], ["clients"])
        self.assertEqual(saved["systems"], ["CheckupAuto", "Mercure"])
        self.assertFalse(saved["reviewOverdue"])
        self.assertTrue(ops.summary(self.db)["operationalRegistersReady"])

    def test_high_risk_activity_blocks_until_dpia_is_approved(self):
        saved = ops.upsert_processing_activity(
            self.activity_payload(riskLevel="high", dpiaStatus="required_pending"), self.db
        )
        state = ops.summary(self.db)
        self.assertFalse(state["operationalRegistersReady"])
        self.assertIn("dpia_unresolved", {item["type"] for item in state["blockers"]})

        updated = self.activity_payload(
            id=saved["id"], riskLevel="high", dpiaStatus="approved"
        )
        ops.upsert_processing_activity(updated, self.db)
        self.assertTrue(ops.summary(self.db)["operationalRegistersReady"])

    def test_unscreened_active_activity_is_not_reported_ready(self):
        ops.upsert_processing_activity(self.activity_payload(dpiaStatus="not_screened"), self.db)
        state = ops.summary(self.db)
        self.assertFalse(state["operationalRegistersReady"])
        self.assertIn("dpia_not_screened", {item["type"] for item in state["blockers"]})

    def test_processor_inventory_tracks_dpa_transfer_and_subprocessors(self):
        saved = ops.upsert_processor(
            self.processor_payload(
                transferRequired=True,
                transferMechanism="Mécanisme contractuel documenté",
                subprocessors=["Sous-traitant déclaré"],
            ),
            self.db,
        )
        self.assertTrue(saved["transferRequired"])
        self.assertEqual(saved["subprocessors"], ["Sous-traitant déclaré"])
        self.assertTrue(ops.summary(self.db)["operationalRegistersReady"])

    def test_pending_dpa_blocks_operational_readiness(self):
        ops.upsert_processor(self.processor_payload(dpaStatus="pending"), self.db)
        state = ops.summary(self.db)
        self.assertFalse(state["operationalRegistersReady"])
        self.assertIn("processor_dpa_pending", {item["type"] for item in state["blockers"]})

    def test_transfer_required_rejects_non_boolean_json_values(self):
        with self.assertRaisesRegex(ValueError, "transferRequired doit être booléen"):
            ops.upsert_processor(self.processor_payload(transferRequired="false"), self.db)

    def test_transfer_marked_required_requires_documented_mechanism(self):
        with self.assertRaisesRegex(ValueError, "mécanisme de transfert requis"):
            ops.upsert_processor(
                self.processor_payload(transferRequired=True, transferMechanism=""), self.db
            )

    def test_overdue_reviews_block_readiness(self):
        ops.upsert_processing_activity(self.activity_payload(reviewDueAt="2000-01-01"), self.db)
        ops.upsert_processor(self.processor_payload(reviewDueAt="2000-01-01"), self.db)
        kinds = {item["type"] for item in ops.summary(self.db)["blockers"]}
        self.assertIn("activity_review_overdue", kinds)
        self.assertIn("processor_review_overdue", kinds)

    def test_audit_contains_hashes_not_registry_payloads(self):
        activity = ops.upsert_processing_activity(self.activity_payload(), self.db)
        processor = ops.upsert_processor(self.processor_payload(), self.db)
        events = ops.audit_events(self.db)
        self.assertEqual(len(events), 2)
        self.assertEqual({item["objectId"] for item in events}, {activity["id"], processor["id"]})
        for item in events:
            self.assertEqual(len(item["evidenceHash"]), 64)
            self.assertNotIn("payload", item)
            self.assertNotIn("dataCategories", item)


if __name__ == "__main__":
    unittest.main()
