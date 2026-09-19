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
MAX_DEADLINES_PER_INSTALLATION = 24


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


def _deadline_id(value: object) -> str:
    raw = str(value or "").strip().lower()
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise ValueError("deadlineId invalide") from exc
    if str(parsed) != raw:
        raise ValueError("deadlineId invalide")
    return raw


def _due_date(value: object) -> str:
    raw = str(value or "").strip()
    try:
        parsed = datetime.date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError("dueDate invalide") from exc
    if parsed.year < 2020 or parsed.year > 2100:
        raise ValueError("dueDate invalide")
    return parsed.isoformat()


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
          disabled_at TEXT NOT NULL DEFAULT '',
          disabled_reason TEXT NOT NULL DEFAULT ''
        )""")
        columns = {str(row["name"]) for row in db.execute("PRAGMA table_info(mobile_device)")}
        if "disabled_reason" not in columns:
            db.execute("ALTER TABLE mobile_device ADD COLUMN disabled_reason TEXT NOT NULL DEFAULT ''")
        db.execute("CREATE INDEX IF NOT EXISTS idx_mobile_token_hash ON mobile_device(token_hash)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_mobile_active ON mobile_device(disabled_at,environment)")
        db.execute("""CREATE TABLE IF NOT EXISTS mobile_deadline(
          installation_id TEXT NOT NULL,
          deadline_id TEXT NOT NULL,
          due_date TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(installation_id,deadline_id)
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_mobile_deadline_due ON mobile_deadline(due_date)")
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
        conflicts = [str(item["installation_id"]) for item in db.execute(
            "SELECT installation_id FROM mobile_device WHERE token_hash=? AND installation_id<>? AND disabled_at=''",
            (token_hash, installation_id),
        )]
        for conflict_id in conflicts:
            db.execute("DELETE FROM mobile_deadline WHERE installation_id=?", (conflict_id,))
        db.execute(
            "UPDATE mobile_device SET device_token='',disabled_at=?,disabled_reason='token_reassigned' WHERE token_hash=? AND installation_id<>? AND disabled_at=''",
            (now, token_hash, installation_id),
        )
        db.execute("""INSERT INTO mobile_device(
          installation_id,secret_hash,device_token,token_hash,environment,created_at,updated_at,last_seen_at,disabled_at
        ) VALUES(?,?,?,?,?,?,?,?, '')
        ON CONFLICT(installation_id) DO UPDATE SET
          device_token=excluded.device_token,token_hash=excluded.token_hash,environment=excluded.environment,
          updated_at=excluded.updated_at,last_seen_at=excluded.last_seen_at,disabled_at='',disabled_reason=''""",
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
        db.execute("UPDATE mobile_device SET device_token='',disabled_at=?,disabled_reason='client_unregister',updated_at=? WHERE installation_id=?", (now, now, installation_id))
        db.execute("DELETE FROM mobile_deadline WHERE installation_id=?", (installation_id,))
    return {"ok": True, "removed": True}



def disable_invalid_token(installation_id: str, device_token: str, reason: str) -> dict:
    installation_id = _install_id(installation_id)
    token = _device_token(device_token)
    clean_reason = re.sub(r"[^A-Za-z0-9_.:-]", "_", str(reason or "invalid_token"))[:80] or "invalid_token"
    token_hash = _hash(token)
    init_db(); now = _now_iso()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT token_hash,disabled_at FROM mobile_device WHERE installation_id=?",
            (installation_id,),
        ).fetchone()
        if not row or row["disabled_at"] or not hmac.compare_digest(str(row["token_hash"]), token_hash):
            return {"ok": True, "disabled": False}
        db.execute(
            "UPDATE mobile_device SET device_token='',disabled_at=?,disabled_reason=?,updated_at=? WHERE installation_id=?",
            (now, clean_reason, now, installation_id),
        )
        db.execute("DELETE FROM mobile_deadline WHERE installation_id=?", (installation_id,))
    return {"ok": True, "disabled": True, "reason": clean_reason, "disabledAt": now}


def _authenticated_device(db: sqlite3.Connection, installation_id: str, secret_hash: str) -> sqlite3.Row:
    row = db.execute(
        "SELECT installation_id,secret_hash,device_token,environment,disabled_at FROM mobile_device WHERE installation_id=?",
        (installation_id,),
    ).fetchone()
    if not row or row["disabled_at"] or not row["device_token"] or not hmac.compare_digest(str(row["secret_hash"]), secret_hash):
        raise PermissionError("identité mobile refusée")
    return row


def sync_deadlines(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("payload invalide")
    installation_id = _install_id(payload.get("installationId"))
    secret_hash = _hash(_secret(payload.get("registrationSecret")))
    raw_deadlines = payload.get("deadlines")
    if not isinstance(raw_deadlines, list) or len(raw_deadlines) > MAX_DEADLINES_PER_INSTALLATION:
        raise ValueError("deadlines invalides")
    deadlines: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in raw_deadlines:
        if not isinstance(item, dict):
            raise ValueError("deadline invalide")
        deadline_id = _deadline_id(item.get("deadlineId"))
        if deadline_id in seen:
            raise ValueError("deadlineId dupliqué")
        seen.add(deadline_id)
        deadlines.append((deadline_id, _due_date(item.get("dueDate"))))

    init_db(); now = _now_iso()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        _authenticated_device(db, installation_id, secret_hash)
        if deadlines:
            placeholders = ",".join("?" for _ in deadlines)
            db.execute(
                f"DELETE FROM mobile_deadline WHERE installation_id=? AND deadline_id NOT IN ({placeholders})",
                (installation_id, *(deadline_id for deadline_id, _ in deadlines)),
            )
        else:
            db.execute("DELETE FROM mobile_deadline WHERE installation_id=?", (installation_id,))
        for deadline_id, due_date in deadlines:
            db.execute(
                """INSERT INTO mobile_deadline(installation_id,deadline_id,due_date,created_at,updated_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(installation_id,deadline_id) DO UPDATE SET
                   due_date=excluded.due_date,updated_at=excluded.updated_at""",
                (installation_id, deadline_id, due_date, now, now),
            )
    return {"ok": True, "installationId": installation_id, "deadlineCount": len(deadlines), "syncedAt": now}


def due_targets(start_date: str, end_date: str) -> list[dict]:
    start = _due_date(start_date); end = _due_date(end_date)
    if end < start:
        raise ValueError("plage de dates invalide")
    init_db()
    with connect() as db:
        rows = db.execute(
            """SELECT d.installation_id,d.deadline_id,d.due_date,m.device_token,m.environment
               FROM mobile_deadline d JOIN mobile_device m ON m.installation_id=d.installation_id
               WHERE d.due_date>=? AND d.due_date<=? AND m.disabled_at='' AND m.device_token<>''
               ORDER BY d.due_date,d.installation_id,d.deadline_id""",
            (start, end),
        )
        return [dict(row) for row in rows]


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
        deadlines = int(db.execute("SELECT COUNT(*) n FROM mobile_deadline").fetchone()["n"])
        installations_with_deadlines = int(db.execute("SELECT COUNT(DISTINCT installation_id) n FROM mobile_deadline").fetchone()["n"])
        disabled_rows = db.execute("SELECT disabled_reason,COUNT(*) n FROM mobile_device WHERE disabled_at<>'' GROUP BY disabled_reason")
        disabled_by_reason = {str(row["disabled_reason"] or "unspecified"): int(row["n"]) for row in disabled_rows}
    return {"ok": True, "total": total, "active": active, "byEnvironment": by_environment,
            "disabledByReason": disabled_by_reason,
            "deadlines": deadlines, "installationsWithDeadlines": installations_with_deadlines,
            "privacy": "Les jetons APNs et les échéances mobiles restent dans le stockage privé du serveur ; seules des échéances opaques sans immatriculation sont conservées."}
