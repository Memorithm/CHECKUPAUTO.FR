"""Explicit PostgreSQL runtime for customer data; SQLite is the default.

The PostgreSQL path needs a verified stage copy, an operator-owned cutover
marker, a named libpq service and a trusted CA. No silent SQLite fallback.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import threading

_STAGE_TABLES = {
    "accounts": ("customer_account", "customer_identity", "customer_session",
                 "customer_password_credential", "customer_password_token",
                 "customer_password_throttle", "customer_passage_confirmation"),
    "oidc": ("customer_oidc_flow", "customer_native_nonce"),
}
_LOCK = threading.RLock()
_READY = set()
_WRITER_LOCK = 84575141621


def enabled():
    backend = os.environ.get("CHECKUPAUTO_CUSTOMER_DB_BACKEND", "sqlite").strip().lower()
    if backend not in {"sqlite", "postgres"}:
        raise RuntimeError("customer_db_backend_invalid")
    return backend == "postgres"


def _cutover_ready():
    path = Path(os.environ.get("CHECKUPAUTO_CUSTOMER_PG_CUTOVER_FILE", ""))
    if not path.is_absolute() or path.is_symlink():
        raise RuntimeError("customer_pg_cutover_marker_missing")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077:
            raise PermissionError("customer_pg_cutover_marker_insecure")
        raw = os.read(fd, 128)
        if raw.strip() != b"CHECKUPAUTO_CUSTOMER_POSTGRES_CUTOVER_V1":
            raise RuntimeError("customer_pg_cutover_marker_invalid")
    finally:
        os.close(fd)


class Row(dict):
    def __init__(self, names, values):
        super().__init__(zip(names, values))
        self._values = values

    def __getitem__(self, key):
        return self._values[key] if isinstance(key, int) else super().__getitem__(key)


def _row_factory(cursor):
    names = tuple(col.name for col in cursor.description)
    return lambda values: Row(names, values)


class Connection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, query, args=None):
        statement = query.strip()
        if statement == "BEGIN IMMEDIATE":
            # Conservative serialization while the legacy read-modify-write
            # statements are audited for PostgreSQL row-level locks.
            return self.raw.execute("SELECT pg_advisory_xact_lock(%s)", (_WRITER_LOCK,))
        if statement == "PRAGMA foreign_keys=ON":
            return None
        return self.raw.execute(statement.replace("?", "%s"), args)

    def __enter__(self):
        self.raw.__enter__()
        return self

    def __exit__(self, *args):
        return self.raw.__exit__(*args)

    def close(self):
        return self.raw.close()

    def commit(self):
        return self.raw.commit()

    def rollback(self):
        return self.raw.rollback()


def connect():
    if not enabled():
        raise RuntimeError("customer_pg_backend_not_enabled")
    _cutover_ready()
    service = os.environ.get("CHECKUPAUTO_CUSTOMER_PG_SERVICE", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", service):
        raise RuntimeError("customer_pg_service_invalid")
    ca = Path(os.environ.get("CHECKUPAUTO_CUSTOMER_PG_CA", ""))
    if not ca.is_absolute() or ca.is_symlink() or not ca.is_file():
        raise RuntimeError("customer_pg_ca_missing")
    try:
        import psycopg
    except ImportError:
        raise RuntimeError("customer_pg_driver_missing") from None
    # Explicit keyword parameters supersede service defaults. Require
    # verified hostname, pinned CA and an upper bound on blocked statements.
    raw = psycopg.connect(
        service=service, sslmode="verify-full", sslrootcert=str(ca),
        connect_timeout=5, row_factory=_row_factory,
        options="-c statement_timeout=8000 -c lock_timeout=1500",
    )
    try:
        raw.execute("SET search_path TO checkupauto_customer, pg_catalog")
    except BaseException:
        raw.close()
        raise
    return Connection(raw)


def assert_schema(kind):
    if kind not in _STAGE_TABLES:
        raise ValueError("customer_pg_schema_kind_invalid")
    key = (os.getpid(), kind)
    with _LOCK:
        if key in _READY:
            return
        with connect() as db:
            for table in _STAGE_TABLES[kind]:
                row = db.execute("SELECT to_regclass(%s)", (
                    "checkupauto_customer." + table,
                )).fetchone()
                if row is None or row[0] is None:
                    raise RuntimeError("customer_pg_schema_not_ready")
        _READY.add(key)
