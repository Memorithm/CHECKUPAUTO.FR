"""Concurrency regression for booking journal; uses only an isolated temporary DB."""
import concurrent.futures
import os
import tempfile
import unittest
from unittest.mock import patch

import customer_booking_journal as journal


class BookingJournalConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{"CYBERCHECK_DATA_DIR":self.temp.name})
        self.env.start()
        self.key="concurrent-booking-request-key-0001"
        self.request={"service":"technical","date":"2026-10-15",
                      "time":"10:30","vehicleId":"v1"}

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_concurrent_prepares_share_exactly_one_intent(self):
        def attempt(_):
            return journal.prepare(account_id="customer-1",key=self.key,request=self.request)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(attempt,range(24)))
        self.assertEqual({item["state"] for item in results},{"prepared"})
        self.assertEqual({item["requestKey"] for item in results},{self.key})
        with journal._connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM booking_request").fetchone()[0],1)

    def test_concurrent_write_claims_allow_only_one_winner(self):
        journal.prepare(account_id="customer-1",key=self.key,request=self.request)
        def attempt(_):
            try:
                return journal.require_reconciliation(account_id="customer-1",key=self.key)["state"]
            except journal.BookingJournalError as exc:
                return str(exc)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(attempt,range(24)))
        self.assertEqual(results.count("reconciliation_required"),1)
        self.assertEqual(results.count("booking_reconciliation_required"),23)
        self.assertFalse(journal.status(account_id="customer-1",key=self.key)["confirmed"])


if __name__=="__main__":
    unittest.main()
