"""Regression: redundant Sentinel schema DDL must not stall cold Passenger logins."""
from __future__ import annotations

import ast
from pathlib import Path
import os
import tempfile
import unittest
from unittest import mock

import security_guard as security
from customer_schema_once import SchemaOnce


class SecurityStartupOnceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "security.sqlite3"

    def test_repeated_runtime_init_does_not_execute_ddl_twice(self):
        def initialize():
            self.db.touch()
        with mock.patch.object(security, "DB", self.db), \
             mock.patch.object(security, "_SCHEMA_ONCE", SchemaOnce()), \
             mock.patch.object(security, "init_db", side_effect=initialize) as init:
            security.ensure_db()
            security.ensure_db()
            self.assertEqual(init.call_count, 1)

    def test_database_replacement_invalidates_cached_schema(self):
        def initialize():
            self.db.touch()
        with mock.patch.object(security, "DB", self.db), \
             mock.patch.object(security, "_SCHEMA_ONCE", SchemaOnce()), \
             mock.patch.object(security, "init_db", side_effect=initialize) as init:
            security.ensure_db()
            self.db.unlink()
            security.ensure_db()
            self.assertEqual(init.call_count, 2)

    def test_worker_pid_change_forces_schema_requalification(self):
        def initialize():
            self.db.touch()
        with mock.patch.object(security, "DB", self.db), \
             mock.patch.object(security, "_SCHEMA_ONCE", SchemaOnce()), \
             mock.patch.object(security, "init_db", side_effect=initialize) as init, \
             mock.patch("customer_schema_once.os.getpid", side_effect=(42, 42, 42, 43, 43)):
            security.ensure_db()
            security.ensure_db()
            self.assertEqual(init.call_count, 2)

    def test_failed_schema_init_is_not_cached_as_ready(self):
        count = 0

        def initialize():
            nonlocal count
            count += 1
            if count == 1:
                raise RuntimeError("transient SQLITE_BUSY simulation")
            self.db.touch()

        with mock.patch.object(security, "DB", self.db), \
             mock.patch.object(security, "_SCHEMA_ONCE", SchemaOnce()), \
             mock.patch.object(security, "init_db", side_effect=initialize):
            with self.assertRaises(RuntimeError):
                security.ensure_db()
            security.ensure_db()
            self.assertEqual(count, 2)

    def test_symlink_db_fails_closed_even_if_initializer_returns(self):
        target = Path(self.tmp.name) / "other"
        target.touch()
        self.db.symlink_to(target)
        with mock.patch.object(security, "DB", self.db), \
             mock.patch.object(security, "_SCHEMA_ONCE", SchemaOnce()), \
             mock.patch.object(security, "init_db") as init:
            with self.assertRaises(RuntimeError):
                security.ensure_db()
            init.assert_called_once()

    def test_admin_runtime_uses_existing_security_schema_gate(self):
        source = Path(__file__).with_name("admin_server.py").read_text(encoding="utf-8")
        self.assertIn("('security',security.ensure_db)", source)
        self.assertNotIn("('security',security.init_db)", source)
        syntax = ast.parse(source)
        self.assertIsNotNone(syntax)


if __name__ == "__main__":
    unittest.main()
