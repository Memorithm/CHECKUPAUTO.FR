"""Offline preflight and fail-closed migration tests; never contact production."""
import importlib.util
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "customer_postgres_migrate", ROOT / "ops/postgres/customer-migrate.py"
)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class CustomerPostgresMigrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.accounts = root / "accounts.sqlite3"
        self.oidc = root / "oidc.sqlite3"
        ddl = (ROOT / "ops/postgres/customer-schema.sql").read_text()
        sql = ddl.replace("CREATE SCHEMA IF NOT EXISTS checkupauto_customer;", "")
        sql = sql.replace("checkupauto_customer.", "")
        for path in (self.accounts, self.oidc):
            with sqlite3.connect(path) as db:
                db.executescript(sql)

    def test_preflight_counts_tables_and_preserves_encrypted_bytes(self):
        with sqlite3.connect(self.accounts) as db:
            db.execute(
                "INSERT INTO customer_account(account_id,kind,email_hash,profile_blob,"
                "created_at,updated_at) VALUES(?,?,?,?,?,?)",
                ("A", "individual", "a" * 64, b"\x00\xffencrypted", "now", "now"),
            )
        result = migration.migrate(self.accounts, self.oidc)
        self.assertFalse(result["copied"])
        self.assertEqual(result["counts"]["customer_account"], 1)
        self.assertEqual(result["counts"]["customer_oidc_flow"], 0)
        with sqlite3.connect(self.accounts) as db:
            self.assertEqual(db.execute(
                "SELECT profile_blob FROM customer_account"
            ).fetchone()[0], b"\x00\xffencrypted")

    def test_no_staging_freeze_means_no_postgres_connect(self):
        with mock.patch.dict(os.environ, {"CHECKUPAUTO_ENVIRONMENT": "staging",
                                       "PGSERVICE": "staging",
                                       "PGSSLMODE": "verify-full",
                                       "PGSSLROOTCERT": "/etc/ssl/root.pem"}), \
             mock.patch("migration_write_freeze.status", return_value={"active": False, "valid": True}):
            with self.assertRaisesRegex(RuntimeError, "freeze_required"):
                migration.migrate(self.accounts, self.oidc, apply=True, confirmed=True)

    def test_plaintext_or_insecure_pg_transport_is_refused(self):
        with mock.patch.dict(os.environ, {"CHECKUPAUTO_ENVIRONMENT": "staging",
                                       "PGSERVICE": "staging", "PGSSLMODE": "disable",
                                       "PGSSLROOTCERT": "/etc/ssl/root.pem"}), \
             mock.patch("migration_write_freeze.status", return_value={"active": True, "valid": True}):
            with self.assertRaisesRegex(RuntimeError, "tls_service_required"):
                migration.migrate(self.accounts, self.oidc, apply=True, confirmed=True)

    def test_symlink_source_refused(self):
        alias = self.accounts.parent / "alias.sqlite3"
        alias.symlink_to(self.accounts)
        with self.assertRaisesRegex(RuntimeError, "source_symlink"):
            migration.migrate(alias, self.oidc)

    def test_integrity_digest_detects_blob_modification(self):
        expected = migration._digest([(1, b"\x00\xff"), ("alpha",)])
        self.assertNotEqual(expected, migration._digest([(1, b"\x00\xfe"), ("alpha",)]))
        self.assertNotEqual(expected, migration._digest([(1, b"\x00\xff"), ("bravo",)]))


if __name__ == "__main__":
    unittest.main()
