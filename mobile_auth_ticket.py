"""One-time mobile authentication handoff tickets."""
import datetime as dt
import hashlib
import secrets
import sqlite3
from pathlib import Path
import os

TTL_SECONDS=90

def _path():
    return Path(os.environ.get("CYBERCHECK_DATA_DIR","/root/CyberCheckData"))/"mobile-auth-ticket.sqlite3"

def _db():
    p=_path(); p.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(p,timeout=10); db.row_factory=sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS mobile_auth_ticket(
      ticket_hash TEXT PRIMARY KEY, session_token TEXT NOT NULL, expires_at TEXT NOT NULL
    )""")
    return db

def issue(session_token: str) -> str:
    token=secrets.token_urlsafe(32)
    expiry=(dt.datetime.now(dt.timezone.utc)+dt.timedelta(seconds=TTL_SECONDS)).isoformat()
    with _db() as db:
        db.execute("DELETE FROM mobile_auth_ticket WHERE expires_at<?",(dt.datetime.now(dt.timezone.utc).isoformat(),))
        db.execute("INSERT INTO mobile_auth_ticket VALUES(?,?,?)",(hashlib.sha256(token.encode()).hexdigest(),session_token,expiry))
    return token

def consume(ticket: str) -> str:
    raw=str(ticket or "")
    digest=hashlib.sha256(raw.encode()).hexdigest()
    now=dt.datetime.now(dt.timezone.utc)
    with _db() as db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT session_token,expires_at FROM mobile_auth_ticket WHERE ticket_hash=?",(digest,)).fetchone()
        db.execute("DELETE FROM mobile_auth_ticket WHERE ticket_hash=?",(digest,))
    if not row or now>=dt.datetime.fromisoformat(row["expires_at"]):
        raise PermissionError("mobile_auth_ticket_invalid")
    return str(row["session_token"])


def purge_expired(*, dry_run: bool = False) -> int:
    """Remove expired one-time tickets (retention, independent of new issues)."""
    if not _path().is_file():
        return 0
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    from contextlib import closing
    with closing(_db()) as db:
        count=int(db.execute("SELECT COUNT(*) FROM mobile_auth_ticket WHERE expires_at<?",(now,)).fetchone()[0])
        if count and not dry_run:
            db.execute("DELETE FROM mobile_auth_ticket WHERE expires_at<?",(now,))
            db.commit()
    return count
