from __future__ import annotations

import datetime
import os
import sqlite3
from pathlib import Path

DATA_DIR = Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData"))
DB = DATA_DIR / "notification-broker.sqlite3"
TRANSPORT_KEY = "email:gmail-api"


def _empty(verification: str) -> dict:
    return {
        "verification": verification,
        "operationallyVerified": False,
        "lastSuccessAt": "",
        "lastFailureAt": "",
        "circuitOpen": False,
        "consecutiveFailures": 0,
    }


def _parse_timestamp(value: object) -> datetime.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def from_health_row(row: dict | sqlite3.Row | None, *, now: datetime.datetime | None = None) -> dict:
    if row is None:
        return _empty("unverified")

    last_success_raw = str(row["last_success_at"] or "")
    last_failure_raw = str(row["last_failure_at"] or "")
    open_until_raw = str(row["open_until"] or "")
    consecutive_failures = max(0, int(row["consecutive_failures"] or 0))

    last_success = _parse_timestamp(last_success_raw)
    last_failure = _parse_timestamp(last_failure_raw)
    open_until = _parse_timestamp(open_until_raw)
    if (last_success_raw and last_success is None) or (last_failure_raw and last_failure is None) or (open_until_raw and open_until is None):
        return _empty("unavailable")

    current = now or datetime.datetime.now(datetime.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=datetime.timezone.utc)
    current = current.astimezone(datetime.timezone.utc)
    circuit_open = bool(open_until and open_until > current)
    failure_is_newer = bool(last_failure and (not last_success or last_failure > last_success))
    verified = bool(last_success) and not circuit_open and not (
        consecutive_failures and failure_is_newer
    )

    if verified:
        verification = "verified"
    elif circuit_open or failure_is_newer:
        verification = "unavailable"
    else:
        verification = "unverified"

    return {
        "verification": verification,
        "operationallyVerified": verified,
        "lastSuccessAt": last_success_raw,
        "lastFailureAt": last_failure_raw,
        "circuitOpen": circuit_open,
        "consecutiveFailures": consecutive_failures,
    }


def status(db_path: str | Path | None = None) -> dict:
    path = Path(db_path) if db_path is not None else DB
    if not path.exists():
        return _empty("unverified")
    try:
        uri = path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=1) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                """SELECT consecutive_failures, open_until, last_failure_at, last_success_at
                   FROM notification_transport_health
                   WHERE transport_key=?""",
                (TRANSPORT_KEY,),
            ).fetchone()
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "no such table" in message:
            return _empty("unverified")
        return _empty("unavailable")
    except (OSError, sqlite3.Error):
        return _empty("unavailable")
    try:
        return from_health_row(row)
    except (KeyError, TypeError, ValueError, OverflowError):
        return _empty("unavailable")
