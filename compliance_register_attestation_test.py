import tempfile
import unittest
from pathlib import Path

import compliance_operations
import compliance_register_attestation as attestation


class ComplianceRegisterAttestationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "compliance.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def activity(self, **overrides):
        payload = {
            "name": "Gestion des rendez-vous",
            "role": "controller",
            "purposes": ["Planifier les contrôles techniques"],
            "dataCategories": ["coordonnées", "données véhicule"],
            "dataSubjects": ["clients"],
            "legalBases": ["contrat"],
            "recipients": ["équipe du centre"],
            "transfers": [],
            "retention": "Durée documentée",
            "securityControls": ["contrôle d'accès"],
            "systems": ["CheckupAuto", "Mercure"],
            "owner": "Responsable conformité",
            "riskLevel": "standard",
            "dpiaStatus": "not_required",
            "reviewDueAt": "2099-12-31",
            "status": "active",
        }
        payload.update(overrides)
        return payload

    def processor(self, **overrides):
        payload = {
            "name": "Prestataire documenté",
            "service": "Service externe documenté",
            "dpaStatus": "signed",
            "hostingLocation": "France",
            "transferRequired": False,
            "transferMechanism": "",
            "subprocessors": [],
            "reviewDueAt": "2099-12-31",
            "status": "active",
        }
        payload.update(overrides)
        return payload

    def seed_ready_registers(self):
        compliance_operations.upsert_processing_activity(self.activity(), self.db)
        compliance_operations.upsert_processor(self.processor(), self.db)

    def test_attestation_requires_non_empty_ready_registers(self):
        with self.assertRaises(RuntimeError):
            attestation.attest(self.db)
        compliance_operations.upsert_processing_activity(self.activity(), self.db)
        with self.assertRaises(RuntimeError):
            attestation.attest(self.db)

    def test_attestation_matches_current_content_hash(self):
        self.seed_ready_registers()
        state = attestation.attest(self.db)
        self.assertTrue(state["current"])
        self.assertFalse(state["stale"])
        self.assertEqual(state["currentRegisterHash"], state["attestedRegisterHash"])
        self.assertEqual(len(state["currentRegisterHash"]), 64)
        self.assertEqual(len(state["evidenceHash"]), 64)
        self.assertEqual(state["attestationCount"], 1)

    def test_substantive_register_change_invalidates_attestation(self):
        self.seed_ready_registers()
        first = attestation.attest(self.db)
        activity = compliance_operations.processing_activities(self.db)[0]
        compliance_operations.upsert_processing_activity(
            self.activity(id=activity["id"], retention="Durée documentée révisée"), self.db
        )
        state = attestation.status(self.db)
        self.assertFalse(state["current"])
        self.assertTrue(state["stale"])
        self.assertNotEqual(first["attestedRegisterHash"], state["currentRegisterHash"])

    def test_volatile_timestamps_do_not_define_register_hash(self):
        self.seed_ready_registers()
        before = attestation.register_hash(self.db)
        activity = compliance_operations.processing_activities(self.db)[0]
        compliance_operations.upsert_processing_activity(self.activity(id=activity["id"]), self.db)
        after = attestation.register_hash(self.db)
        self.assertEqual(before, after)

    def test_blocked_register_cannot_be_attested(self):
        compliance_operations.upsert_processing_activity(
            self.activity(riskLevel="high", dpiaStatus="required_pending"), self.db
        )
        compliance_operations.upsert_processor(self.processor(), self.db)
        with self.assertRaises(RuntimeError):
            attestation.attest(self.db)


if __name__ == "__main__":
    unittest.main()
