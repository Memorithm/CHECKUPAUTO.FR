"""Regression: customer/OIDC hot paths must not execute DDL on every request."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

import customer_schema_once
import customer_accounts
import customer_oidc


class SchemaOnceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.private = self.root / "private"
        self.data.mkdir()
        self.private.mkdir()
        env = patch.dict(os.environ, {
            "CYBERCHECK_DATA_DIR": str(self.data),
            "CYBERCHECK_PRIVATE_DIR": str(self.private),
        })
        env.start()
        self.addCleanup(env.stop)
        # These singleton gates may have seen other roots in this test worker.
        self.account_gate = patch.object(customer_accounts, "_SCHEMA_ONCE",
                                         customer_schema_once.SchemaOnce())
        self.account_gate.start()
        self.addCleanup(self.account_gate.stop)
        self.oidc_gate = patch.object(customer_oidc, "_SCHEMA_ONCE",
                                      customer_schema_once.SchemaOnce())
        self.oidc_gate.start()
        self.addCleanup(self.oidc_gate.stop)

    def test_ensure_only_initializes_once_until_database_is_replaced(self):
        gate = customer_schema_once.SchemaOnce()
        db = self.data / "test.sqlite3"
        calls = []
        def initialize():
            calls.append(True)
            db.touch()
        gate.ensure(db, initialize)
        gate.ensure(db, initialize)
        self.assertEqual(len(calls), 1)
        db.unlink()
        gate.ensure(db, initialize)
        self.assertEqual(len(calls), 2)
        with patch.object(customer_schema_once.os, "getpid", return_value=987123):
            gate.ensure(db, initialize)
        self.assertEqual(len(calls), 3)

    def test_failed_schema_init_retries_and_never_marks_ready(self):
        gate = customer_schema_once.SchemaOnce()
        db = self.data / "test.sqlite3"
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            gate.ensure(db, lambda: None)
        calls = []
        gate.ensure(db, lambda: (calls.append(True), db.touch()))
        gate.ensure(db, lambda: calls.append(True))
        self.assertEqual(len(calls), 1)

    def test_concurrent_ensure_serializes_ddl(self):
        gate = customer_schema_once.SchemaOnce()
        db = self.data / "test.sqlite3"
        calls = []
        def initialize():
            calls.append(1)
            db.touch()
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: gate.ensure(db, initialize), range(40)))
        self.assertEqual(len(calls), 1)

    def test_accounts_hot_path_reuses_existing_schema(self):
        customer_accounts._ensure_schema()
        self.assertTrue(customer_accounts.data_path().is_file())
        with patch.object(customer_accounts, "init_db",
                          side_effect=AssertionError("DDL on warm request")):
            customer_accounts._ensure_schema()
            customer_accounts._ensure_schema()

    def test_oidc_hot_path_reuses_existing_schema(self):
        customer_oidc._ensure_schema()
        self.assertTrue(customer_oidc._flow_path().is_file())
        with patch.object(customer_oidc, "init_db",
                          side_effect=AssertionError("DDL on warm request")):
            customer_oidc._ensure_schema()
            customer_oidc._ensure_schema()

    def test_explicit_init_db_still_repairs_legacy_oidc_schema(self):
        import sqlite3
        path = customer_oidc._flow_path()
        with sqlite3.connect(path) as db:
            db.execute(
                "CREATE TABLE customer_oidc_flow("
                "state_hash TEXT PRIMARY KEY, provider TEXT, nonce TEXT, verifier TEXT,"
                "redirect_uri TEXT, created_at TEXT, expires_at TEXT)"
            )
        customer_oidc.init_db()
        with sqlite3.connect(path) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(customer_oidc_flow)")}
        self.assertIn("browser_hash", columns)
        self.assertIn("mobile_challenge", columns)


if __name__ == "__main__":
    unittest.main()
