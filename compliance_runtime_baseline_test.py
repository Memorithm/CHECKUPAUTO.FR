import importlib.util
import tempfile
import unittest
from pathlib import Path

import compliance_operations as ops
import compliance_register_attestation as register_attestation

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("compliance_seed",ROOT/"scripts/checkupauto-compliance-seed-baseline.py")
seed=importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)

class ComplianceRuntimeBaselineTest(unittest.TestCase):
    def test_baseline_covers_real_processing_without_claiming_external_dpa(self):
        data=seed.load_baseline()
        self.assertGreaterEqual(len(data["processingActivities"]),5)
        names={x["id"] for x in data["processingActivities"]}
        for expected in (
            "customer_identity_accounts",
            "booking_payment_mercure",
            "customer_inspection_summary",
            "notifications_marketing",
            "compliance_rights_withdrawal",
        ):
            self.assertIn(expected,names)
        self.assertTrue(all(
            x["riskLevel"]=="standard" and x["dpiaStatus"]=="not_required"
            for x in data["processingActivities"]
        ))
        processors={x["id"]:x for x in data["processors"]}
        self.assertEqual(processors["autobilan_mercure"]["dpaStatus"],"pending")
        self.assertEqual(processors["planethoster"]["dpaStatus"],"pending")

    def test_apply_is_idempotent_and_replaces_missing_inventory_with_exact_pending_dpa_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"compliance.sqlite3"
            first=seed.apply(db)
            second=seed.apply(db)
            self.assertEqual(first["activityCount"],5)
            self.assertEqual(first["processorCount"],2)
            self.assertEqual(len(ops.processing_activities(db)),5)
            self.assertEqual(len(ops.processors(db)),2)
            self.assertEqual(first["blockerTypes"],["processor_dpa_pending"])
            self.assertEqual(second["blockerTypes"],["processor_dpa_pending"])
            self.assertFalse(first["operationalRegistersReady"])
            self.assertTrue(first["externalEvidencePending"])

    def test_seeded_register_matches_reviewed_baseline_canonically(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"compliance.sqlite3"
            seed.apply(db)
            data=seed.load_baseline()
            expected={
                "schema":"checkupauto.operational-registers.v1",
                "processingActivities":sorted(
                    data["processingActivities"],
                    key=lambda row:str(row.get("id") or ""),
                ),
                "processors":sorted(
                    data["processors"],
                    key=lambda row:str(row.get("id") or ""),
                ),
            }
            self.assertEqual(register_attestation.register_payload(db),expected)

    def test_output_does_not_claim_external_contracts_are_satisfied(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/"compliance.sqlite3"
            result=seed.apply(db)
            self.assertNotIn("signed",str(result).lower())
            self.assertTrue(result["externalEvidencePending"])

if __name__=="__main__":
    unittest.main()
