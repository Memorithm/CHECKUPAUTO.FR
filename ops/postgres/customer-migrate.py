"""Fail-closed SQLite -> PostgreSQL customer staging copy.

Default is dry-run only. --apply requires an explicit staging-only write freeze,
preprovisioned empty PostgreSQL schema and secure libpq service settings.
Never logs profile data, session tokens, OIDC state, SQL rows or credentials.
Does not change the running application's database backend.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sqlite3
import stat

TABLES = (
    ("customer_account", "accounts", "account_id"),
    ("customer_identity", "accounts", "provider,subject_hash"),
    ("customer_session", "accounts", "session_hash"),
    ("customer_password_credential", "accounts", "account_id"),
    ("customer_password_token", "accounts", "token_hash"),
    ("customer_password_throttle", "accounts", "account_id,client_key"),
    ("customer_passage_confirmation", "accounts", "passage_hash"),
    ("customer_oidc_flow", "oidc", "state_hash"),
    ("customer_native_nonce", "oidc", "nonce_hash"),
)


def _source(path):
    p = Path(path)
    if p.is_symlink():
        raise RuntimeError("customer_migration_source_symlink")
    info = p.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
        raise RuntimeError("customer_migration_source_invalid")
    uri = p.resolve().as_uri() + "?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _rows(db, name, order):
    cols = tuple(row[1] for row in db.execute(f"PRAGMA table_info({name})"))
    if not cols:
        raise RuntimeError("customer_migration_source_schema_missing")
    if not all(c.isidentifier() for c in cols):
        raise RuntimeError("customer_migration_source_schema_invalid")
    return cols, db.execute(
        f"SELECT {','.join(cols)} FROM {name} ORDER BY {order}"
    ).fetchall()


def _digest(rows):
    h = hashlib.sha256()
    for row in rows:
        for field in row:
            if field is None:
                item = b"n"
            elif isinstance(field, (bytes, bytearray, memoryview)):
                item = b"b" + bytes(field)
            else:
                item = b"s" + str(field).encode("utf-8")
            h.update(len(item).to_bytes(8, "big"))
            h.update(item)
    return h.digest()


def snapshot(account_db, oidc_db):
    result = {}
    for table, source, order in TABLES:
        columns, rows = _rows(account_db if source == "accounts" else oidc_db, table, order)
        result[table] = (columns, rows, _digest(rows))
    return result


def migrate(account_path, oidc_path, *, apply=False, confirmed=False, connector=None):
    import migration_write_freeze

    if apply:
        freeze = migration_write_freeze.status()
        if (not confirmed or os.environ.get("CHECKUPAUTO_ENVIRONMENT") != "staging"
                or not freeze.get("active") or not freeze.get("valid")):
            raise RuntimeError("customer_migration_staging_freeze_required")
        if not os.environ.get("PGSERVICE") or os.environ.get("PGSSLMODE") != "verify-full":
            raise RuntimeError("customer_migration_tls_service_required")
        if not os.environ.get("PGSSLROOTCERT"):
            raise RuntimeError("customer_migration_ca_required")

    with _source(account_path) as accounts, _source(oidc_path) as oidc:
        before = snapshot(accounts, oidc)
        counts = {table: len(before[table][1]) for table, _, _ in TABLES}
        if not apply:
            return {"mode": "preflight", "counts": counts, "copied": False}

        # Import only in the standalone maintenance process, never Passenger.
        if connector is None:
            try:
                import psycopg
                from psycopg import sql
            except ImportError:
                raise RuntimeError("customer_migration_postgres_driver_missing") from None
            connector = psycopg.connect
        else:
            from psycopg import sql

        with connector(connect_timeout=5, options="-c statement_timeout=30000") as target:
            # PGSERVICE entries may override libpq environment defaults.
            # Verify the effective policy and the actual transport before copy.
            effective = target.info.get_parameters()
            if (effective.get("sslmode") != "verify-full"
                    or not effective.get("sslrootcert")):
                raise RuntimeError("customer_migration_tls_verification_missing")
            with target.cursor() as transport:
                transport.execute("SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()")
                active_tls = transport.fetchone()
            if not active_tls or active_tls[0] is not True:
                raise RuntimeError("customer_migration_tls_not_active")
            for table, _, _ in TABLES:
                qualified = sql.SQL("checkupauto_customer.{}").format(sql.Identifier(table))
                with target.cursor() as cursor:
                    cursor.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(qualified))
                    if cursor.fetchone()[0] != 0:
                        raise RuntimeError("customer_migration_destination_not_empty")

            for table, _, order in TABLES:
                columns, rows, expected = before[table]
                qualified = sql.SQL("checkupauto_customer.{}").format(sql.Identifier(table))
                identifiers = sql.SQL(",").join(map(sql.Identifier, columns))
                placeholders = sql.SQL(",").join(sql.Placeholder() for _ in columns)
                with target.cursor() as cursor:
                    if rows:
                        cursor.executemany(
                            sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                                qualified, identifiers, placeholders
                            ), rows,
                        )
                    cursor.execute(
                        sql.SQL("SELECT {} FROM {} ORDER BY {}").format(
                            identifiers, qualified,
                            sql.SQL(",").join(map(sql.Identifier, order.split(","))),
                        )
                    )
                    destination_rows = cursor.fetchall()
                    if len(destination_rows) != len(rows) or _digest(destination_rows) != expected:
                        raise RuntimeError("customer_migration_integrity_mismatch")
            # Fail closed if any external writer bypassed the staging freeze.
            after = snapshot(accounts, oidc)
            if any(after[name][2] != before[name][2] for name, _, _ in TABLES):
                raise RuntimeError("customer_migration_source_changed")
        return {"mode": "copied", "counts": counts, "copied": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--accounts", required=True)
    parser.add_argument("--oidc", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    result = migrate(args.accounts, args.oidc, apply=args.apply,
                     confirmed=args.confirm == "STAGING_PG_COPY")
    # No customer, credential or even table content is printed.
    print(f"CUSTOMER_POSTGRES_COPY mode={result['mode']} copied={result['copied']}")
    for key, count in result["counts"].items():
        print(f"CUSTOMER_POSTGRES_ROWS table={key} count={count}")


if __name__ == "__main__":
    main()
