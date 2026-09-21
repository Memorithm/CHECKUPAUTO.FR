from __future__ import annotations

import datetime
import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path

import compliance_store


SUBJECT_KINDS = {
    "email",
    "phone",
    "mercure_account",
    "mercure_free",
    "vehicle",
    "installation",
    "contract",
}
PURPOSES = {
    "ct_reminder",
    "google_review",
    "direct_marketing_email",
    "direct_marketing_phone",
    "direct_marketing_sms",
    "direct_marketing_push",
    "all_processing",
}
DIRECT_MARKETING_PURPOSES = (
    "direct_marketing_email",
    "direct_marketing_phone",
    "direct_marketing_sms",
    "direct_marketing_push",
)
_KEY_NAME = "privacy-suppression-key"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _private_dir() -> Path:
    return Path(os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate"))


def _key_path() -> Path:
    return _private_dir() / _KEY_NAME


def ensure_key() -> bytes:
    path = _key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except PermissionError:
        pass
    if not path.exists():
        tmp = path.with_suffix(".tmp")
        tmp.write_text(secrets.token_urlsafe(48) + "\n", encoding="utf-8")
        tmp.chmod(0o600)
        os.replace(tmp, path)
    try:
        path.chmod(0o600)
    except PermissionError:
        pass
    raw = path.read_text(encoding="utf-8").strip()
    if len(raw) < 32:
        raise RuntimeError("privacy suppression key invalid")
    return raw.encode("utf-8")


def normalize(kind: object, value: object) -> tuple[str, str]:
    subject_kind = str(kind or "").strip().lower()
    if subject_kind not in SUBJECT_KINDS:
        raise ValueError("subjectKind invalide")
    raw = str(value or "").strip()
    if not raw or len(raw) > 512 or "\x00" in raw:
        raise ValueError("subjectRef invalide")
    if subject_kind == "email":
        raw = raw.lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", raw):
            raise ValueError("adresse e-mail invalide")
    elif subject_kind == "phone":
        raw = re.sub(r"[^+0-9]", "", raw)
        if not re.fullmatch(r"\+?[0-9]{6,20}", raw):
            raise ValueError("telephone invalide")
    elif subject_kind == "installation":
        raw = raw.lower()
        if not re.fullmatch(r"[0-9a-f-]{36}", raw):
            raise ValueError("installation invalide")
    elif subject_kind in {"mercure_account", "mercure_free", "vehicle", "contract"}:
        if not re.fullmatch(r"[A-Za-z0-9_.:@/+\-]{1,200}", raw):
            raise ValueError("identifiant sujet invalide")
    return subject_kind, raw


def identity_hash(kind: object, value: object) -> str:
    subject_kind, normalized = normalize(kind, value)
    material = f"{subject_kind}\x00{normalized}".encode("utf-8")
    return hmac.new(ensure_key(), material, hashlib.sha256).hexdigest()


def init_db(db_path: Path | str | None = None) -> None:
    compliance_store.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS privacy_suppressions(
              subject_kind TEXT NOT NULL,
              subject_hash TEXT NOT NULL,
              purpose TEXT NOT NULL,
              source_request_id TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1,
              PRIMARY KEY(subject_kind,subject_hash,purpose)
            );
            CREATE INDEX IF NOT EXISTS idx_privacy_suppression_active
              ON privacy_suppressions(active,purpose,subject_kind);
            """
        )


def suppress(
    kind: object,
    value: object,
    purposes: list[str] | tuple[str, ...],
    *,
    source_request_id: object = "",
    db_path: Path | str | None = None,
) -> dict:
    subject_kind, normalized = normalize(kind, value)
    clean_purposes = tuple(dict.fromkeys(str(item or "").strip() for item in purposes))
    if not clean_purposes or any(item not in PURPOSES for item in clean_purposes):
        raise ValueError("finalité de suppression invalide")
    digest = identity_hash(subject_kind, normalized)
    source = str(source_request_id or "").strip()[:64]
    stamp = _now_iso()
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        for purpose in clean_purposes:
            db.execute(
                """INSERT INTO privacy_suppressions(
                     subject_kind,subject_hash,purpose,source_request_id,created_at,updated_at,active
                   ) VALUES(?,?,?,?,?,?,1)
                   ON CONFLICT(subject_kind,subject_hash,purpose) DO UPDATE SET
                     source_request_id=CASE WHEN excluded.source_request_id<>'' THEN excluded.source_request_id
                                            ELSE privacy_suppressions.source_request_id END,
                     updated_at=excluded.updated_at,active=1""",
                (subject_kind, digest, purpose, source, stamp, stamp),
            )
    return {
        "ok": True,
        "subjectKind": subject_kind,
        "purposes": list(clean_purposes),
        "sourceRequestId": source,
    }


def unsuppress(
    kind: object,
    value: object,
    purposes: list[str] | tuple[str, ...],
    *,
    db_path: Path | str | None = None,
) -> dict:
    subject_kind, normalized = normalize(kind, value)
    clean_purposes = tuple(dict.fromkeys(str(item or "").strip() for item in purposes))
    if not clean_purposes or any(item not in PURPOSES for item in clean_purposes):
        raise ValueError("finalité de suppression invalide")
    digest = identity_hash(subject_kind, normalized)
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        placeholders = ",".join("?" for _ in clean_purposes)
        cursor = db.execute(
            f"""UPDATE privacy_suppressions SET active=0,updated_at=?
                WHERE subject_kind=? AND subject_hash=? AND purpose IN ({placeholders})""",
            (_now_iso(), subject_kind, digest, *clean_purposes),
        )
    return {"ok": True, "deactivated": int(cursor.rowcount or 0)}


def is_suppressed(
    kind: object,
    value: object,
    purpose: object,
    *,
    db_path: Path | str | None = None,
) -> bool:
    requested = str(purpose or "").strip()
    if requested not in PURPOSES:
        raise ValueError("finalité invalide")
    subject_kind, normalized = normalize(kind, value)
    digest = identity_hash(subject_kind, normalized)
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        if requested == "all_processing":
            row = db.execute(
                """SELECT 1 FROM privacy_suppressions
                   WHERE subject_kind=? AND subject_hash=? AND active=1
                     AND purpose='all_processing' LIMIT 1""",
                (subject_kind, digest),
            ).fetchone()
        else:
            row = db.execute(
                """SELECT 1 FROM privacy_suppressions
                   WHERE subject_kind=? AND subject_hash=? AND active=1
                     AND purpose IN (?, 'all_processing')
                   LIMIT 1""",
                (subject_kind, digest, requested),
            ).fetchone()
    return bool(row)


def any_suppressed(
    candidates: list[tuple[str, object]],
    purpose: str,
    *,
    db_path: Path | str | None = None,
) -> bool:
    for kind, value in candidates:
        if value not in (None, "") and is_suppressed(kind, value, purpose, db_path=db_path):
            return True
    return False


def summary(db_path: Path | str | None = None) -> dict:
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        total = int(
            db.execute("SELECT COUNT(*) n FROM privacy_suppressions WHERE active=1").fetchone()["n"]
        )
        by_purpose = {
            str(row["purpose"]): int(row["n"])
            for row in db.execute(
                """SELECT purpose,COUNT(*) n FROM privacy_suppressions
                   WHERE active=1 GROUP BY purpose ORDER BY purpose"""
            )
        }
    return {
        "active": total,
        "byPurpose": by_purpose,
        "identityProtection": "HMAC-SHA256",
        "privateKeyFile": _KEY_NAME,
    }
