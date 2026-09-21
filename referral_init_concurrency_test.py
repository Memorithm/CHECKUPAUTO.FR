import tempfile
import threading
import unittest
from pathlib import Path

import analytics_store as analytics
import referral_engine as referrals


class ReferralInitConcurrencyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.original_db = analytics.DB
        analytics.DB = Path(self.tmp.name) / "analytics.sqlite3"
        self.addCleanup(self._restore_db)

    def _restore_db(self):
        analytics.DB = self.original_db

    def test_concurrent_init_is_idempotent_and_preserves_invariant_triggers(self):
        referrals.init_db()
        workers = 8
        barrier = threading.Barrier(workers)
        errors = []
        lock = threading.Lock()

        def initialize_repeatedly():
            barrier.wait()
            try:
                for _ in range(20):
                    referrals.init_db()
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=initialize_repeatedly) for _ in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        self.assertEqual(errors, [])
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        with analytics.connect() as db:
            triggers = {
                row["name"]
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_referral_ledger_%'"
                )
            }
        self.assertEqual(
            triggers,
            {
                "trg_referral_ledger_nonnegative",
                "trg_referral_ledger_reverse_matches_earn",
            },
        )


if __name__ == "__main__":
    unittest.main()
