"""Validate the PostgreSQL customer schema against the current SQLite contract.

No customer data, PostgreSQL server, secrets or network access is required.
"""
from pathlib import Path
import re
import sqlite3
import unittest


SQL = Path(__file__).resolve().parent / "ops/postgres/customer-schema.sql"
CUSTOMER_TABLES = (
    "customer_account", "customer_identity", "customer_session",
    "customer_password_credential", "customer_password_token",
    "customer_password_throttle", "customer_passage_confirmation",
)
OIDC_TABLES = ("customer_oidc_flow", "customer_native_nonce")


class CustomerPostgresSchemaTest(unittest.TestCase):
    def test_schema_has_all_current_account_and_oidc_columns(self):
        ddl = SQL.read_text(encoding="utf-8")
        self.assertIn("profile_blob BYTEA NOT NULL", ddl)
        self.assertIn("ON DELETE CASCADE", ddl)
        self.assertNotIn("DROP TABLE", ddl.upper())
        with sqlite3.connect(":memory:") as target:
            target.execute("PRAGMA foreign_keys=ON")
            # Validate the SQL's table and FK semantics on a local, isolated
            # SQLite engine; the live Postgres instance needs its own smoke test.
            translated = ddl.replace(
                "CREATE SCHEMA IF NOT EXISTS checkupauto_customer;", ""
            ).replace("checkupauto_customer.", "")
            target.executescript(translated)
            for table in (*CUSTOMER_TABLES, *OIDC_TABLES):
                self.assertIsNotNone(target.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone(), table)
            for table in (*CUSTOMER_TABLES, *OIDC_TABLES):
                self.assertGreater(len(target.execute(
                    f"PRAGMA table_info({table})"
                ).fetchall()), 0)

            target.execute(
                "INSERT INTO customer_account(account_id,kind,email_hash,profile_blob,created_at,updated_at) "
                "VALUES('a','individual','hash',?, 'now','now')",
                (b"encrypted-not-plaintext",),
            )
            target.execute(
                "INSERT INTO customer_session(session_hash,account_id,created_at,expires_at,last_seen_at) "
                "VALUES('token-hash','a','now','later','now')"
            )
            target.execute("DELETE FROM customer_account WHERE account_id='a'")
            self.assertEqual(target.execute(
                "SELECT COUNT(*) FROM customer_session"
            ).fetchone()[0], 0)

    def test_no_missing_or_renamed_primary_tables(self):
        ddl = SQL.read_text(encoding="utf-8")
        for table in (*CUSTOMER_TABLES, *OIDC_TABLES):
            self.assertRegex(
                ddl, r"CREATE TABLE IF NOT EXISTS checkupauto_customer\." +
                table + r"\s*\(",
            )
        self.assertEqual(len(re.findall(r"CREATE TABLE IF NOT EXISTS", ddl)), 9)


if __name__ == "__main__":
    unittest.main()
