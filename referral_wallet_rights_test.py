import tempfile
import unittest
from pathlib import Path

import analytics_store as analytics
import compliance_store
import data_subject_rights
import mobile_devices as devices
import referral_engine as referrals
import referral_wallet_claims as claims
import referral_wallet_rights as rights


class ReferralWalletRightsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_analytics_db = analytics.DB
        self.old_mobile_dir, self.old_mobile_db = devices.DATA_DIR, devices.DB
        analytics.DB = Path(self.tmp.name) / "analytics.sqlite3"
        devices.DATA_DIR = Path(self.tmp.name) / "mobile"
        devices.DB = devices.DATA_DIR / "devices.sqlite3"
        self.compliance_db = Path(self.tmp.name) / "compliance.sqlite3"
        analytics.init_db(); referrals.init_db(); claims.init_db()
        devices.init_db(); compliance_store.init_db(self.compliance_db)
        self.installation = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
        self.registration_value = "A" * 43
        devices.register_installation({
            "installationId": self.installation,
            "registrationSecret": self.registration_value,
        })
        self.account = referrals.create_account("RIGHTS-7K4P")
        token = claims.issue(self.account["code"])["claimToken"]
        claims.consume({
            "installationId": self.installation,
            "registrationSecret": self.registration_value,
            "claimToken": token,
        })

    def tearDown(self):
        analytics.DB = self.old_analytics_db
        devices.DATA_DIR, devices.DB = self.old_mobile_dir, self.old_mobile_db
        self.tmp.cleanup()

    def _request(self, request_type="access", subject=None):
        return compliance_store.create_rights_request(
            {"type": request_type, "subjectRef": subject or self.installation},
            self.compliance_db,
        )

    def test_access_export_requires_proven_owner_and_keeps_request_open(self):
        referrals.record_pending(
            self.account["code"],
            "mercure-rdv",
            "third-party-appointment-42",
            "intent-1",
        )
        request = self._request("access")
        result = rights.execute(
            request["id"], self.installation, self.account["id"], self.compliance_db
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["adapter"], "referral_wallet")
        self.assertEqual(result["requestStatus"], "in_progress")
        self.assertFalse(result["requestComplete"])
        self.assertEqual(result["data"]["account"]["accountId"], self.account["id"])
        self.assertEqual(result["data"]["wallet"]["balanceCents"], 0)
        self.assertEqual(result["data"]["wallet"]["pendingCents"], 500)
        rendered = str(result["data"])
        self.assertNotIn("third-party-appointment-42", rendered)
        self.assertNotIn("intent-1", rendered)
        self.assertFalse(result["data"]["thirdPartyAppointmentIdentifiersExposed"])
        refreshed = next(
            row for row in compliance_store.rights_requests(self.compliance_db)
            if row["id"] == request["id"]
        )
        self.assertEqual(refreshed["status"], "in_progress")
        self.assertEqual(refreshed["closedAt"], "")

    def test_portability_export_hashes_ledger_references(self):
        referrals.record_pending(self.account["code"], "mercure-rdv", "rdv-42", "intent-2")
        referrals.complete_control("mercure-rdv", "rdv-42")
        referrals.redeem(self.account["code"], 100, "ledger-reference-1")
        request = self._request("portability")
        result = rights.execute(
            request["id"], self.installation, self.account["id"], self.compliance_db
        )
        self.assertGreaterEqual(len(result["data"]["ledger"]), 2)
        rendered = str(result["data"]["ledger"])
        self.assertNotIn("ledger-reference-1", rendered)
        for entry in result["data"]["ledger"]:
            self.assertNotIn("reference", entry)
            self.assertRegex(entry["referenceHash"], r"^[0-9a-f]{64}$")

    def test_other_mobile_installation_cannot_export_wallet(self):
        other = "4fb1e2f8-fd94-49af-8642-b6aad6f6c721"
        request = self._request("access", subject=other)
        with self.assertRaises(PermissionError):
            rights.execute(request["id"], other, self.account["id"], self.compliance_db)

    def test_request_subject_must_be_the_owner_installation(self):
        request = self._request("access", subject="4fb1e2f8-fd94-49af-8642-b6aad6f6c721")
        with self.assertRaises(PermissionError):
            rights.execute(
                request["id"], self.installation, self.account["id"], self.compliance_db
            )

    def test_unsupported_right_does_not_execute(self):
        request = self._request("erasure")
        with self.assertRaises(NotImplementedError):
            rights.execute(
                request["id"], self.installation, self.account["id"], self.compliance_db
            )
        self.assertFalse(
            data_subject_rights._adapter_executed(
                request["id"], "referral_wallet", self.compliance_db
            )
        )

    def test_adapter_cannot_execute_twice_for_same_request(self):
        request = self._request("access")
        rights.execute(request["id"], self.installation, self.account["id"], self.compliance_db)
        with self.assertRaises(RuntimeError):
            rights.execute(request["id"], self.installation, self.account["id"], self.compliance_db)

    def test_audit_contains_only_evidence_hash(self):
        request = self._request("access")
        rights.execute(request["id"], self.installation, self.account["id"], self.compliance_db)
        rows = data_subject_rights.audit_rows(self.compliance_db)
        row = next(item for item in rows if item["adapter"] == "referral_wallet")
        rendered = str(row)
        self.assertRegex(row["evidenceHash"], r"^[0-9a-f]{64}$")
        self.assertNotIn(self.installation, rendered)
        self.assertNotIn(self.account["id"], rendered)
        self.assertNotIn(self.account["code"], rendered)

    def test_capability_is_partial_and_non_identifying(self):
        capability = rights.capability(self.compliance_db)
        self.assertTrue(capability["bound"])
        self.assertTrue(capability["partial"])
        self.assertEqual(capability["supportedRights"], ["access", "portability"])
        self.assertEqual(capability["ownershipProvenance"], "authenticated_mobile_wallet_claim")
        self.assertFalse(capability["thirdPartyAppointmentIdentifiersExposed"])
        self.assertIn("erasure_retention_policy", capability["remainingOperations"])
        rendered = str(capability)
        self.assertNotIn(self.installation, rendered)
        self.assertNotIn(self.account["id"], rendered)


if __name__ == "__main__":
    unittest.main()
