from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

import analytics_store as analytics
import compliance_store
import data_subject_rights
import referral_engine as referrals
import referral_wallet_claims as claims
import referral_wallet_rights as rights
import rights_completion_plan


class ReferralWalletExportCompletionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_analytics_db = analytics.DB
        analytics.DB = Path(self.tmp.name) / "analytics.sqlite3"
        self.compliance_db = Path(self.tmp.name) / "compliance.sqlite3"
        analytics.init_db()
        referrals.init_db()
        claims.init_db()
        compliance_store.init_db(self.compliance_db)
        self.installation = "60cf7ccf-4297-41f4-b76b-c0bd44dbe3d1"
        self.account = referrals.create_account("EXPORT-9K4P")

    def tearDown(self):
        analytics.DB = self.old_analytics_db
        self.tmp.cleanup()

    def _request(self, request_type: str) -> dict:
        return compliance_store.create_rights_request(
            {"type": request_type, "subjectRef": self.installation},
            self.compliance_db,
        )

    def _plan(self, request_type: str) -> list[dict]:
        entries = []
        for adapter in rights_completion_plan._known_adapters(request_type):
            if adapter == rights.ADAPTER:
                entries.append({"adapter": adapter, "disposition": "required"})
            else:
                entries.append(
                    {
                        "adapter": adapter,
                        "disposition": "not_applicable",
                        "justification": f"{adapter} non applicable dans ce scénario de test isolé",
                    }
                )
        return entries

    def _wallet_item(self, request_id: str, request_type: str) -> tuple[dict, dict]:
        state = rights_completion_plan.configure(
            request_id,
            self._plan(request_type),
            self.compliance_db,
        )
        item = next(row for row in state["items"] if row["adapter"] == rights.ADAPTER)
        return state, item

    def test_complete_small_access_export_satisfies_wallet_plan_item_only(self):
        request = self._request("access")
        with mock.patch.object(claims, "ownership_matches", return_value=True):
            result = rights.execute(
                request["id"], self.installation, self.account["id"], self.compliance_db
            )

        self.assertTrue(result["exportComplete"])
        self.assertFalse(result["data"]["ledgerTruncated"])
        audit = next(
            row
            for row in data_subject_rights.audit_rows(self.compliance_db)
            if row["adapter"] == rights.ADAPTER
        )
        self.assertEqual(audit["action"], "export_complete")

        state, wallet = self._wallet_item(request["id"], "access")
        self.assertTrue(wallet["executed"])
        self.assertTrue(wallet["executionComplete"])
        self.assertTrue(wallet["satisfied"])
        self.assertEqual(wallet["executionLimitation"], "")
        self.assertTrue(state["knownScopeComplete"])
        self.assertFalse(state["globalCoverageComplete"])
        self.assertFalse(state["closureReady"])

    def test_real_truncated_portability_export_stays_partial(self):
        request = self._request("portability")
        stamp = "2026-09-23T00:00:00+00:00"
        with analytics.connect() as db:
            db.executemany(
                """INSERT INTO referral_ledger(
                     account_id,kind,amount_cents,reference,created_at,note
                   ) VALUES(?,?,?,?,?,?)""",
                [
                    (
                        self.account["id"],
                        "earn",
                        1,
                        f"export-test-{index:03d}",
                        stamp,
                        "test",
                    )
                    for index in range(rights.MAX_LEDGER_ENTRIES + 1)
                ],
            )

        with mock.patch.object(claims, "ownership_matches", return_value=True):
            result = rights.execute(
                request["id"], self.installation, self.account["id"], self.compliance_db
            )

        self.assertFalse(result["exportComplete"])
        self.assertTrue(result["data"]["ledgerTruncated"])
        self.assertEqual(result["data"]["ledgerCount"], rights.MAX_LEDGER_ENTRIES + 1)
        self.assertEqual(len(result["data"]["ledger"]), rights.MAX_LEDGER_ENTRIES)
        audit = next(
            row
            for row in data_subject_rights.audit_rows(self.compliance_db)
            if row["adapter"] == rights.ADAPTER
        )
        self.assertEqual(audit["action"], "export_bounded")

        state, wallet = self._wallet_item(request["id"], "portability")
        self.assertTrue(wallet["executed"])
        self.assertFalse(wallet["executionComplete"])
        self.assertFalse(wallet["satisfied"])
        self.assertEqual(wallet["executionLimitation"], "bounded_wallet_or_retained_erasure")
        self.assertFalse(state["knownScopeComplete"])
        self.assertFalse(state["closureReady"])

    def test_access_completion_action_cannot_satisfy_erasure(self):
        request = self._request("erasure")
        data_subject_rights._init_audit(self.compliance_db)
        with compliance_store.connect(self.compliance_db) as db:
            db.execute(
                """INSERT INTO rights_execution_audit(
                     execution_id,request_id,request_type,adapter,action,evidence_hash,created_at
                   ) VALUES(?,?,?,?,?,?,?)""",
                (
                    uuid.uuid4().hex,
                    request["id"],
                    "erasure",
                    rights.ADAPTER,
                    "export_complete",
                    "a" * 64,
                    data_subject_rights._now_iso(),
                ),
            )

        state, wallet = self._wallet_item(request["id"], "erasure")
        self.assertTrue(wallet["executed"])
        self.assertFalse(wallet["executionComplete"])
        self.assertFalse(wallet["satisfied"])
        self.assertEqual(wallet["executionLimitation"], "bounded_wallet_or_retained_erasure")
        self.assertFalse(state["knownScopeComplete"])


if __name__ == "__main__":
    unittest.main()
