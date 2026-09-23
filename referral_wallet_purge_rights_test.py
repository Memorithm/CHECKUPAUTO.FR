import datetime
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analytics_store as analytics
import compliance_store
import data_subject_rights
import referral_engine
import referral_wallet_claims
import referral_wallet_final_purge as final_purge
import referral_wallet_purge_rights as purge_rights
import rights_completion_plan


class ReferralWalletPurgeRightsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_analytics = analytics.DB
        analytics.DB = Path(self.tmp.name) / "analytics.sqlite3"
        self.addCleanup(setattr, analytics, "DB", self.old_analytics)
        self.compliance_db = Path(self.tmp.name) / "compliance.sqlite3"
        analytics.init_db()
        referral_engine.init_db()
        referral_wallet_claims.init_db()
        compliance_store.init_db(self.compliance_db)
        data_subject_rights._init_audit(self.compliance_db)
        self.now = datetime.datetime(2026, 9, 23, 6, 0, tzinfo=datetime.timezone.utc)

    def _request(self, request_id: str, *, initial_execution: bool = True) -> None:
        stamp = self.now.isoformat(timespec="seconds")
        with compliance_store.connect(self.compliance_db) as db:
            db.execute(
                """INSERT INTO rights_requests(
                     request_id,request_type,status,subject_ref_hash,received_at,due_at,closed_at,notes
                   ) VALUES(?, 'erasure', 'in_progress', ?, ?, ?, '', '')""",
                (request_id, "a" * 64, stamp, stamp),
            )
            if initial_execution:
                db.execute(
                    """INSERT INTO rights_execution_audit(
                         execution_id,request_id,request_type,adapter,action,evidence_hash,created_at
                       ) VALUES(?,?,'erasure',?,?,?,?)""",
                    (
                        "e" * 32,
                        request_id,
                        purge_rights.ADAPTER,
                        purge_rights.INITIAL_ACTION,
                        "b" * 64,
                        stamp,
                    ),
                )

    def _retired_account(self, code: str) -> dict:
        account = referral_engine.create_account(code)
        with analytics.connect() as db:
            db.execute(
                "UPDATE referral_accounts SET active=0,code=? WHERE id=?",
                (final_purge._retired_code(account["id"]), account["id"]),
            )
        return account

    def test_final_purge_appends_hashed_erasure_completion_evidence(self):
        request_id = "1" * 32
        self._request(request_id)
        account = self._retired_account("DSAR-PURGE-COMPLETE")
        staged = purge_rights.stage(request_id, account["id"], self.compliance_db)
        self.assertEqual(len(staged["accountHash"]), 64)
        self.assertNotEqual(staged["accountHash"], account["id"])

        result = final_purge.purge_retired_wallets(
            30,
            now=self.now,
            db_path=self.compliance_db,
        )
        self.assertEqual(result["purgedAccounts"], 1)

        with compliance_store.connect(self.compliance_db) as db:
            actions = [
                str(row["action"])
                for row in db.execute(
                    """SELECT action FROM rights_execution_audit
                       WHERE request_id=? AND adapter=? ORDER BY created_at,execution_id""",
                    (request_id, purge_rights.ADAPTER),
                )
            ]
            complete = db.execute(
                """SELECT evidence_hash FROM rights_execution_audit
                   WHERE request_id=? AND adapter=? AND action=?""",
                (request_id, purge_rights.ADAPTER, purge_rights.COMPLETE_ACTION),
            ).fetchone()
            pending = int(
                db.execute(
                    "SELECT COUNT(*) n FROM referral_wallet_erasure_completion_link"
                ).fetchone()["n"]
            )
        self.assertIn(purge_rights.INITIAL_ACTION, actions)
        self.assertIn(purge_rights.COMPLETE_ACTION, actions)
        self.assertEqual(len(str(complete["evidence_hash"])), 64)
        self.assertEqual(pending, 0)
        self.assertNotIn(account["id"], str(actions) + str(dict(complete)))

        state = rights_completion_plan.configure(
            request_id,
            [
                {
                    "adapter": "mobile_installation",
                    "disposition": "not_applicable",
                    "justification": "Aucune installation mobile applicable à cette demande de test.",
                },
                {
                    "adapter": "privacy_suppression",
                    "disposition": "not_applicable",
                    "justification": "La suppression de traitement est hors du périmètre de cette demande de test.",
                },
                {"adapter": "referral_wallet", "disposition": "required"},
            ],
            self.compliance_db,
        )
        wallet = next(item for item in state["items"] if item["adapter"] == "referral_wallet")
        self.assertTrue(wallet["executionComplete"])
        self.assertTrue(wallet["satisfied"])
        self.assertTrue(state["knownScopeComplete"])
        self.assertFalse(state["globalCoverageComplete"])
        self.assertFalse(state["closureReady"])

    def test_recovered_post_commit_purge_also_completes_dsar_evidence(self):
        request_id = "2" * 32
        self._request(request_id)
        account = self._retired_account("DSAR-PURGE-RECOVER")
        purge_rights.stage(request_id, account["id"], self.compliance_db)

        with mock.patch.object(final_purge, "_complete", side_effect=RuntimeError("audit outage")):
            with self.assertRaisesRegex(RuntimeError, "audit outage"):
                final_purge.purge_retired_wallets(
                    30,
                    now=self.now,
                    db_path=self.compliance_db,
                )

        recovered = final_purge.purge_retired_wallets(
            30,
            now=self.now,
            db_path=self.compliance_db,
        )
        self.assertEqual(recovered["recoveredPlannedOperations"], 1)
        with compliance_store.connect(self.compliance_db) as db:
            action = db.execute(
                """SELECT action FROM rights_execution_audit
                   WHERE request_id=? AND adapter=? AND action=?""",
                (request_id, purge_rights.ADAPTER, purge_rights.COMPLETE_ACTION),
            ).fetchone()
            purge_state = db.execute(
                "SELECT state FROM referral_wallet_final_purge_audit"
            ).fetchone()
        self.assertIsNotNone(action)
        self.assertEqual(str(purge_state["state"]), "recovered_absent")

    def test_missing_initial_erasure_audit_never_invents_completion(self):
        request_id = "3" * 32
        self._request(request_id, initial_execution=False)
        account = self._retired_account("DSAR-PURGE-NO-INITIAL")
        purge_rights.stage(request_id, account["id"], self.compliance_db)

        result = final_purge.purge_retired_wallets(
            30,
            now=self.now,
            db_path=self.compliance_db,
        )
        self.assertEqual(result["purgedAccounts"], 1)
        with compliance_store.connect(self.compliance_db) as db:
            complete = db.execute(
                """SELECT 1 FROM rights_execution_audit
                   WHERE request_id=? AND action=?""",
                (request_id, purge_rights.COMPLETE_ACTION),
            ).fetchone()
            pending = int(
                db.execute(
                    "SELECT COUNT(*) n FROM referral_wallet_erasure_completion_link"
                ).fetchone()["n"]
            )
        self.assertIsNone(complete)
        self.assertEqual(pending, 1)


if __name__ == "__main__":
    unittest.main()
