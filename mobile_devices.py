from __future__ import annotations

import datetime
import hashlib
import hmac
import os
import re
import sqlite3
import uuid
from pathlib import Path

DATA_DIR = Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData"))
DB = DATA_DIR / "mobile-devices.sqlite3"
_TOKEN_RE = re.compile(r"^[0-9a-fA-F]{32,400}$")
_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _install_id(value: object) -> str:
    raw = str(value or "").strip().lower()
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise ValueError("installationId invalide") from exc
    if str(parsed) != raw:
        raise ValueError("installationId invalide")
    return raw


def _secret(value: object) -> str:
    raw = str(value or "").strip()
    if not _SECRET_RE.fullmatch(raw):
        raise ValueError("registrationSecret invalide")
    return raw


def _device_token(value: object) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) % 2 or not _TOKEN_RE.fullmatch(raw):
        raise ValueError("deviceToken invalide")
    return raw


def _environment(value: object) -> str:
    raw = str(value or "sandbox").strip().lower()
    if raw not in {"sandbox", "production"}:
        raise ValueError("environment invalide")
    return raw


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        DATA_DIR.chmod(0o700)
    except PermissionError:
        pass
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def init_db() -> None:
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS mobile_device(
          installation_id TEXT PRIMARY KEY,
          secret_hash TEXT NOT NULL,
          device_token TEXT NOT NULL,
          token_hash TEXT NOT NULL,
          environment TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          disabled_at TEXT NOT NULL DEFAULT ''
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_mobile_token_hash ON mobile_device(token_hash)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_mobile_active ON mobile_device(disabled_at,environment)")
    try:
        DB.chmod(0o600)
    except PermissionError:
        pass


def register(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("payload invalide")
    installation_id = _install_id(payload.get("installationId"))
    secret = _secret(payload.get("registrationSecret"))
    token = _device_token(payload.get("deviceToken"))
    environment = _environment(payload.get("environment"))
    secret_hash = _hash(secret)
    token_hash = _hash(token)
    now = _now_iso()
    init_db()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT secret_hash FROM mobile_device WHERE installation_id=?", (installation_id,)).fetchone()
        if row and not hmac.compare_digest(str(row["secret_hash"]), secret_hash):
            raise PermissionError("identité mobile refusée")
        db.execute(
            "UPDATE mobile_device SET device_token='',disabled_at=? WHERE token_hash=? AND installation_id<>? AND disabled_at=''",
            (now, token_hash, installation_id),
        )
        db.execute("""INSERT INTO mobile_device(
          installation_id,secret_hash,device_token,token_hash,environment,created_at,updated_at,last_seen_at,disabled_at
        ) VALUES(?,?,?,?,?,?,?,?, '')
        ON CONFLICT(installation_id) DO UPDATE SET
          device_token=excluded.device_token,token_hash=excluded.token_hash,environment=excluded.environment,
          updated_at=excluded.updated_at,last_seen_at=excluded.last_seen_at,disabled_at=''""",
          (installation_id, secret_hash, token, token_hash, environment, now, now, now),
        )
    return {"ok": True, "installationId": installation_id, "environment": environment, "registeredAt": now}


def unregister(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("payload invalide")
    installation_id = _install_id(payload.get("installationId"))
    secret_hash = _hash(_secret(payload.get("registrationSecret")))
    init_db(); now = _now_iso()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT secret_hash FROM mobile_device WHERE installation_id=?", (installation_id,)).fetchone()
        if not row:
            return {"ok": True, "removed": False}
        if not hmac.compare_digest(str(row["secret_hash"]), secret_hash):
            raise PermissionError("identité mobile refusée")
        db.execute("UPDATE mobile_device SET device_token='',disabled_at=?,updated_at=? WHERE installation_id=?", (now, now, installation_id))
    return {"ok": True, "removed": True}


def active_targets(environment: str | None = None) -> list[dict]:
    init_db()
    query = "SELECT installation_id,device_token,environment FROM mobile_device WHERE disabled_at='' AND device_token<>''"
    args: tuple = ()
    if environment:
        query += " AND environment=?"; args = (_environment(environment),)
    with connect() as db:
        return [dict(row) for row in db.execute(query, args)]


def status() -> dict:
    init_db()
    with connect() as db:
        total = int(db.execute("SELECT COUNT(*) n FROM mobile_device").fetchone()["n"])
        active = int(db.execute("SELECT COUNT(*) n FROM mobile_device WHERE disabled_at='' AND device_token<>''").fetchone()["n"])
        rows = db.execute("SELECT environment,COUNT(*) n FROM mobile_device WHERE disabled_at='' AND device_token<>'' GROUP BY environment")
        by_environment = {row["environment"]: int(row["n"]) for row in rows}
    return {"ok": True, "total": total, "active": active, "byEnvironment": by_environment,
            "privacy": "Les jetons APNs restent dans le stockage privé du serveur et ne sont jamais exposés par l'API d'administration."}
