"""PostgreSQL customer runtime compatibility tests; no live database required."""
from pathlib import Path
import os
import tempfile
import unittest
from unittest import mock

import customer_accounts
import customer_oidc
import customer_postgres_runtime as pg


class CustomerPostgresRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.addCleanup(pg._READY.clear)
        pg._READY.clear()

    def test_sqlite_is_the_default_and_invalid_backend_fails_closed(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(pg.enabled())
        with mock.patch.dict(os.environ, {"CHECKUPAUTO_CUSTOMER_DB_BACKEND": "invalid"}):
            with self.assertRaisesRegex(RuntimeError, "backend_invalid"):
                pg.enabled()

    def test_pg_mode_never_silently_falls_back_to_sqlite(self):
        with mock.patch.dict(os.environ, {"CHECKUPAUTO_CUSTOMER_DB_BACKEND": "postgres"},
                             clear=True), \
             mock.patch("customer_accounts.sqlite3.connect") as sqlite:
            with self.assertRaises(RuntimeError):
                customer_accounts._connect()
            sqlite.assert_not_called()

    def test_cutover_marker_must_be_private_regular_file(self):
        marker = self.root / "cutover"
        marker.write_text("CHECKUPAUTO_CUSTOMER_POSTGRES_CUTOVER_V1")
        marker.chmod(0o600)
        with mock.patch.dict(os.environ, {"CHECKUPAUTO_CUSTOMER_PG_CUTOVER_FILE": str(marker)}):
            pg._cutover_ready()
            marker.chmod(0o644)
            with self.assertRaises(PermissionError):
                pg._cutover_ready()
        target = self.root / "target"
        target.write_text("CHECKUPAUTO_CUSTOMER_POSTGRES_CUTOVER_V1")
        alias = self.root / "alias"
        alias.symlink_to(target)
        with mock.patch.dict(os.environ, {"CHECKUPAUTO_CUSTOMER_PG_CUTOVER_FILE": str(alias)}):
            with self.assertRaises(RuntimeError):
                pg._cutover_ready()

    def test_row_matches_sqlite_position_and_mapping_semantics(self):
        row = pg.Row(("account_id", "expires_at"), ("a", "tomorrow"))
        self.assertEqual(row["account_id"], "a")
        self.assertEqual(row[0], "a")
        self.assertEqual(row[1], "tomorrow")
        self.assertEqual(dict(row)["expires_at"], "tomorrow")

    def test_sqlite_write_transaction_becomes_conservative_pg_advisory_lock(self):
        raw = mock.Mock()
        adapter = pg.Connection(raw)
        adapter.execute("BEGIN IMMEDIATE")
        raw.execute.assert_called_with(
            "SELECT pg_advisory_xact_lock(%s)", (pg._WRITER_LOCK,),
        )
        adapter.execute(
            "SELECT account_id FROM customer_account WHERE email_hash=?",
            ("hash",),
        )
        raw.execute.assert_called_with(
            "SELECT account_id FROM customer_account WHERE email_hash=%s",
            ("hash",),
        )

    def test_postgres_schema_is_read_only_runtime_gate(self):
        cur = mock.Mock()
        cur.fetchone.return_value = ("checkupauto_customer.customer_account",)
        connection = mock.MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value = cur
        with mock.patch.object(pg, "connect", return_value=connection), \
             mock.patch.object(pg.os, "getpid", return_value=4321):
            pg.assert_schema("accounts")
            self.assertEqual(connection.execute.call_count, 7)
            pg.assert_schema("accounts")
            self.assertEqual(connection.execute.call_count, 7)
            pg.assert_schema("oidc")
            self.assertEqual(connection.execute.call_count, 9)
        self.assertTrue(all(
            call.args[0].startswith("SELECT to_regclass")
            for call in connection.execute.call_args_list
        ))

    def test_missing_postgres_table_fails_closed(self):
        cur = mock.Mock()
        cur.fetchone.return_value = (None,)
        connection = mock.MagicMock()
        connection.__enter__.return_value = connection
        connection.execute.return_value = cur
        with mock.patch.object(pg, "connect", return_value=connection):
            with self.assertRaisesRegex(RuntimeError, "schema_not_ready"):
                pg.assert_schema("oidc")

    def test_account_and_oidc_backends_both_route_to_postgres(self):
        with mock.patch.object(pg, "enabled", return_value=True), \
             mock.patch.object(pg, "connect", return_value="pg-only") as connect, \
             mock.patch.object(pg, "assert_schema") as assert_schema:
            self.assertEqual(customer_accounts._connect(), "pg-only")
            self.assertEqual(customer_oidc._connect(), "pg-only")
            customer_accounts._ensure_schema()
            customer_oidc._ensure_schema()
            self.assertEqual(connect.call_count, 2)
            assert_schema.assert_any_call("accounts")
            assert_schema.assert_any_call("oidc")
            with self.assertRaisesRegex(RuntimeError, "operator_only"):
                customer_accounts.init_db()
            with self.assertRaisesRegex(RuntimeError, "operator_only"):
                customer_oidc.init_db()


if __name__ == "__main__":
    unittest.main()
