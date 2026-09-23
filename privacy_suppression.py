from __future__ import annotations

import datetime
import hashlib
import hmac
import json
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
    "installation",
    "vehicle",
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
_MARKETING_CHANNEL_FOR_PURPOSE = {
    "direct_marketing_email": "email",
    "direct_marketing_phone": "phone",
    "direct_marketing_sms": "sms",
    "direct_marketing_push": "push",
}
_MARKETING_SUBJECT_KIND_FOR_CHANNEL = {
    "email": "email",
    "phone": "phone",
    "sms": "phone",
    "push": "installation",
}
_KEY_FILE = "privacy-suppression-key"


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _key_path() -> Path:
    return Path(os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate")) / _KEY_FILE


def _key() -> bytes:
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
    elif subject_kind in {"mercure_account", "mercure_free", "vehicle"}:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", raw):
            raise ValueError("identifiant invalide")
    return subject_kind, raw


def identity_hash(kind: object, value: object) -> str:
    subject_kind, normalized = normalize(kind, value)
    payload = f"{subject_kind}\x00{normalized}".encode("utf-8")
    return hmac.new(_key(), payload, hashlib.sha256).hexdigest()


def init_db(db_path: Path | str | None = None) -> None:
    compliance_store.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS privacy_suppression(
              subject_kind TEXT NOT NULL,
              subject_hash TEXT NOT NULL,
              purpose TEXT NOT NULL,
              request_id TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1,
              PRIMARY KEY(subject_kind,subject_hash,purpose)
            );
            CREATE INDEX IF NOT EXISTS idx_privacy_suppression_active
              ON privacy_suppression(active,purpose,subject_kind);
            CREATE TABLE IF NOT EXISTS privacy_store_receipt(
              request_id TEXT NOT NULL,
              store_name TEXT NOT NULL,
              subject_kind TEXT NOT NULL,
              subject_hash TEXT NOT NULL,
              scope TEXT NOT NULL,
              operation TEXT NOT NULL,
              affected_rows INTEGER NOT NULL,
              remaining_active_rows INTEGER NOT NULL,
              evidence_hash TEXT NOT NULL,
              created_at TEXT NOT NULL,
              verified_at TEXT NOT NULL,
              PRIMARY KEY(request_id,store_name,subject_kind,subject_hash,scope)
            );
            CREATE INDEX IF NOT EXISTS idx_privacy_store_receipt_request
              ON privacy_store_receipt(request_id,store_name);
            """
        )


def _table_exists(db, table_name: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    ).fetchone()
    return bool(row)


def _rights_request_type(db, request_id: str) -> str:
    if not request_id or not _table_exists(db, "rights_requests"):
        return ""
    row = db.execute(
        "SELECT request_type FROM rights_requests WHERE request_id=? LIMIT 1",
        (request_id,),
    ).fetchone()
    return str(row["request_type"]) if row else ""


def _marketing_store_receipts(
    db,
    *,
    request_id: str,
    subject_kind: str,
    subject_hash: str,
    purposes: tuple[str, ...],
    stamp: str,
) -> list[dict]:
    """Withdraw consent rows atomically when a DSAR withdrawal is suppressed.

    The privacy gate and the durable marketing-consent state live in the same
    compliance SQLite database. For an actual ``consent_withdrawal`` request we
    therefore mutate both stores in the same transaction and retain a receipt
    containing only the HMAC subject key plus a canonical evidence hash. Other
    right types keep consent proof untouched and rely on suppression alone.
    """
    if _rights_request_type(db, request_id) != "consent_withdrawal":
        return []
    if not _table_exists(db, "marketing_consent"):
        return []

    receipts: list[dict] = []
    for purpose in purposes:
        channel = _MARKETING_CHANNEL_FOR_PURPOSE.get(purpose, "")
        if not channel or _MARKETING_SUBJECT_KIND_FOR_CHANNEL[channel] != subject_kind:
            continue
        cursor = db.execute(
            """UPDATE marketing_consent
               SET state='withdrawn',withdrawn_at=?,withdrawal_source='data-subject-rights'
               WHERE subject_kind=? AND subject_hash=? AND channel=? AND state='active'""",
            (stamp, subject_kind, subject_hash, channel),
        )
        affected = int(cursor.rowcount or 0)
        remaining = int(
            db.execute(
                """SELECT COUNT(*) n FROM marketing_consent
                   WHERE subject_kind=? AND subject_hash=? AND channel=? AND state='active'""",
                (subject_kind, subject_hash, channel),
            ).fetchone()["n"]
        )
        if remaining:
            raise RuntimeError("retrait marketing incomplet")
        evidence = {
            "requestId": request_id,
            "store": "marketing_consent",
            "subjectKind": subject_kind,
            "subjectHash": subject_hash,
            "scope": channel,
            "operation": "withdraw",
            "affectedRows": affected,
            "remainingActiveRows": remaining,
        }
        canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
        evidence_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        db.execute(
            """INSERT INTO privacy_store_receipt(
                 request_id,store_name,subject_kind,subject_hash,scope,operation,
                 affected_rows,remaining_active_rows,evidence_hash,created_at,verified_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(request_id,store_name,subject_kind,subject_hash,scope) DO UPDATE SET
                 remaining_active_rows=excluded.remaining_active_rows,
                 verified_at=excluded.verified_at""",
            (
                request_id,
                "marketing_consent",
                subject_kind,
                subject_hash,
                channel,
                "withdraw",
                affected,
                remaining,
                evidence_hash,
                stamp,
                stamp,
            ),
        )
        stored = db.execute(
            """SELECT affected_rows,remaining_active_rows,evidence_hash,created_at,verified_at
               FROM privacy_store_receipt
               WHERE request_id=? AND store_name='marketing_consent'
                 AND subject_kind=? AND subject_hash=? AND scope=?""",
            (request_id, subject_kind, subject_hash, channel),
        ).fetchone()
        receipts.append(
            {
                "store": "marketing_consent",
                "scope": channel,
                "operation": "withdraw",
                "affectedRows": int(stored["affected_rows"]),
                "remainingActiveRows": int(stored["remaining_active_rows"]),
                "evidenceHash": str(stored["evidence_hash"]),
                "createdAt": str(stored["created_at"]),
                "verifiedAt": str(stored["verified_at"]),
            }
        )
    return receipts


def suppress(
    kind: object,
    value: object,
    purposes: list[str] | tuple[str, ...],
    *,
    request_id: object = "",
    db_path: Path | str | None = None,
) -> dict:
    subject_kind, normalized = normalize(kind, value)
    clean = tuple(dict.fromkeys(str(item or "").strip() for item in purposes))
    if not clean or any(item not in PURPOSES for item in clean):
        raise ValueError("finalité de suppression invalide")
    digest = identity_hash(subject_kind, normalized)
    rid = str(request_id or "").strip().lower()[:64]
    stamp = _now_iso()
    init_db(db_path)
    receipts: list[dict] = []
    with compliance_store.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        for purpose in clean:
            db.execute(
                """INSERT INTO privacy_suppression(
                     subject_kind,subject_hash,purpose,request_id,created_at,updated_at,active
                   ) VALUES(?,?,?,?,?,?,1)
                   ON CONFLICT(subject_kind,subject_hash,purpose) DO UPDATE SET
                     request_id=CASE WHEN excluded.request_id<>'' THEN excluded.request_id
                                     ELSE privacy_suppression.request_id END,
                     updated_at=excluded.updated_at,active=1""",
                (subject_kind, digest, purpose, rid, stamp, stamp),
            )
        receipts = _marketing_store_receipts(
            db,
            request_id=rid,
            subject_kind=subject_kind,
            subject_hash=digest,
            purposes=clean,
            stamp=stamp,
        )
    return {
        "ok": True,
        "subjectKind": subject_kind,
        "purposes": list(clean),
        "storeReceiptCount": len(receipts),
        "storeReceipts": receipts,
    }


def unsuppress(
    kind: object,
    value: object,
    purposes: list[str] | tuple[str, ...],
    *,
    db_path: Path | str | None = None,
) -> dict:
    subject_kind, normalized = normalize(kind, value)
    clean = tuple(dict.fromkeys(str(item or "").strip() for item in purposes))
    if not clean or "all_processing" in clean or any(item not in PURPOSES for item in clean):
        raise ValueError("finalité de réactivation invalide")
    digest = identity_hash(subject_kind, normalized)
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        placeholders = ",".join("?" for _ in clean)
        cursor = db.execute(
            f"""UPDATE privacy_suppression
                SET active=0,updated_at=?
                WHERE subject_kind=? AND subject_hash=? AND active=1
                  AND purpose IN ({placeholders})""",
            (_now_iso(), subject_kind, digest, *clean),
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
                """SELECT 1 FROM privacy_suppression
                   WHERE subject_kind=? AND subject_hash=? AND active=1
                     AND purpose='all_processing' LIMIT 1""",
                (subject_kind, digest),
            ).fetchone()
        else:
            row = db.execute(
                """SELECT 1 FROM privacy_suppression
                   WHERE subject_kind=? AND subject_hash=? AND active=1
                     AND purpose IN (?, 'all_processing') LIMIT 1""",
                (subject_kind, digest, requested),
            ).fetchone()
    return bool(row)


def any_suppressed(
    candidates: list[tuple[str, object]],
    purpose: str,
    *,
    db_path: Path | str | None = None,
) -> bool:
    return any(
        value not in (None, "") and is_suppressed(kind, value, purpose, db_path=db_path)
        for kind, value in candidates
    )


def store_receipts(
    request_id: object,
    db_path: Path | str | None = None,
) -> list[dict]:
    rid = str(request_id or "").strip().lower()[:64]
    if not rid:
        raise ValueError("requestId requis")
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        rows = db.execute(
            """SELECT store_name,scope,operation,affected_rows,remaining_active_rows,
                      evidence_hash,created_at,verified_at
               FROM privacy_store_receipt WHERE request_id=?
               ORDER BY store_name,scope,created_at""",
            (rid,),
        ).fetchall()
    return [
        {
            "store": str(row["store_name"]),
            "scope": str(row["scope"]),
            "operation": str(row["operation"]),
            "affectedRows": int(row["affected_rows"]),
            "remainingActiveRows": int(row["remaining_active_rows"]),
            "evidenceHash": str(row["evidence_hash"]),
            "createdAt": str(row["created_at"]),
            "verifiedAt": str(row["verified_at"]),
        }
        for row in rows
    ]


def summary(db_path: Path | str | None = None) -> dict:
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        total = int(db.execute(
            "SELECT COUNT(*) n FROM privacy_suppression WHERE active=1"
        ).fetchone()["n"])
        rows = db.execute(
            """SELECT purpose,COUNT(*) n FROM privacy_suppression
               WHERE active=1 GROUP BY purpose ORDER BY purpose"""
        ).fetchall()
        receipt_total = int(
            db.execute("SELECT COUNT(*) n FROM privacy_store_receipt").fetchone()["n"]
        )
    return {
        "active": total,
        "byPurpose": {str(row["purpose"]): int(row["n"]) for row in rows},
        "identityProtection": "HMAC-SHA256",
        "privateKeyFile": _KEY_FILE,
        "storeReceiptCount": receipt_total,
        "storeEvidenceStores": ["marketing_consent"],
    }
