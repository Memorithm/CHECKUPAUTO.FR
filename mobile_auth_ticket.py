"""One-time mobile authentication handoff tickets.

A ticket references the authenticated account only: no session token is stored
at rest.  The customer session is issued at exchange time.  When the app sent a
PKCE ``code_challenge`` (S256) at the start of the flow, the exchange must
present the matching ``code_verifier``, so an application that intercepts the
custom-scheme redirect cannot redeem the ticket (audit S-05).
"""
import base64
import datetime as dt
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from contextlib import closing
from pathlib import Path

TTL_SECONDS=90
PKCE_REQUIRED_ENV="CYBERCHECK_MOBILE_PKCE_REQUIRED"
_CHALLENGE=re.compile(r"[A-Za-z0-9_-]{43}")
_VERIFIER=re.compile(r"[A-Za-z0-9._~-]{43,128}")

def _path():
    return Path(os.environ.get("CYBERCHECK_DATA_DIR","/root/CyberCheckData"))/"mobile-auth-ticket.sqlite3"

def _db():
    p=_path(); p.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(p,timeout=10); db.row_factory=sqlite3.Row
    columns={row[1] for row in db.execute("PRAGMA table_info(mobile_auth_ticket)")}
    if "session_token" in columns:
        # Legacy rows held raw session tokens; they live 90 s, so drop them.
        db.execute("DROP TABLE mobile_auth_ticket")
        db.commit()
    db.execute("""CREATE TABLE IF NOT EXISTS mobile_auth_ticket(
      ticket_hash TEXT PRIMARY KEY, account_id TEXT NOT NULL,
      code_challenge TEXT NOT NULL DEFAULT '', expires_at TEXT NOT NULL
    )""")
    return db

def pkce_required() -> bool:
    return os.environ.get(PKCE_REQUIRED_ENV,"").strip().lower() in {"1","true","yes","on"}

def valid_challenge(value: object) -> str:
    raw=str(value or "").strip()
    if raw and not _CHALLENGE.fullmatch(raw):
        raise ValueError("mobile_auth_challenge_invalid")
    return raw

def _challenge_for(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")

def issue(account_id: str, *, code_challenge: str="") -> str:
    account=str(account_id or "").strip()
    if not account:
        raise ValueError("mobile_auth_account_required")
    challenge=valid_challenge(code_challenge)
    token=secrets.token_urlsafe(32)
    now=dt.datetime.now(dt.timezone.utc)
    expiry=(now+dt.timedelta(seconds=TTL_SECONDS)).isoformat()
    with closing(_db()) as db, db:
        db.execute("DELETE FROM mobile_auth_ticket WHERE expires_at<?",(now.isoformat(),))
        db.execute(
            "INSERT INTO mobile_auth_ticket(ticket_hash,account_id,code_challenge,expires_at) VALUES(?,?,?,?)",
            (hashlib.sha256(token.encode()).hexdigest(),account,challenge,expiry),
        )
    return token

def consume(ticket: str, code_verifier: str="") -> str:
    """Burn the ticket and return the account id it authorises."""
    raw=str(ticket or "")
    digest=hashlib.sha256(raw.encode()).hexdigest()
    now=dt.datetime.now(dt.timezone.utc)
    with closing(_db()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row=db.execute("SELECT account_id,code_challenge,expires_at FROM mobile_auth_ticket WHERE ticket_hash=?",(digest,)).fetchone()
        db.execute("DELETE FROM mobile_auth_ticket WHERE ticket_hash=?",(digest,))
    if not row or now>=dt.datetime.fromisoformat(row["expires_at"]):
        raise PermissionError("mobile_auth_ticket_invalid")
    challenge=str(row["code_challenge"] or "")
    verifier=str(code_verifier or "")
    if challenge:
        if not _VERIFIER.fullmatch(verifier) or not hmac.compare_digest(_challenge_for(verifier),challenge):
            raise PermissionError("mobile_auth_ticket_invalid")
    elif pkce_required():
        raise PermissionError("mobile_auth_ticket_invalid")
    return str(row["account_id"])


def purge_expired(*, dry_run: bool = False) -> int:
    """Remove expired one-time tickets (retention, independent of new issues)."""
    if not _path().is_file():
        return 0
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    with closing(_db()) as db:
        count=int(db.execute("SELECT COUNT(*) FROM mobile_auth_ticket WHERE expires_at<?",(now,)).fetchone()[0])
        if count and not dry_run:
            db.execute("DELETE FROM mobile_auth_ticket WHERE expires_at<?",(now,))
            db.commit()
    return count
