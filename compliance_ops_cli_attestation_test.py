import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import compliance_operations
import compliance_register_attestation as attestation


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "scripts" / "checkupauto-compliance-ops.py"


class ComplianceOpsCliAttestationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "compliance.sqlite3"
        compliance_operations.upsert_processing_activity(
            {
                "name": "Gestion des rendez-vous",
                "role": "controller",
                "purposes": ["Planifier les contrôles techniques"],
                "dataCategories": ["coordonnées"],
                "dataSubjects": ["clients"],
                "legalBases": ["contrat"],
                "recipients": ["équipe du centre"],
                "transfers": [],
                "retention": "Durée documentée",
                "securityControls": ["contrôle d'accès"],
                "systems": ["CheckupAuto"],
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

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--db", str(self.db), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_attest_requires_reviewed_hash_argument(self):
        result = self.run_cli("attest", "--confirm", "CURRENT-REGISTERS-REVIEWED")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--expected-hash", result.stderr)
        self.assertEqual(attestation.status(self.db)["attestationCount"], 0)

    def test_attest_accepts_hash_returned_by_status(self):
        status_result = self.run_cli("attestation-status")
        self.assertEqual(status_result.returncode, 0, status_result.stderr)
        digest = json.loads(status_result.stdout)["currentRegisterHash"]
        result = self.run_cli(
            "attest",
            "--confirm",
            "CURRENT-REGISTERS-REVIEWED",
            "--expected-hash",
            digest,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertTrue(state["current"])
        self.assertEqual(state["attestedRegisterHash"], digest)


if __name__ == "__main__":
    unittest.main()
