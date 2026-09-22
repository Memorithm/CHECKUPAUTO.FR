import tempfile
import unittest
from pathlib import Path

import compliance_admin
import compliance_operations
import compliance_register_attestation


class ComplianceAdminAttestationActionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "compliance.sqlite3"
        compliance_operations.upsert_processing_activity(
            {
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
            },
            self.db,
        )
        compliance_operations.upsert_processor(
            {
                "name": "Prestataire documenté",
                "service": "Service externe documenté",
                "dpaStatus": "signed",
                "hostingLocation": "France",
                "transferRequired": False,
                "transferMechanism": "",
                "subprocessors": [],
                "reviewDueAt": "2099-12-31",
                "status": "active",
            },
            self.db,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self, digest=None):
        return {
            "confirm": compliance_admin.REGISTER_REVIEW_CONFIRMATION,
            "expectedRegisterHash": digest or compliance_register_attestation.register_hash(self.db),
        }

    def test_exact_confirmation_and_digest_create_current_attestation(self):
        reviewed = compliance_register_attestation.register_hash(self.db)
        state = compliance_admin.attest_operational_registers(self.payload(reviewed), self.db)
        self.assertTrue(state["current"])
        self.assertFalse(state["stale"])
        self.assertEqual(state["currentRegisterHash"], reviewed)
        self.assertEqual(state["attestedRegisterHash"], reviewed)
        self.assertEqual(state["attestationCount"], 1)
        self.assertEqual(len(state["evidenceHash"]), 64)
        self.assertTrue(state["reviewedAt"])

    def test_confirmation_is_required(self):
        payload = self.payload()
        payload["confirm"] = "YES"
        with self.assertRaisesRegex(PermissionError, "confirmation"):
            compliance_admin.attest_operational_registers(payload, self.db)
        self.assertEqual(compliance_register_attestation.status(self.db)["attestationCount"], 0)

    def test_extra_payload_fields_are_rejected(self):
        payload = self.payload()
        payload["operatorEmail"] = "operator@example.test"
        with self.assertRaisesRegex(ValueError, "payload"):
            compliance_admin.attest_operational_registers(payload, self.db)
        self.assertEqual(compliance_register_attestation.status(self.db)["attestationCount"], 0)

    def test_stale_review_digest_is_rejected_without_attestation(self):
        reviewed = compliance_register_attestation.register_hash(self.db)
        activity = compliance_operations.processing_activities(self.db)[0]
        compliance_operations.upsert_processing_activity(
            {
                "id": activity["id"],
                "name": activity["name"],
                "role": activity["role"],
                "purposes": activity["purposes"],
                "dataCategories": activity["dataCategories"],
                "dataSubjects": activity["dataSubjects"],
                "legalBases": activity["legalBases"],
                "recipients": activity["recipients"],
                "transfers": activity["transfers"],
                "retention": "Durée modifiée après affichage",
                "securityControls": activity["securityControls"],
                "systems": activity["systems"],
                "owner": activity["owner"],
                "riskLevel": activity["riskLevel"],
                "dpiaStatus": activity["dpiaStatus"],
                "reviewDueAt": activity["reviewDueAt"],
                "status": activity["status"],
            },
            self.db,
        )
        with self.assertRaisesRegex(RuntimeError, "changé"):
            compliance_admin.attest_operational_registers(self.payload(reviewed), self.db)
        self.assertEqual(compliance_register_attestation.status(self.db)["attestationCount"], 0)

    def test_response_does_not_echo_operator_payload(self):
        state = compliance_admin.attest_operational_registers(self.payload(), self.db)
        self.assertEqual(
            set(state),
            {
                "current",
                "stale",
                "currentRegisterHash",
                "attestedRegisterHash",
                "reviewedAt",
                "evidenceHash",
                "attestationCount",
            },
        )
        serialized = str(state)
        self.assertNotIn(compliance_admin.REGISTER_REVIEW_CONFIRMATION, serialized)


if __name__ == "__main__":
    unittest.main()
