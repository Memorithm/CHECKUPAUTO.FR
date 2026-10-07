import importlib.util
import tempfile
import unittest
from pathlib import Path

import compliance_operations as operations

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "dpa_transition",
    ROOT / "scripts/checkupauto-compliance-transition-dpa-review.py",
)
transition = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transition)


class ComplianceDpaReviewTransitionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "compliance.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def processor(self, **overrides):
        payload = {
            "id": "autobilan_mercure",
            "name": "AutoBilan-Systems / Mercure",
            "service": "Mercure",
            "dpaStatus": "pending",
            "dpaEvidenceSha256": "",
            "hostingLocation": "France",
            "transferRequired": False,
            "transferMechanism": "",
            "subprocessors": [],
            "reviewDueAt": "2099-12-31",
            "status": "active",
        }
        payload.update(overrides)
        return payload

    def test_pending_transitions_to_reviewed_insufficient_without_dpa_evidence(self):
        operations.upsert_processor(self.processor(), self.db)
        result = transition.transition("autobilan_mercure", self.db)
        self.assertEqual(result["state"], "transitioned")
        self.assertEqual(result["previousStatus"], "pending")
        self.assertEqual(result["currentStatus"], "reviewed_insufficient")
        row = operations.processors(self.db)[0]
        self.assertEqual(row["dpaStatus"], "reviewed_insufficient")
        self.assertEqual(row["dpaEvidenceSha256"], "")
        blockers = {item["type"] for item in operations.summary(self.db)["blockers"]}
        self.assertEqual(blockers, {"processor_dpa_insufficient"})

    def test_transition_is_idempotent(self):
        operations.upsert_processor(
            self.processor(dpaStatus="reviewed_insufficient"),
            self.db,
        )
        result = transition.transition("autobilan_mercure", self.db)
        self.assertEqual(result["state"], "already_target")
        self.assertEqual(result["currentStatus"], "reviewed_insufficient")

    def test_signed_dpa_is_never_downgraded(self):
        operations.upsert_processor(
            self.processor(dpaStatus="signed", dpaEvidenceSha256="a" * 64),
            self.db,
        )
        result = transition.transition("autobilan_mercure", self.db)
        self.assertEqual(result["state"], "already_resolved")
        self.assertEqual(result["currentStatus"], "signed")
        row = operations.processors(self.db)[0]
        self.assertEqual(row["dpaStatus"], "signed")
        self.assertEqual(row["dpaEvidenceSha256"], "a" * 64)

    def test_not_required_is_never_downgraded(self):
        operations.upsert_processor(
            self.processor(dpaStatus="not_required"),
            self.db,
        )
        result = transition.transition("autobilan_mercure", self.db)
        self.assertEqual(result["state"], "already_resolved")
        self.assertEqual(result["currentStatus"], "not_required")

    def test_missing_processor_fails_closed(self):
        with self.assertRaisesRegex(LookupError, "processor not found"):
            transition.transition("autobilan_mercure", self.db)


if __name__ == "__main__":
    unittest.main()
