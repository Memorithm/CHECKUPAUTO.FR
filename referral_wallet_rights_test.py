import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analytics_store as analytics
import compliance_store
import data_subject_rights
import mobile_devices as devices
import referral_engine as referrals
import referral_wallet_claims as claims
import referral_wallet_rights as rights
import retention_enforcement


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

    def _configure_retention(self, days=1095):
        return retention_enforcement.save_policy(
            {
                "ruleId": "referral_ledger",
                "activeDays": days,
                "justification": "Validation juridique test du ledger de parrainage",
                "legalReviewConfirmed": True,
                "enabled": True,
            },
            self.compliance_db,
        )

    def _account_active(self):
        with analytics.connect() as db:
            return bool(db.execute(
                "SELECT active FROM referral_accounts WHERE id=?", (self.account["id"],)
            ).fetchone()["active"])

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
        request = self._request("rectification")
        with self.assertRaises(NotImplementedError):
            rights.execute(
                request["id"], self.installation, self.account["id"], self.compliance_db
            )
        self.assertFalse(
            data_subject_rights._adapter_executed(
                request["id"], "referral_wallet", self.compliance_db
            )
        )

    def test_erasure_refuses_to_invent_retention_policy(self):
        request = self._request("erasure")
        with self.assertRaisesRegex(RuntimeError, "politique de conservation"):
            rights.execute(
                request["id"], self.installation, self.account["id"], self.compliance_db
            )
        self.assertTrue(self._account_active())
        self.assertTrue(claims.ownership_matches(self.account["id"], self.installation))
        self.assertFalse(data_subject_rights._adapter_executed(
            request["id"], "referral_wallet", self.compliance_db
        ))

    def test_erasure_deactivates_zero_balance_wallet_and_retains_financial_history(self):
        self._configure_retention(1095)
        referrals.record_pending(self.account["code"], "mercure-rdv", "rdv-retained", "intent-retained")
        referrals.complete_control("mercure-rdv", "rdv-retained")
        referrals.cancel_pending("mercure-rdv", "rdv-retained")
        before_ledger = referrals.account_summary(self.account["code"])["ledger"]
        self.assertEqual(referrals.account_summary(self.account["code"])["balanceCents"], 0)
        claim = claims.issue(self.account["code"])
        self.assertTrue(claim["claimToken"].startswith("rw_"))

        request = self._request("erasure")
        result = rights.execute(
            request["id"], self.installation, self.account["id"], self.compliance_db
        )

        self.assertFalse(self._account_active())
        self.assertFalse(claims.ownership_matches(self.account["id"], self.installation))
        with analytics.connect() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) n FROM referral_wallet_claim WHERE account_id=?",
                (self.account["id"],),
            ).fetchone()["n"], 0)
            after_ledger = [dict(row) for row in db.execute(
                """SELECT kind,amount_cents amountCents,reference,created_at createdAt,note
                   FROM referral_ledger WHERE account_id=? ORDER BY id DESC LIMIT 50""",
                (self.account["id"],),
            )]
        self.assertEqual(after_ledger, before_ledger)
        self.assertEqual(result["ownershipReleased"], 1)
        self.assertEqual(result["pendingClaimsRevoked"], 1)
        self.assertTrue(result["financialHistoryRetained"])
        self.assertFalse(result["finalPhysicalPurgeComplete"])
        self.assertEqual(result["retention"]["activeDays"], 1095)
        self.assertTrue(result["retention"]["legalReviewConfirmed"])
        self.assertFalse(result["requestComplete"])
        rendered = repr(result)
        self.assertNotIn(self.installation, rendered)
        self.assertNotIn(self.account["id"], rendered)
        self.assertNotIn(self.account["code"], rendered)
        audit = data_subject_rights.audit_rows(self.compliance_db)
        self.assertEqual(audit[0]["action"], "deactivate_retained_erasure")
        self.assertNotIn(self.installation, repr(audit))
        self.assertNotIn(self.account["id"], repr(audit))

    def test_erasure_blocks_nonzero_balance_until_financial_resolution(self):
        self._configure_retention()
        referrals.record_pending(self.account["code"], "mercure-rdv", "rdv-balance", "intent-balance")
        referrals.complete_control("mercure-rdv", "rdv-balance")
        self.assertEqual(referrals.account_summary(self.account["code"])["balanceCents"], 500)
        request = self._request("erasure")

        with self.assertRaisesRegex(RuntimeError, "résolution financière"):
            rights.execute(
                request["id"], self.installation, self.account["id"], self.compliance_db
            )
        self.assertTrue(self._account_active())
        self.assertTrue(claims.ownership_matches(self.account["id"], self.installation))

        referrals.redeem(self.account["code"], 500, "settle-before-erasure")
        result = rights.execute(
            request["id"], self.installation, self.account["id"], self.compliance_db
        )
        self.assertTrue(result["ok"])
        self.assertFalse(self._account_active())

    def test_erasure_blocks_pending_rewards_until_provider_state_is_resolved(self):
        self._configure_retention()
        referrals.record_pending(self.account["code"], "mercure-rdv", "rdv-pending", "intent-pending")
        request = self._request("erasure")
        with self.assertRaisesRegex(RuntimeError, "résolution financière"):
            rights.execute(
                request["id"], self.installation, self.account["id"], self.compliance_db
            )
        referrals.cancel_pending("mercure-rdv", "rdv-pending")
        result = rights.execute(
            request["id"], self.installation, self.account["id"], self.compliance_db
        )
        self.assertTrue(result["ok"])
        self.assertFalse(self._account_active())

    def test_erasure_retry_survives_audit_failure_without_restoring_owner_link(self):
        self._configure_retention()
        request = self._request("erasure")
        with mock.patch.object(
            rights.data_subject_rights,
            "_audit_execution",
            side_effect=RuntimeError("temporary compliance audit failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "temporary compliance audit failure"):
                rights.execute(
                    request["id"], self.installation, self.account["id"], self.compliance_db
                )

        self.assertFalse(self._account_active())
        self.assertFalse(claims.ownership_matches(self.account["id"], self.installation))
        with compliance_store.connect(self.compliance_db) as db:
            checkpoint = db.execute(
                "SELECT account_hash,subject_hash FROM referral_wallet_erasure_checkpoint WHERE request_id=?",
                (request["id"],),
            ).fetchone()
        self.assertIsNotNone(checkpoint)
        self.assertNotIn(self.account["id"], repr(tuple(checkpoint)))
        self.assertNotIn(self.installation, repr(tuple(checkpoint)))

        result = rights.execute(
            request["id"], self.installation, self.account["id"], self.compliance_db
        )
        self.assertTrue(result["ok"])
        with compliance_store.connect(self.compliance_db) as db:
            remaining = db.execute(
                "SELECT COUNT(*) n FROM referral_wallet_erasure_checkpoint WHERE request_id=?",
                (request["id"],),
            ).fetchone()["n"]
        self.assertEqual(remaining, 0)
        self.assertEqual(len(data_subject_rights.audit_rows(self.compliance_db)), 1)

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
        self.assertEqual(capability["supportedRights"], ["access", "portability", "erasure"])
        self.assertEqual(capability["ownershipProvenance"], "authenticated_mobile_wallet_claim")
        self.assertFalse(capability["thirdPartyAppointmentIdentifiersExposed"])
        self.assertFalse(capability["erasure"]["retention"]["ready"])
        self.assertFalse(capability["erasure"]["finalPhysicalPurgeComplete"])
        self.assertIn("final_retention_expiry_purge", capability["remainingOperations"])
        rendered = str(capability)
        self.assertNotIn(self.installation, rendered)
        self.assertNotIn(self.account["id"], rendered)

        self._configure_retention(730)
        ready = rights.capability(self.compliance_db)
        self.assertTrue(ready["erasure"]["retention"]["ready"])
        self.assertEqual(ready["erasure"]["retention"]["activeDays"], 730)


if __name__ == "__main__":
    unittest.main()
