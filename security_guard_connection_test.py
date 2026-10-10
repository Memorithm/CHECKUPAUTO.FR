"""Q-03: Sentinel database handles are closed deterministically."""
import gc
import sqlite3
import unittest
import warnings
from unittest import mock

import security_guard


class SentinelConnectionTest(unittest.TestCase):
    def test_db_helper_closes_connection(self):
        with security_guard._db() as db:
            db.execute("SELECT 1")
            handle = db
        with self.assertRaises(sqlite3.ProgrammingError):
            handle.execute("SELECT 1")

    def test_db_helper_rolls_back_and_closes_on_error(self):
        with self.assertRaises(RuntimeError):
            with security_guard._db() as db:
                db.execute("INSERT INTO security_events(occurred_at,client_hash,method,path,status,risk,action,reason) VALUES('x','y','GET','/q03',0,0,'allow','test')")
                handle = db
                raise RuntimeError("boom")
        with self.assertRaises(sqlite3.ProgrammingError):
            handle.execute("SELECT 1")
        with security_guard._db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM security_events WHERE path='/q03'").fetchone()[0], 0)

    def test_recording_and_status_leave_no_unclosed_connection(self):
        gc.collect()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            with mock.patch.object(security_guard.alerts, "emit"):
                security_guard.system_event("q03_probe", risk=10)
            security_guard.status(1)
            gc.collect()
        leaks = [w for w in caught if issubclass(w.category, ResourceWarning) and "sqlite3" in str(w.message)]
        self.assertEqual(leaks, [])


if __name__ == "__main__":
    unittest.main()
