"""Administrative announcements shown in authenticated customer dashboards.

These are public editorial messages, not customer notifications or referral rewards.
They live in the runtime data directory, never in the Git repository.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3

DEFAULT_ANNOUNCEMENT = (
    "Nous mettons prochainement en place un système de fidélité et de parrainage "
    "avantageux pour vous récompenser. Restez à l’écoute et renseignez vos "
    "coordonnées dans votre espace client !"
)
IPHONE_ANNOUNCEMENT = (
    "Bientôt, l’application CHECKUPAUTO pour iPhone ! "
    "Programmez des rappels GRATUITS pour votre véhicule "
    "et n’oubliez plus jamais votre contrôle technique."
)
_IPHONE_SEED_ID = "2026-10-16-iphone-free-technical-reminders"
MAX_LENGTH = 400
MAX_ITEMS = 20


def data_path() -> Path:
    return Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData")) / "customer-announcements.sqlite3"


def _connect() -> sqlite3.Connection:
    path = data_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def _initialize(db: sqlite3.Connection) -> None:
    # The seed is inserted only when the table is first created. Deleting it
    # through the admin UI must never recreate it on a subsequent request.
    db.execute("BEGIN IMMEDIATE")
    present = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='customer_announcements'"
    ).fetchone()
    if not present:
        db.execute("""
            CREATE TABLE customer_announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        db.execute(
            "INSERT INTO customer_announcements (message,enabled,created_at,updated_at) "
            "VALUES (?,1,?,?)", (DEFAULT_ANNOUNCEMENT, now, now)
        )

    # An explicitly requested editorial campaign, once per database. The
    # migration ledger is distinct from admin-managed rows so an editor may
    # later hide, amend or delete the message without automatic re-creation.
    db.execute("""
        CREATE TABLE IF NOT EXISTS customer_announcement_seed_history (
            slug TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)
    applied = db.execute(
        "SELECT 1 FROM customer_announcement_seed_history WHERE slug=?",
        (_IPHONE_SEED_ID,)
    ).fetchone()
    if not applied:
        # Existing/disabled editor-created copies take precedence. On a full
        # editorial catalog, do not disrupt customer account availability.
        already = db.execute(
            "SELECT 1 FROM customer_announcements WHERE message=? LIMIT 1",
            (IPHONE_ANNOUNCEMENT,)
        ).fetchone()
        count = db.execute("SELECT COUNT(*) FROM customer_announcements").fetchone()[0]
        if already or count < MAX_ITEMS:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if not already:
                db.execute(
                    "INSERT INTO customer_announcements "
                    "(message,enabled,created_at,updated_at) VALUES (?,1,?,?)",
                    (IPHONE_ANNOUNCEMENT, now, now)
                )
            db.execute(
                "INSERT INTO customer_announcement_seed_history (slug,applied_at) "
                "VALUES (?,?)", (_IPHONE_SEED_ID, now)
            )


def _open_initialized():
    db = _connect()
    try:
        with db:
            _initialize(db)
        return db
    except Exception:
        db.close()
        raise


def _row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "message": row["message"],
        "enabled": bool(row["enabled"]),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def list_all() -> list[dict]:
    with closing(_open_initialized()) as db:
        rows = db.execute(
            "SELECT id,message,enabled,created_at,updated_at "
            "FROM customer_announcements ORDER BY id ASC"
        ).fetchall()
        return [_row(row) for row in rows]


def list_public() -> list[dict]:
    with closing(_open_initialized()) as db:
        rows = db.execute(
            "SELECT id,message FROM customer_announcements "
            "WHERE enabled=1 ORDER BY id ASC"
        ).fetchall()
        return [{"id": row["id"], "message": row["message"]} for row in rows]


def _valid_id(raw: object) -> int:
    if type(raw) is not int or raw < 1:
        raise ValueError("announcement_invalid_id")
    return raw


def _message(raw: object) -> str:
    if not isinstance(raw, str):
        raise ValueError("announcement_invalid_message")
    message = " ".join(raw.split())
    if not message or len(message) > MAX_LENGTH or any(ord(char) < 32 for char in message):
        raise ValueError("announcement_invalid_message")
    return message


def change(payload: object) -> list[dict]:
    if not isinstance(payload, dict):
        raise ValueError("announcement_invalid_request")
    action = payload.get("action")
    if action == "create":
        if set(payload) != {"action", "message", "enabled"} or type(payload["enabled"]) is not bool:
            raise ValueError("announcement_invalid_request")
        message = _message(payload["message"])
        with closing(_open_initialized()) as db, db:
            if db.execute("SELECT COUNT(*) FROM customer_announcements").fetchone()[0] >= MAX_ITEMS:
                raise ValueError("announcement_limit_reached")
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            db.execute(
                "INSERT INTO customer_announcements (message,enabled,created_at,updated_at) "
                "VALUES (?,?,?,?)", (message, int(payload["enabled"]), now, now)
            )
    elif action == "update":
        if set(payload) != {"action", "id", "message", "enabled"} or type(payload["enabled"]) is not bool:
            raise ValueError("announcement_invalid_request")
        identifier = _valid_id(payload["id"])
        message = _message(payload["message"])
        with closing(_open_initialized()) as db, db:
            result = db.execute(
                "UPDATE customer_announcements SET message=?,enabled=?,updated_at=? WHERE id=?",
                (message, int(payload["enabled"]),
                 datetime.now(timezone.utc).isoformat(timespec="seconds"), identifier)
            )
            if not result.rowcount:
                raise LookupError("announcement_not_found")
    elif action == "delete":
        if set(payload) != {"action", "id"}:
            raise ValueError("announcement_invalid_request")
        identifier = _valid_id(payload["id"])
        with closing(_open_initialized()) as db, db:
            result = db.execute("DELETE FROM customer_announcements WHERE id=?", (identifier,))
            if not result.rowcount:
                raise LookupError("announcement_not_found")
    else:
        raise ValueError("announcement_invalid_action")
    return list_all()
