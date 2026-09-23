from __future__ import annotations

import datetime
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import uuid
from pathlib import Path

import privacy_suppression as privacy

DATA_DIR = Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData"))
DB = DATA_DIR / "mobile-devices.sqlite3"
_TOKEN_RE = re.compile(r"^[0-9a-fA-F]{32,400}$")
_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_CLAIM_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_REFERRAL_WALLET_CLAIM_PREFIX = "rw_"
_VEHICLE_CLAIM_PREFIX = "vc_"
_PROVIDER_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
MAX_DEADLINES_PER_INSTALLATION = 24
DEVICE_DEADLINE_SOURCE = "device"
AUTHORITATIVE_DEADLINE_SOURCE = "mercure"


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


def _assert_processing_allowed(installation_id: str) -> None:
    if privacy.is_suppressed("installation", installation_id, "all_processing"):
        raise PermissionError("traitement mobile refusé")


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


def _provider_id(value: object, label: str) -> str:
    raw = str(value or "").strip()
    if not _PROVIDER_ID_RE.fullmatch(raw):
        raise ValueError(f"{label} invalide")
    return raw


def _client_kind(value: object) -> str:
    raw = str(value or "").strip().lower()
    if raw not in {"account", "free"}:
        raise ValueError("clientKind invalide")
    return raw


