from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import compliance_store
import referral_wallet_lifecycle
import rights_completion_plan


SUBJECT = "11111111-1111-1111-1111-111111111111"


class MobileErasureCompletionPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "compliance.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, request_type="erasure"):
        return compliance_store.create_rights_request(
            {"type": request_type, "subjectRef": SUBJECT, "notes": ""},
            self.db_path,
        )

    def plan(self, mobile_disposition="required"):
        entries = []
        for adapter in rights_completion_plan._known_adapters("erasure"):
            if adapter == "mobile_installation":
                if mobile_disposition == "required":
                    entries.append({"adapter": adapter, "disposition": "required"})
                else:
                    entries.append(
                        {
                            "adapter": adapter,
                            "disposition": "not_applicable",
                            "justification": "aucune installation mobile applicable",
                        }
                    )
            else:
                entries.append(
                    {
                        "adapter": adapter,
                        "disposition": "not_applicable",
                        "justification": f"{adapter} hors périmètre du sujet mobile",
                    }
                )
        return entries

    @staticmethod
    def receipt(erased_at="9999-01-01T00:00:00+00:00"):
        return {
            "receiptId": "a" * 32,
            "evidenceHash": "b" * 64,
            "removed": {
                "deviceRecords": 1,
                "deadlineRecords": 2,
                "vehicleBindingRecords": 1,
            },
            "erasedAt": erased_at,
            "rawInstallationPersisted": False,
            "pushTokenPersisted": False,
            "registrationSecretPersisted": False,
        }

    def test_post_request_receipt_satisfies_required_mobile_erasure_item(self):
        request = self.request()
        with mock.patch.object(
            referral_wallet_lifecycle,
            "mobile_erasure_receipt_by_subject_hash",
            return_value=self.receipt(),
        ) as lookup:
            state = rights_completion_plan.configure(
                request["id"], self.plan(), self.db_path
            )

        mobile = next(
            item for item in state["items"]
            if item["adapter"] == "mobile_installation"
        )
        self.assertTrue(mobile["executed"])
        self.assertTrue(mobile["executionComplete"])
        self.assertTrue(mobile["satisfied"])
        self.assertEqual(mobile["executionEvidenceSource"], "mobile_erasure_receipt")
        self.assertEqual(mobile["executionEvidenceHash"], "b" * 64)
        self.assertTrue(state["knownScopeComplete"])
        self.assertFalse(state["globalCoverageComplete"])
        self.assertFalse(state["closureReady"])
        self.assertGreaterEqual(lookup.call_count, 1)
        subject_hash = compliance_store.create_rights_request.__module__
        self.assertNotEqual(subject_hash, SUBJECT)

    def test_receipt_preceding_request_is_not_completion_proof(self):
        request = self.request()
        with mock.patch.object(
            referral_wallet_lifecycle,
            "mobile_erasure_receipt_by_subject_hash",
            return_value=self.receipt("2000-01-01T00:00:00+00:00"),
        ):
            state = rights_completion_plan.configure(
                request["id"], self.plan(), self.db_path
            )

        mobile = next(
            item for item in state["items"]
            if item["adapter"] == "mobile_installation"
        )
        self.assertFalse(mobile["executed"])
        self.assertFalse(mobile["executionComplete"])
        self.assertFalse(mobile["satisfied"])
        self.assertEqual(mobile["executionEvidenceSource"], "")
        self.assertFalse(state["knownScopeComplete"])

    def test_receipt_backed_mobile_adapter_cannot_be_marked_not_applicable(self):
        request = self.request()
        with mock.patch.object(
            referral_wallet_lifecycle,
            "mobile_erasure_receipt_by_subject_hash",
            return_value=self.receipt(),
        ):
            with self.assertRaisesRegex(ValueError, "adaptateur exécuté"):
                rights_completion_plan.configure(
                    request["id"],
                    self.plan(mobile_disposition="not_applicable"),
                    self.db_path,
                )

    def test_non_erasure_plan_never_consumes_mobile_erasure_receipt(self):
        request = self.request("access")
        with mock.patch.object(
            referral_wallet_lifecycle,
            "mobile_erasure_receipt_by_subject_hash",
        ) as lookup:
            rights_completion_plan.status(request["id"], self.db_path)
        lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
