from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analytics_store as analytics
import compliance_store
import data_subject_rights
import referral_engine as referrals
import referral_wallet_claims as claims
import referral_wallet_paged_export as paged
import referral_wallet_rights as rights
import rights_completion_plan
import rights_execution_dispatch


class ReferralWalletPagedExportTest(unittest.TestCase):
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
        self.account = referrals.create_account("PAGED-9K4P")

    def tearDown(self):
        analytics.DB = self.old_analytics_db
        self.tmp.cleanup()

    def _request(self, request_type: str = "portability") -> dict:
        return compliance_store.create_rights_request(
            {"type": request_type, "subjectRef": self.installation},
            self.compliance_db,
        )

    def _insert_ledger(self, count: int) -> None:
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
                        f"paged-export-{index:04d}",
                        stamp,
                        "test",
                    )
                    for index in range(count)
                ],
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
                        "justification": f"{adapter} non applicable au scénario isolé",
                    }
                )
        return entries

    def test_401_rows_complete_across_three_bounded_pages(self):
        request = self._request()
        self._insert_ledger(401)

        with mock.patch.object(claims, "ownership_matches", return_value=True):
            first = rights.execute(
                request["id"], self.installation, self.account["id"], self.compliance_db
            )
            self.assertFalse(first["exportComplete"])
            self.assertEqual(len(first["data"]["ledger"]), paged.PAGE_SIZE)
            session_id = first["pagedExport"]["sessionId"]
            self.assertTrue(first["pagedExport"]["hasMore"])

            second = rights.continue_export(
                request["id"],
                self.installation,
                self.account["id"],
                session_id,
                self.compliance_db,
            )
            self.assertEqual(len(second["data"]["ledger"]), paged.PAGE_SIZE)
            self.assertTrue(second["pagedExport"]["hasMore"])
            self.assertFalse(second["pagedExport"]["exportComplete"])

            third = rights.continue_export(
                request["id"],
                self.installation,
                self.account["id"],
                session_id,
                self.compliance_db,
            )
            self.assertEqual(len(third["data"]["ledger"]), 1)
            self.assertFalse(third["pagedExport"]["hasMore"])
            self.assertTrue(third["pagedExport"]["exportComplete"])
            self.assertEqual(third["pagedExport"]["rowsExportedTotal"], 401)

            replay = rights.continue_export(
                request["id"],
                self.installation,
                self.account["id"],
                session_id,
                self.compliance_db,
            )
            self.assertTrue(replay["pagedExport"]["alreadyComplete"])
            self.assertEqual(replay["data"]["ledger"], [])

        actions = {
            row["action"]
            for row in data_subject_rights.audit_rows(self.compliance_db)
            if row["requestId"] == request["id"] and row["adapter"] == rights.ADAPTER
        }
        self.assertEqual(actions, {"export_bounded", "export_complete"})

        state = rights_completion_plan.configure(
            request["id"], self._plan("portability"), self.compliance_db
        )
        wallet = next(item for item in state["items"] if item["adapter"] == rights.ADAPTER)
        self.assertTrue(wallet["executionComplete"])
        self.assertTrue(wallet["satisfied"])
        self.assertTrue(state["knownScopeComplete"])
        self.assertFalse(state["globalCoverageComplete"])

        with compliance_store.connect(self.compliance_db) as db:
            columns = {
                str(row["name"])
                for row in db.execute("PRAGMA table_info(referral_wallet_export_session)")
            }
            session = db.execute(
                """SELECT account_hash,expected_count,rows_seen,completed_at
                   FROM referral_wallet_export_session WHERE session_id=?""",
                (session_id,),
            ).fetchone()
        self.assertNotIn("account_id", columns)
        self.assertNotIn("installation_id", columns)
        self.assertEqual(
            str(session["account_hash"]),
            hashlib.sha256(self.account["id"].encode("utf-8")).hexdigest(),
        )
        self.assertEqual(int(session["expected_count"]), 401)
        self.assertEqual(int(session["rows_seen"]), 401)
        self.assertTrue(str(session["completed_at"]))

    def test_rows_inserted_after_start_do_not_enter_stable_boundary(self):
        request = self._request()
        self._insert_ledger(201)

        with mock.patch.object(claims, "ownership_matches", return_value=True):
            first = rights.execute(
                request["id"], self.installation, self.account["id"], self.compliance_db
            )
            session_id = first["pagedExport"]["sessionId"]
            with analytics.connect() as db:
                db.execute(
                    """INSERT INTO referral_ledger(
                         account_id,kind,amount_cents,reference,created_at,note
                       ) VALUES(?,?,?,?,?,?)""",
                    (
                        self.account["id"],
                        "earn",
                        1,
                        "inserted-after-session",
                        "2026-09-23T00:00:00+00:00",
                        "test",
                    ),
                )
            final = rights.continue_export(
                request["id"],
                self.installation,
                self.account["id"],
                session_id,
                self.compliance_db,
            )

        self.assertTrue(final["pagedExport"]["exportComplete"])
        self.assertEqual(final["pagedExport"]["rowsExportedTotal"], 201)
        self.assertEqual(len(final["data"]["ledger"]), 1)
        inserted_hash = hashlib.sha256(b"inserted-after-session").hexdigest()
        self.assertNotEqual(final["data"]["ledger"][0]["referenceHash"], inserted_hash)

    def test_deletion_inside_boundary_invalidates_without_completion_audit(self):
        request = self._request()
        self._insert_ledger(201)

        with mock.patch.object(claims, "ownership_matches", return_value=True):
            first = rights.execute(
                request["id"], self.installation, self.account["id"], self.compliance_db
            )
            session_id = first["pagedExport"]["sessionId"]
            with analytics.connect() as db:
                oldest = db.execute(
                    "SELECT MIN(id) id FROM referral_ledger WHERE account_id=?",
                    (self.account["id"],),
                ).fetchone()["id"]
                db.execute("DELETE FROM referral_ledger WHERE id=?", (int(oldest),))

            final = rights.continue_export(
                request["id"],
                self.installation,
                self.account["id"],
                session_id,
                self.compliance_db,
            )

        self.assertTrue(final["pagedExport"]["invalidated"])
        self.assertFalse(final["pagedExport"]["exportComplete"])
        actions = {
            row["action"]
            for row in data_subject_rights.audit_rows(self.compliance_db)
            if row["requestId"] == request["id"] and row["adapter"] == rights.ADAPTER
        }
        self.assertEqual(actions, {"export_bounded"})

    def test_dispatcher_continuation_uses_opaque_server_session(self):
        request = self._request("access")
        self._insert_ledger(201)

        with mock.patch.object(claims, "ownership_matches", return_value=True):
            first = rights_execution_dispatch.execute(
                {
                    "id": request["id"],
                    "subjectRef": self.installation,
                    "adapter": rights.ADAPTER,
                    "accountId": self.account["id"],
                },
                self.compliance_db,
            )
            final = rights_execution_dispatch.execute(
                {
                    "id": request["id"],
                    "subjectRef": self.installation,
                    "adapter": rights.ADAPTER,
                    "accountId": self.account["id"],
                    "pagedExportSessionId": first["pagedExport"]["sessionId"],
                },
                self.compliance_db,
            )

        self.assertTrue(final["pagedExport"]["exportComplete"])
        self.assertEqual(final["pagedExport"]["rowsExportedTotal"], 201)


if __name__ == "__main__":
    unittest.main()
