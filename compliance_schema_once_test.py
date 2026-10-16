"""Compliance SQLite initialization must not serialize every ordinary account access."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import compliance_store as compliance
from customer_schema_once import SchemaOnce


class ComplianceSchemaOnceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "compliance.sqlite3"

    def test_ordinary_access_does_not_repeat_compliance_ddl(self):
        original = compliance.init_db
        with mock.patch.object(compliance, "_SCHEMA_ONCE", SchemaOnce()), \
             mock.patch.object(compliance, "init_db", wraps=original) as init:
            self.assertEqual(compliance.settings(self.db)["controllerName"], "")
            self.assertEqual(compliance.settings(self.db)["controllerName"], "")
            self.assertEqual(init.call_count, 1)
            # Explicit migrations/repair must never be bypassed by this cache.
            compliance.init_db(self.db)
            self.assertEqual(init.call_count, 2)

    def test_db_replacement_triggers_real_schema_initialization(self):
        with mock.patch.object(compliance, "_SCHEMA_ONCE", SchemaOnce()):
            compliance.ensure_db(self.db)
            with compliance.connect(self.db) as db:
                db.execute("UPDATE compliance_settings SET payload=? WHERE id=1",
                           ('{"controllerName":"existing"}',))
            self.assertEqual(compliance.settings(self.db)["controllerName"], "existing")
            self.db.unlink()
            # New DB must contain initialized tables and not inherit old PII.
            self.assertEqual(compliance.settings(self.db)["controllerName"], "")
            with sqlite3.connect(self.db) as db:
                self.assertIsNotNone(db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='compliance_settings'"
                ).fetchone())

    def test_worker_pid_change_reinitializes_once(self):
        pid = [50]
        original = compliance.init_db
        with mock.patch.object(compliance, "_SCHEMA_ONCE", SchemaOnce()), \
             mock.patch.object(compliance, "init_db", wraps=original) as init, \
             mock.patch("customer_schema_once.os.getpid", side_effect=lambda: pid[0]):
            compliance.ensure_db(self.db)
            compliance.ensure_db(self.db)
            self.assertEqual(init.call_count, 1)
            pid[0] = 51
            compliance.ensure_db(self.db)
            self.assertEqual(init.call_count, 2)

    def test_failed_initializer_does_not_mark_schema_ready(self):
        original = compliance.init_db
        count = [0]

        def fails_once(db_path):
            count[0] += 1
            if count[0] == 1:
                raise sqlite3.OperationalError("SQLITE_BUSY")
            return original(db_path)

        with mock.patch.object(compliance, "_SCHEMA_ONCE", SchemaOnce()), \
             mock.patch.object(compliance, "init_db", side_effect=fails_once):
            with self.assertRaises(sqlite3.OperationalError):
                compliance.ensure_db(self.db)
            compliance.ensure_db(self.db)
            self.assertEqual(count[0], 2)

    def test_symlink_database_is_not_cached_as_valid(self):
        target = Path(self.tmp.name) / "target.sqlite3"
        target.touch()
        self.db.symlink_to(target)
        with mock.patch.object(compliance, "_SCHEMA_ONCE", SchemaOnce()), \
             mock.patch.object(compliance, "init_db") as init:
            with self.assertRaises(RuntimeError):
                compliance.ensure_db(self.db)
            init.assert_called_once()

    def test_withdrawal_and_retention_use_guarded_compliance_initializer(self):
        import withdrawal_service
        import retention_enforcement
        with mock.patch.object(compliance, "init_db", wraps=compliance.init_db) as init, \
             mock.patch.object(compliance, "_SCHEMA_ONCE", SchemaOnce()):
            withdrawal_service.init_db(self.db)
            retention_enforcement.init_db(self.db)
            self.assertEqual(init.call_count, 1)
            with compliance.connect(self.db) as db:
                self.assertIsNotNone(db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='withdrawal_requests'"
                ).fetchone())
                self.assertIsNotNone(db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='retention_purge_audit'"
                ).fetchone())


if __name__ == "__main__":
    unittest.main()