def _claim_token(value: object) -> str:
    raw = str(value or "").strip()
    if not _CLAIM_RE.fullmatch(raw) or raw.startswith(_REFERRAL_WALLET_CLAIM_PREFIX):
        raise ValueError("claimToken invalide")
    return raw


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
          source TEXT NOT NULL DEFAULT 'device',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY(installation_id,deadline_id)
        )""")
        deadline_columns = {str(row["name"]) for row in db.execute("PRAGMA table_info(mobile_deadline)")}
        if "source" not in deadline_columns:
            db.execute("ALTER TABLE mobile_deadline ADD COLUMN source TEXT NOT NULL DEFAULT 'device'")
        db.execute("CREATE INDEX IF NOT EXISTS idx_mobile_deadline_due ON mobile_deadline(due_date)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_mobile_deadline_source ON mobile_deadline(installation_id,source,due_date)")

        db.execute("""CREATE TABLE IF NOT EXISTS mobile_vehicle_claim(
          token_hash TEXT PRIMARY KEY,
          vehicle_id TEXT NOT NULL,
          client_kind TEXT NOT NULL,
          client_id TEXT NOT NULL,
          created_at TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          consumed_at TEXT NOT NULL DEFAULT ''
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_mobile_claim_expiry ON mobile_vehicle_claim(expires_at,consumed_at)")
        db.execute("""CREATE TABLE IF NOT EXISTS mobile_vehicle_binding(
          binding_id TEXT PRIMARY KEY,
          installation_id TEXT NOT NULL,
          vehicle_id TEXT NOT NULL,
          client_kind TEXT NOT NULL,
          client_id TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(installation_id,vehicle_id)
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_mobile_binding_install ON mobile_vehicle_binding(installation_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_mobile_binding_vehicle ON mobile_vehicle_binding(vehicle_id)")
    try:
        DB.chmod(0o600)
    except PermissionError:
        pass


def register_installation(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("payload invalide")
    installation_id = _install_id(payload.get("installationId"))
    _assert_processing_allowed(installation_id)
    secret_hash = _hash(_secret(payload.get("registrationSecret")))
    now = _now_iso()
    init_db()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT secret_hash FROM mobile_device WHERE installation_id=?",
            (installation_id,),
        ).fetchone()
        if row and not hmac.compare_digest(str(row["secret_hash"]), secret_hash):
            raise PermissionError("identité mobile refusée")
        db.execute(
            """INSERT INTO mobile_device(
                 installation_id,secret_hash,device_token,token_hash,environment,
                 created_at,updated_at,last_seen_at,disabled_at,disabled_reason
               ) VALUES(?,?,?,?,?,?,?,?, '', '')
               ON CONFLICT(installation_id) DO UPDATE SET
                 updated_at=excluded.updated_at,last_seen_at=excluded.last_seen_at""",
            (installation_id, secret_hash, "", "", "", now, now, now),
        )
    return {"ok": True, "installationId": installation_id, "registeredAt": now}


def register(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("payload invalide")
    installation_id = _install_id(payload.get("installationId"))
    _assert_processing_allowed(installation_id)
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
            db.execute("DELETE FROM mobile_vehicle_binding WHERE installation_id=?", (conflict_id,))
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


def delete_installation(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("payload invalide")
    installation_id = _install_id(payload.get("installationId"))
    secret_hash = _hash(_secret(payload.get("registrationSecret")))
    init_db()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT secret_hash FROM mobile_device WHERE installation_id=?",
            (installation_id,),
        ).fetchone()
        if not row:
            return {"ok": True, "removed": False}
        if not hmac.compare_digest(str(row["secret_hash"]), secret_hash):
            raise PermissionError("identité mobile refusée")
        db.execute("DELETE FROM mobile_deadline WHERE installation_id=?", (installation_id,))
        db.execute("DELETE FROM mobile_vehicle_binding WHERE installation_id=?", (installation_id,))
        db.execute("DELETE FROM mobile_device WHERE installation_id=?", (installation_id,))
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


def _authenticated_installation(db: sqlite3.Connection, installation_id: str, secret_hash: str) -> sqlite3.Row:
    _assert_processing_allowed(installation_id)
    row = db.execute(
        """SELECT installation_id,secret_hash,device_token,environment,disabled_at
           FROM mobile_device WHERE installation_id=?""",
        (installation_id,),
    ).fetchone()
    if not row or not hmac.compare_digest(str(row["secret_hash"]), secret_hash):
        raise PermissionError("identité mobile refusée")
    return row


def _authenticated_device(db: sqlite3.Connection, installation_id: str, secret_hash: str) -> sqlite3.Row:
    row = _authenticated_installation(db, installation_id, secret_hash)
    if row["disabled_at"] or not row["device_token"]:
        raise PermissionError("canal push mobile indisponible")
    return row


def issue_vehicle_claim(
    vehicle_id: object,
    client_kind: object,
    client_id: object,
    *,
    ttl_seconds: int = 1800,
) -> dict:
    """Create a high-entropy one-time vehicle claim.

    This function is intentionally internal-only. The raw token is returned exactly once
    to the trusted caller and is never persisted. New vehicle tokens use the reserved
    ``vc_`` namespace so they can never collide with referral-wallet ``rw_`` claims.
    """
    vehicle = _provider_id(vehicle_id, "vehicleId")
    kind = _client_kind(client_kind)
    client = _provider_id(client_id, "clientId")
    if privacy.any_suppressed(
        [("mercure_"+kind,client),("vehicle",vehicle)],
        "all_processing",
    ):
        raise PermissionError("claim mobile refusé")
    ttl = int(ttl_seconds)
    if ttl < 60 or ttl > 86400:
        raise ValueError("ttlSeconds invalide")
    token = _VEHICLE_CLAIM_PREFIX + secrets.token_urlsafe(32)
    token_hash = _hash(token)
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now = now_dt.isoformat(timespec="seconds")
    expires = (now_dt + datetime.timedelta(seconds=ttl)).isoformat(timespec="seconds")
    init_db()
    with connect() as db:
        db.execute(
            "DELETE FROM mobile_vehicle_claim WHERE consumed_at<>'' OR expires_at<=?",
            (now,),
        )
        db.execute(
            """INSERT INTO mobile_vehicle_claim(
                 token_hash,vehicle_id,client_kind,client_id,created_at,expires_at,consumed_at
               ) VALUES(?,?,?,?,?,?, '')""",
            (token_hash, vehicle, kind, client, now, expires),
        )
    return {"claimToken": token, "expiresAt": expires}


def consume_vehicle_claim(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("payload invalide")
    installation_id = _install_id(payload.get("installationId"))
    secret_hash = _hash(_secret(payload.get("registrationSecret")))
    token = _claim_token(payload.get("claimToken"))
    token_hash = _hash(token)
    now_dt = datetime.datetime.now(datetime.timezone.utc)
    now = now_dt.isoformat(timespec="seconds")
    init_db()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        _authenticated_installation(db, installation_id, secret_hash)
        claim = db.execute(
            """SELECT vehicle_id,client_kind,client_id,expires_at,consumed_at
               FROM mobile_vehicle_claim WHERE token_hash=?""",
            (token_hash,),
        ).fetchone()
        if not claim or claim["consumed_at"]:
            raise PermissionError("claim mobile refusé")
        if privacy.any_suppressed(
            [("mercure_"+str(claim["client_kind"]),str(claim["client_id"])),
             ("vehicle",str(claim["vehicle_id"]))],
            "all_processing",
        ):
            raise PermissionError("claim mobile refusé")
        try:
            expires = datetime.datetime.fromisoformat(str(claim["expires_at"]))
        except ValueError as exc:
            raise PermissionError("claim mobile refusé") from exc
        if expires <= now_dt:
            raise PermissionError("claim mobile refusé")

        existing = db.execute(
            """SELECT binding_id,created_at FROM mobile_vehicle_binding
               WHERE installation_id=? AND vehicle_id=?""",
            (installation_id, claim["vehicle_id"]),
        ).fetchone()
        binding_id = str(existing["binding_id"]) if existing else str(uuid.uuid4())
        created_at = str(existing["created_at"]) if existing else now
        db.execute(
            """INSERT INTO mobile_vehicle_binding(
                 binding_id,installation_id,vehicle_id,client_kind,client_id,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(installation_id,vehicle_id) DO UPDATE SET
                 client_kind=excluded.client_kind,client_id=excluded.client_id,
                 updated_at=excluded.updated_at""",
            (
                binding_id,
                installation_id,
                claim["vehicle_id"],
                claim["client_kind"],
                claim["client_id"],
                created_at,
                now,
            ),
        )
        db.execute(
            "DELETE FROM mobile_vehicle_claim WHERE token_hash=?",
            (token_hash,),
        )
    return {"ok": True, "bindingId": binding_id, "claimedAt": now}


def active_vehicle_bindings(installation_id: str | None = None) -> list[dict]:
    init_db()
    query = """SELECT b.binding_id,b.installation_id,b.vehicle_id,b.client_kind,b.client_id
               FROM mobile_vehicle_binding b
               JOIN mobile_device m ON m.installation_id=b.installation_id
               WHERE m.disabled_at='' AND m.device_token<>''"""
    args: tuple = ()
    if installation_id is not None:
        query += " AND b.installation_id=?"
        args = (_install_id(installation_id),)
    query += " ORDER BY b.installation_id,b.binding_id"
    with connect() as db:
        return [dict(row) for row in db.execute(query, args)]


def registered_vehicle_bindings(installation_id: str | None = None) -> list[dict]:
    """Return verified bindings independently from APNs opt-in."""
    init_db()
    query = """SELECT b.binding_id,b.installation_id,b.vehicle_id,b.client_kind,b.client_id
               FROM mobile_vehicle_binding b
               JOIN mobile_device m ON m.installation_id=b.installation_id
               WHERE 1=1"""
    args: tuple = ()
    if installation_id is not None:
        query += " AND b.installation_id=?"
        args = (_install_id(installation_id),)
    query += " ORDER BY b.installation_id,b.binding_id"
    with connect() as db:
        return [dict(row) for row in db.execute(query, args)]


def bound_inventory(payload: dict) -> dict:
    """Return the authenticated mobile state without leaking provider identifiers.

    Vehicle deadlines remain opaque Mercure bindings. Referral-wallet state is projected
    through the independently authenticated wallet read model and therefore contains no
    internal account IDs, appointment IDs, or ledger references. Keeping both views on
    the existing authenticated inventory boundary avoids adding another public endpoint.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload invalide")
    installation_id = _install_id(payload.get("installationId"))
    registration_secret = _secret(payload.get("registrationSecret"))
    secret_hash = _hash(registration_secret)
    init_db()
    with connect() as db:
        _authenticated_installation(db, installation_id, secret_hash)
        rows = db.execute(
            """SELECT b.binding_id,d.due_date
               FROM mobile_vehicle_binding b
               LEFT JOIN mobile_deadline d
                 ON d.installation_id=b.installation_id
                AND d.deadline_id=b.binding_id
                AND d.source=?
               WHERE b.installation_id=?
               ORDER BY b.binding_id""",
            (AUTHORITATIVE_DEADLINE_SOURCE, installation_id),
        )
        vehicles = [
            {
                "bindingId": str(row["binding_id"]),
                "dueDate": str(row["due_date"]) if row["due_date"] else None,
            }
            for row in rows
        ]

    # Runtime import avoids a module cycle: referral_wallet_mobile ->
    # referral_wallet_claims -> mobile_devices. At request time this module is fully loaded.
    import referral_wallet_mobile

    wallet_status = referral_wallet_mobile.status(
        {
            "installationId": installation_id,
            "registrationSecret": registration_secret,
        }
    )
    return {
        "ok": True,
        "vehicles": vehicles,
        "source": AUTHORITATIVE_DEADLINE_SOURCE,
        "referralWalletStatus": wallet_status,
    }


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
                f"""DELETE FROM mobile_deadline
                    WHERE installation_id=? AND source=?
                    AND deadline_id NOT IN ({placeholders})""",
                (installation_id, DEVICE_DEADLINE_SOURCE, *(deadline_id for deadline_id, _ in deadlines)),
            )
        else:
            db.execute(
                "DELETE FROM mobile_deadline WHERE installation_id=? AND source=?",
                (installation_id, DEVICE_DEADLINE_SOURCE),
            )
        for deadline_id, due_date in deadlines:
            existing = db.execute(
                "SELECT source FROM mobile_deadline WHERE installation_id=? AND deadline_id=?",
                (installation_id, deadline_id),
            ).fetchone()
            if existing and str(existing["source"]) != DEVICE_DEADLINE_SOURCE:
                raise ValueError("deadlineId réservé à une source autoritaire")
            db.execute(
                """INSERT INTO mobile_deadline(
                     installation_id,deadline_id,due_date,source,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?)
                   ON CONFLICT(installation_id,deadline_id) DO UPDATE SET
                     due_date=excluded.due_date,updated_at=excluded.updated_at
                   WHERE mobile_deadline.source='device'""",
                (installation_id, deadline_id, due_date, DEVICE_DEADLINE_SOURCE, now, now),
            )
    return {
        "ok": True,
        "installationId": installation_id,
        "deadlineCount": len(deadlines),
        "source": DEVICE_DEADLINE_SOURCE,
        "syncedAt": now,
    }


def sync_authoritative_deadlines(installation_id: str, deadlines: list[dict]) -> dict:
    """Replace the authoritative Mercure snapshot for one already registered installation.

    This is an internal server-side primitive. It intentionally accepts no registration
    secret and is not exposed by the public mobile API. A future verified installation
    binding can call it after resolving Mercure vehicle identities.
    """
    installation_id = _install_id(installation_id)
    _assert_processing_allowed(installation_id)
    if not isinstance(deadlines, list) or len(deadlines) > MAX_DEADLINES_PER_INSTALLATION:
        raise ValueError("deadlines invalides")
    parsed: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in deadlines:
        if not isinstance(item, dict):
            raise ValueError("deadline invalide")
        deadline_id = _deadline_id(item.get("deadlineId"))
        if deadline_id in seen:
            raise ValueError("deadlineId dupliqué")
        seen.add(deadline_id)
        parsed.append((deadline_id, _due_date(item.get("dueDate"))))

    init_db()
    now = _now_iso()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        device = db.execute(
            "SELECT installation_id FROM mobile_device WHERE installation_id=?",
            (installation_id,),
        ).fetchone()
        if not device:
            raise LookupError("installation mobile introuvable")

        if parsed:
            placeholders = ",".join("?" for _ in parsed)
            db.execute(
                f"""DELETE FROM mobile_deadline
                    WHERE installation_id=? AND source=?
                    AND deadline_id NOT IN ({placeholders})""",
                (installation_id, AUTHORITATIVE_DEADLINE_SOURCE, *(deadline_id for deadline_id, _ in parsed)),
            )
        else:
            db.execute(
                "DELETE FROM mobile_deadline WHERE installation_id=? AND source=?",
                (installation_id, AUTHORITATIVE_DEADLINE_SOURCE),
            )

        for deadline_id, due_date in parsed:
            db.execute(
                """DELETE FROM mobile_deadline
                   WHERE installation_id=? AND deadline_id=? AND source=?""",
                (installation_id, deadline_id, DEVICE_DEADLINE_SOURCE),
            )
            db.execute(
                """INSERT INTO mobile_deadline(
                     installation_id,deadline_id,due_date,source,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?)
                   ON CONFLICT(installation_id,deadline_id) DO UPDATE SET
                     due_date=excluded.due_date,source=excluded.source,updated_at=excluded.updated_at""",
                (
                    installation_id,
                    deadline_id,
                    due_date,
                    AUTHORITATIVE_DEADLINE_SOURCE,
                    now,
                    now,
                ),
            )
    return {
        "ok": True,
        "installationId": installation_id,
        "deadlineCount": len(parsed),
        "source": AUTHORITATIVE_DEADLINE_SOURCE,
        "syncedAt": now,
    }


def due_targets(start_date: str, end_date: str) -> list[dict]:
    start = _due_date(start_date); end = _due_date(end_date)
    if end < start:
        raise ValueError("plage de dates invalide")
    init_db()
    with connect() as db:
        rows = db.execute(
            """WITH source_choice AS (
                 SELECT installation_id,
                        MAX(CASE WHEN source=? THEN 1 ELSE 0 END) AS has_authoritative
                 FROM mobile_deadline
                 GROUP BY installation_id
               )
               SELECT d.installation_id,d.deadline_id,d.due_date,d.source,
                      m.device_token,m.environment
               FROM mobile_deadline d
               JOIN source_choice c ON c.installation_id=d.installation_id
               JOIN mobile_device m ON m.installation_id=d.installation_id
               WHERE d.due_date>=? AND d.due_date<=?
                 AND m.disabled_at='' AND m.device_token<>''
                 AND (
                   (c.has_authoritative=1 AND d.source=?)
                   OR
                   (c.has_authoritative=0 AND d.source=?)
                 )
               ORDER BY d.due_date,d.installation_id,d.deadline_id""",
            (
                AUTHORITATIVE_DEADLINE_SOURCE,
                start,
                end,
                AUTHORITATIVE_DEADLINE_SOURCE,
                DEVICE_DEADLINE_SOURCE,
            ),
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
        source_rows = db.execute("SELECT source,COUNT(*) n FROM mobile_deadline GROUP BY source")
        deadlines_by_source = {str(row["source"]): int(row["n"]) for row in source_rows}
        disabled_rows = db.execute("SELECT disabled_reason,COUNT(*) n FROM mobile_device WHERE disabled_at<>'' GROUP BY disabled_reason")
        disabled_by_reason = {str(row["disabled_reason"] or "unspecified"): int(row["n"]) for row in disabled_rows}
        bindings = int(db.execute("SELECT COUNT(*) n FROM mobile_vehicle_binding").fetchone()["n"])
        pending_claims = int(db.execute(
            "SELECT COUNT(*) n FROM mobile_vehicle_claim WHERE consumed_at='' AND expires_at>?",
            (_now_iso(),),
        ).fetchone()["n"])
    return {"ok": True, "total": total, "active": active, "byEnvironment": by_environment,
            "disabledByReason": disabled_by_reason,
            "deadlines": deadlines,
            "deadlinesBySource": deadlines_by_source,
            "installationsWithDeadlines": installations_with_deadlines,
            "sourcePolicy": {
                "authoritative": AUTHORITATIVE_DEADLINE_SOURCE,
                "fallback": DEVICE_DEADLINE_SOURCE,
            },
            "vehicleBindings": bindings,
            "pendingClaims": pending_claims,
            "privacy": "Les jetons APNs et les échéances mobiles restent dans le stockage privé du serveur ; seules des échéances opaques sans immatriculation sont conservées."}
