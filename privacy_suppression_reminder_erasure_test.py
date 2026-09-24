import os
import tempfile
import unittest
from pathlib import Path

import compliance_store
import privacy_suppression
import reminder_dispatch


class PrivacySuppressionReminderErasureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.old_private = os.environ.get("CYBERCHECK_PRIVATE_DIR")
        os.environ["CYBERCHECK_PRIVATE_DIR"] = str(root / "private")
        self.old_reminder_data = reminder_dispatch.DATA_DIR
        self.old_reminder_db = reminder_dispatch.DB
        reminder_dispatch.DATA_DIR = root / "reminder"
        reminder_dispatch.DB = reminder_dispatch.DATA_DIR / "reminder-dispatch.sqlite3"
        self.addCleanup(self._restore)
        self.compliance_db = root / "compliance.sqlite3"
        compliance_store.init_db(self.compliance_db)
        reminder_dispatch.init_db()

    def _restore(self):
        reminder_dispatch.DATA_DIR = self.old_reminder_data
        reminder_dispatch.DB = self.old_reminder_db
        if self.old_private is None:
            os.environ.pop("CYBERCHECK_PRIVATE_DIR", None)
        else:
            os.environ["CYBERCHECK_PRIVATE_DIR"] = self.old_private

    def _request(self, request_type, subject_ref):
        return compliance_store.create_rights_request(
            {"type": request_type, "subjectRef": subject_ref},
            self.compliance_db,
        )

    def _target(self, vehicle_id, client_kind, client_id):
        reminder_dispatch.init_db()
        with reminder_dispatch.connect() as db:
            db.execute(
                """INSERT INTO reminder_target(
                     vehicle_id,client_kind,client_id,due_date,appointment_id,
                     first_seen_at,last_seen_at,source_window_end,quarantined
                   ) VALUES(?,?,?,?,?,?,?,?,0)""",
                (
                    vehicle_id,
                    client_kind,
                    client_id,
                    "2027-01-15",
                    "appointment-test",
                    "2026-09-24T04:00:00+00:00",
                    "2026-09-24T04:00:00+00:00",
                    "2026-09-24",
                ),
            )

    def _target_count(self, *, client_kind=None, client_id=None, vehicle_id=None):
        with reminder_dispatch.connect() as db:
            if vehicle_id is not None:
                return int(db.execute(
                    "SELECT COUNT(*) n FROM reminder_target WHERE vehicle_id=?",
                    (vehicle_id,),
                ).fetchone()["n"])
            return int(db.execute(
                "SELECT COUNT(*) n FROM reminder_target WHERE client_kind=? AND client_id=?",
                (client_kind, client_id),
            ).fetchone()["n"])

    def test_erasure_removes_mercure_subject_from_reminder_cache_and_records_minimized_receipt(self):
        client_id = "account-erase-1"
        self._target("vehicle-erase-1", "account", client_id)
        request = self._request("erasure", f"account:{client_id}")

        result = privacy_suppression.suppress(
            "mercure_account",
            client_id,
            ["all_processing"],
            request_id=request["id"],
            db_path=self.compliance_db,
        )

        self.assertEqual(self._target_count(client_kind="account", client_id=client_id), 0)
        receipts = [row for row in result["storeReceipts"] if row["store"] == "reminder_target"]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["scope"], "mercure_account")
        self.assertEqual(receipts[0]["operation"], "erase_cached_target")
        self.assertEqual(receipts[0]["affectedRows"], 1)
        self.assertEqual(receipts[0]["remainingActiveRows"], 0)
        self.assertEqual(len(receipts[0]["evidenceHash"]), 64)
        self.assertNotIn(client_id, repr(receipts))
        self.assertIn(
            "reminder_target",
            privacy_suppression.summary(self.compliance_db)["storeEvidenceStores"],
        )

    def test_vehicle_erasure_is_bounded_to_matching_vehicle(self):
        vehicle_id = "vehicle-erase-exact"
        self._target(vehicle_id, "free", "free-client-1")
        self._target("vehicle-preserve", "free", "free-client-1")
        request = self._request("erasure", "free:free-client-1")
        subject_hash = privacy_suppression.identity_hash("vehicle", vehicle_id)

        mutation = reminder_dispatch.erase_privacy_targets(
            request["id"], "vehicle", vehicle_id, subject_hash
        )

        self.assertTrue(mutation["observed"])
        self.assertEqual(mutation["affectedRows"], 1)
        self.assertEqual(self._target_count(vehicle_id=vehicle_id), 0)
        self.assertEqual(self._target_count(vehicle_id="vehicle-preserve"), 1)
        self.assertNotIn(vehicle_id, repr(mutation))

    def test_non_erasure_suppression_preserves_reminder_cache(self):
        client_id = "account-objection-1"
        self._target("vehicle-objection-1", "account", client_id)
        request = self._request("objection", f"account:{client_id}")

        result = privacy_suppression.suppress(
            "mercure_account",
            client_id,
            ["direct_marketing_email"],
            request_id=request["id"],
            db_path=self.compliance_db,
        )

        self.assertEqual(self._target_count(client_kind="account", client_id=client_id), 1)
        self.assertFalse(any(row["store"] == "reminder_target" for row in result["storeReceipts"]))

    def test_store_receipt_recovers_compliance_proof_after_cross_database_interruption(self):
        client_id = "account-recover-1"
        self._target("vehicle-recover-1", "account", client_id)
        request = self._request("erasure", f"account:{client_id}")
        subject_hash = privacy_suppression.identity_hash("mercure_account", client_id)

        first = reminder_dispatch.erase_privacy_targets(
            request["id"], "mercure_account", client_id, subject_hash
        )
        self.assertTrue(first["observed"])
        self.assertEqual(first["affectedRows"], 1)
        self.assertEqual(
            privacy_suppression.store_receipts(request["id"], self.compliance_db),
            [],
        )

        recovered = privacy_suppression.suppress(
            "mercure_account",
            client_id,
            ["all_processing"],
            request_id=request["id"],
            db_path=self.compliance_db,
        )
        reminder_receipts = [
            row for row in recovered["storeReceipts"] if row["store"] == "reminder_target"
        ]
        self.assertEqual(len(reminder_receipts), 1)
        self.assertEqual(reminder_receipts[0]["affectedRows"], 1)
        self.assertEqual(reminder_receipts[0]["remainingActiveRows"], 0)

    def test_reintroduced_cache_row_is_removed_and_cumulative_receipt_advances(self):
        client_id = "account-race-1"
        vehicle_id = "vehicle-race-1"
        self._target(vehicle_id, "account", client_id)
        request = self._request("erasure", f"account:{client_id}")
        subject_hash = privacy_suppression.identity_hash("mercure_account", client_id)

        first = reminder_dispatch.erase_privacy_targets(
            request["id"], "mercure_account", client_id, subject_hash
        )
        self.assertEqual(first["affectedRows"], 1)
        self._target(vehicle_id, "account", client_id)
        second = reminder_dispatch.erase_privacy_targets(
            request["id"], "mercure_account", client_id, subject_hash
        )

        self.assertEqual(second["affectedRows"], 2)
        self.assertEqual(second["remainingActiveRows"], 0)
        self.assertNotEqual(first["evidenceHash"], second["evidenceHash"])
        self.assertEqual(self._target_count(client_kind="account", client_id=client_id), 0)


if __name__ == "__main__":
    unittest.main()
