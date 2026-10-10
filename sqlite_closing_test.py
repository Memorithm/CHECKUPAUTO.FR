import importlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlite_closing import ClosingConnection

MODULES = (
    "analytics_store", "competitive_intelligence", "compliance_store",
    "customer_accounts", "customer_booking_journal", "customer_ct_reports",
    "customer_oidc", "mobile_devices", "notification_broker",
    "reminder_dispatch", "review_followup",
)


class ClosingConnectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "t.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def test_commit_then_close(self):
        with sqlite3.connect(self.path, factory=ClosingConnection) as db:
            db.execute("CREATE TABLE t(x)")
            db.execute("INSERT INTO t VALUES (1)")
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute("SELECT 1")
        check = sqlite3.connect(self.path)
        self.assertEqual(check.execute("SELECT x FROM t").fetchall(), [(1,)])
        check.close()

    def test_rollback_then_close_and_exception_propagates(self):
        with sqlite3.connect(self.path, factory=ClosingConnection) as db:
            db.execute("CREATE TABLE t(x)")
        with self.assertRaises(RuntimeError):
            with sqlite3.connect(self.path, factory=ClosingConnection) as db:
                db.execute("INSERT INTO t VALUES (2)")
                raise RuntimeError("boom")
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute("SELECT 1")
        check = sqlite3.connect(self.path)
        self.assertEqual(check.execute("SELECT count(*) FROM t").fetchone(), (0,))
        check.close()

    def test_application_stores_use_closing_connections(self):
        with tempfile.TemporaryDirectory() as data, mock.patch.dict(os.environ, {"CYBERCHECK_DATA_DIR": data}):
            for name in MODULES:
                module = importlib.import_module(name)
                source = Path(module.__file__).read_text(encoding="utf-8")
                self.assertIn("factory=ClosingConnection", source, name)


if __name__ == "__main__":
    unittest.main()
