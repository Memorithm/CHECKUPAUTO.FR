import os
import tempfile
import unittest
from unittest.mock import patch

import customer_booking_journal as journal


class BookingJournalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"CYBERCHECK_DATA_DIR": self.temp.name})
        self.env.start()
        self.key = "booking-test-unique-key-0001"
        self.request = {"service": "technical", "date": "2026-10-15", "time": "10:30",
                        "vehicleId": "vehicle-1", "priceCents": 8000}

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_replay_is_idempotent_and_does_not_claim_confirmation(self):
        first = journal.prepare(account_id="customer-1", key=self.key, request=self.request)
        again = journal.prepare(account_id="customer-1", key=self.key, request=self.request)
        self.assertEqual(first, again)
        self.assertEqual(first["state"], "prepared")
        self.assertFalse(first["confirmed"])

    def test_reused_key_for_other_request_or_account_is_rejected(self):
        journal.prepare(account_id="customer-1", key=self.key, request=self.request)
        for account, request in (
            ("customer-2", self.request),
            ("customer-1", {**self.request, "time": "11:00"}),
        ):
            with self.subTest(account=account, request=request), self.assertRaisesRegex(
                journal.BookingJournalError, "booking_idempotency_conflict"
            ):
                journal.prepare(account_id=account, key=self.key, request=request)

    def test_ambiguous_external_write_blocks_all_blind_retries(self):
        journal.prepare(account_id="customer-1", key=self.key, request=self.request)
        state = journal.require_reconciliation(account_id="customer-1", key=self.key)
        self.assertEqual(state["state"], "reconciliation_required")
        self.assertFalse(state["confirmed"])
        with self.assertRaisesRegex(journal.BookingJournalError, "booking_reconciliation_required"):
            journal.require_reconciliation(account_id="customer-1", key=self.key)
        replay = journal.prepare(account_id="customer-1", key=self.key, request=self.request)
        self.assertEqual(replay["state"], "reconciliation_required")
        self.assertFalse(replay["confirmed"])

    def test_unknown_or_invalid_key_cannot_claim_provider_write(self):
        with self.assertRaisesRegex(journal.BookingJournalError, "booking_request_not_found"):
            journal.require_reconciliation(account_id="customer-1", key=self.key)
        with self.assertRaisesRegex(journal.BookingJournalError, "booking_idempotency_key_invalid"):
            journal.prepare(account_id="customer-1", key="x", request=self.request)


if __name__ == "__main__":
    unittest.main()
