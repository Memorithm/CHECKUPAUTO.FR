import os
import tempfile
import unittest
from unittest.mock import patch

import customer_booking_journal as journal


class BookingReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"CYBERCHECK_DATA_DIR": self.temp.name})
        self.env.start()
        self.key = "reconciliation-test-key-0001"
        self.request = {"service":"technical","vehicleId":"v1","date":"2026-10-15"}
        journal.prepare(account_id="a1",key=self.key,request=self.request)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_cannot_confirm_before_claiming_provider_write(self):
        with self.assertRaisesRegex(journal.BookingJournalError,"booking_reconciliation_required"):
            journal.confirm_verified(account_id="a1",key=self.key,
                                     provider_reference="mercure-1",verified=True)

    def test_provider_verification_is_mandatory(self):
        journal.require_reconciliation(account_id="a1",key=self.key)
        with self.assertRaisesRegex(journal.BookingJournalError,"booking_provider_confirmation_unverified"):
            journal.confirm_verified(account_id="a1",key=self.key,
                                     provider_reference="mercure-1",verified=False)
        self.assertFalse(journal.status(account_id="a1",key=self.key)["confirmed"])

    def test_truthy_non_boolean_verification_is_rejected(self):
        journal.require_reconciliation(account_id="a1",key=self.key)
        for forged in ("true", 1, {"verified": True}):
            with self.subTest(forged=forged), self.assertRaisesRegex(
                journal.BookingJournalError, "booking_provider_confirmation_unverified"
            ):
                journal.confirm_verified(account_id="a1",key=self.key,
                                         provider_reference="mercure-1",verified=forged)
        self.assertFalse(journal.status(account_id="a1",key=self.key)["confirmed"])

    def test_confirmed_reference_is_idempotent_and_immutable(self):
        journal.require_reconciliation(account_id="a1",key=self.key)
        for _ in range(2):
            result=journal.confirm_verified(account_id="a1",key=self.key,
                                            provider_reference="mercure-1",verified=True)
            self.assertTrue(result["confirmed"])
        self.assertEqual(journal.status(account_id="a1",key=self.key)["providerReference"],"mercure-1")
        with self.assertRaisesRegex(journal.BookingJournalError,"booking_provider_reference_conflict"):
            journal.confirm_verified(account_id="a1",key=self.key,
                                     provider_reference="mercure-2",verified=True)

    def test_foreign_account_cannot_read_or_confirm(self):
        journal.require_reconciliation(account_id="a1",key=self.key)
        with self.assertRaisesRegex(journal.BookingJournalError,"booking_request_not_found"):
            journal.status(account_id="a2",key=self.key)
        with self.assertRaisesRegex(journal.BookingJournalError,"booking_request_not_found"):
            journal.confirm_verified(account_id="a2",key=self.key,
                                     provider_reference="mercure-1",verified=True)


if __name__ == "__main__":
    unittest.main()
