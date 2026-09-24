import tempfile
import unittest
from pathlib import Path

import compliance_store
import provider_erasure_completion as completion


class ProviderErasureCompletionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "compliance.sqlite3"
        self.request = compliance_store.create_rights_request(
            {"type": "erasure", "subjectRef": "account:42"},
            self.db,
        )

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def receipt(store, set_hash="a" * 64, evidence_hash="b" * 64):
        return {
            "store": store,
            "appointmentSetHash": set_hash,
            "appointmentCount": 2,
            "affectedRows": 1,
            "remainingActiveRows": 0,
            "evidenceHash": evidence_hash,
        }

    def test_records_minimized_cross_store_completion(self):
        result = completion.record(
            self.request["id"],
            self.receipt("review_followup", evidence_hash="b" * 64),
            self.receipt("booking_conversions", evidence_hash="c" * 64),
            self.db,
        )
        self.assertFalse(result["rawAppointmentIdsPersisted"])
        self.assertRegex(result["evidenceHash"], r"^[0-9a-f]{64}$")
        stored = completion.status(self.request["id"], self.db)
        self.assertTrue(stored["complete"])
        self.assertEqual(stored["appointmentSetHash"], "a" * 64)
        self.assertNotIn("appointmentIds", stored)

    def test_mismatched_inventory_hashes_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError, "divergentes"):
            completion.record(
                self.request["id"],
                self.receipt("review_followup", set_hash="a" * 64),
                self.receipt("booking_conversions", set_hash="d" * 64),
                self.db,
            )
        self.assertIsNone(completion.status(self.request["id"], self.db))

    def test_nonzero_remaining_rows_fail_closed(self):
        booking = self.receipt("booking_conversions")
        booking["remainingActiveRows"] = 1
        with self.assertRaisesRegex(RuntimeError, "incomplet"):
            completion.record(
                self.request["id"],
                self.receipt("review_followup"),
                booking,
                self.db,
            )

    def test_identical_replay_reuses_existing_completion(self):
        review = self.receipt("review_followup", evidence_hash="b" * 64)
        booking = self.receipt("booking_conversions", evidence_hash="c" * 64)
        first = completion.record(self.request["id"], review, booking, self.db)
        second = completion.record(self.request["id"], review, booking, self.db)
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertEqual(first["evidenceHash"], second["evidenceHash"])
        self.assertEqual(first["completedAt"], second["completedAt"])

    def test_non_erasure_request_is_rejected(self):
        access = compliance_store.create_rights_request(
            {"type": "access", "subjectRef": "account:42"},
            self.db,
        )
        with self.assertRaisesRegex(ValueError, "effacement"):
            completion.record(
                access["id"],
                self.receipt("review_followup"),
                self.receipt("booking_conversions"),
                self.db,
            )


if __name__ == "__main__":
    unittest.main()
