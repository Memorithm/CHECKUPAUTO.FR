from __future__ import annotations

import calendar
import datetime
import hashlib
import json
import re
import uuid
from pathlib import Path

import compliance_store
import privacy_suppression


CHANNELS = {"email", "sms", "phone", "push"}
SUBJECT_KIND_FOR_CHANNEL = {
    "email": "email",
    "sms": "phone",
    "phone": "phone",
    "push": "installation",
}
PURPOSE_FOR_CHANNEL = {
    "email": "direct_marketing_email",
    "sms": "direct_marketing_sms",
    "phone": "direct_marketing_phone",
    "push": "direct_marketing_push",
}
CONSENT_STATES = {"active", "withdrawn", "expired", "superseded"}
PHONE_MAX_YEARS = 1
PHONE_PROOF_YEARS = 3


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _calendar_years_later(value: datetime.datetime, years: int) -> datetime.datetime:
    year = value.year + int(years)
    day = min(value.day, calendar.monthrange(year, value.month)[1])
    return value.replace(year=year, day=day)


def _text(value: object, name: str, limit: int, *, required: bool = False) -> str:
    clean = str(value or "").strip()
    if required and not clean:
        raise ValueError(f"{name} requis")
    if len(clean) > limit:
        raise ValueError(f"{name} trop long")
    return clean


def _channel(value: object) -> str:
    channel = str(value or "").strip().lower()
    if channel not in CHANNELS:
        raise ValueError("canal marketing invalide")
    return channel


def _parse_datetime(value: object, name: str, *, required: bool = False) -> datetime.datetime | None:
    raw = _text(value, name, 64, required=required)
    if not raw:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} invalide") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc)


def init_db(db_path: Path | str | None = None) -> None:
    compliance_store.init_db(db_path)
    privacy_suppression.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS marketing_consent(
              consent_id TEXT PRIMARY KEY,
              subject_kind TEXT NOT NULL,
              subject_hash TEXT NOT NULL,
              channel TEXT NOT NULL,
              state TEXT NOT NULL,
              controller_name TEXT NOT NULL,
              third_party_name TEXT NOT NULL DEFAULT '',
              goods_services_scope TEXT NOT NULL,
              statement_version TEXT NOT NULL,
              statement_text TEXT NOT NULL,
              statement_hash TEXT NOT NULL,
              positive_action INTEGER NOT NULL,
              source TEXT NOT NULL,
              evidence_ref_hash TEXT NOT NULL,
              consented_at TEXT NOT NULL,
              valid_until TEXT NOT NULL DEFAULT '',
              proof_retain_until TEXT NOT NULL DEFAULT '',
              withdrawal_method TEXT NOT NULL,
              withdrawn_at TEXT NOT NULL DEFAULT '',
              withdrawal_source TEXT NOT NULL DEFAULT '',
              superseded_at TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_marketing_consent_subject
              ON marketing_consent(subject_kind,subject_hash,channel,state,consented_at);
            CREATE INDEX IF NOT EXISTS idx_marketing_consent_retention
              ON marketing_consent(channel,proof_retain_until,state);
            """
        )


def _public_row(row) -> dict:
    return {
        "id": str(row["consent_id"]),
        "subjectKind": str(row["subject_kind"]),
        "subjectHash": str(row["subject_hash"])[:16],
        "channel": str(row["channel"]),
        "state": str(row["state"]),
        "controllerName": str(row["controller_name"]),
        "thirdPartyName": str(row["third_party_name"]),
        "goodsServicesScope": str(row["goods_services_scope"]),
        "statementVersion": str(row["statement_version"]),
        "statementText": str(row["statement_text"]),
        "statementHash": str(row["statement_hash"]),
        "positiveAction": bool(row["positive_action"]),
        "source": str(row["source"]),
        "evidenceRefHash": str(row["evidence_ref_hash"]),
        "consentedAt": str(row["consented_at"]),
        "validUntil": str(row["valid_until"]),
        "proofRetainUntil": str(row["proof_retain_until"]),
        "withdrawalMethod": str(row["withdrawal_method"]),
        "withdrawnAt": str(row["withdrawn_at"]),
        "withdrawalSource": str(row["withdrawal_source"]),
        "supersededAt": str(row["superseded_at"]),
    }


def record_consent(payload: dict, db_path: Path | str | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("preuve de consentement invalide")
    channel = _channel(payload.get("channel"))
    kind = SUBJECT_KIND_FOR_CHANNEL[channel]
    _, normalized = privacy_suppression.normalize(kind, payload.get("subjectRef"))
    subject_hash = privacy_suppression.identity_hash(kind, normalized)
    controller = _text(payload.get("controllerName"), "controllerName", 240, required=True)
    third_party = _text(payload.get("thirdPartyName"), "thirdPartyName", 240)
    scope = _text(payload.get("goodsServicesScope"), "goodsServicesScope", 1000, required=True)
    version = _text(payload.get("statementVersion"), "statementVersion", 64, required=True)
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._-]{0,63}", version):
        raise ValueError("version de formulation invalide")
    statement = _text(payload.get("statementText"), "statementText", 5000, required=True)
    if len(statement) < 40:
        raise ValueError("formulation de consentement trop courte")
    source = _text(payload.get("source"), "source", 120, required=True)
    withdrawal_method = _text(
        payload.get("withdrawalMethod"), "withdrawalMethod", 1000, required=True
    )
    evidence_ref = _text(payload.get("evidenceRef"), "evidenceRef", 500, required=True)
    if payload.get("positiveAction") is not True:
        raise ValueError("le consentement exige un acte positif explicite")

    consented = _parse_datetime(payload.get("consentedAt"), "consentedAt") or _now()
    if consented > _now() + datetime.timedelta(minutes=5):
        raise ValueError("consentedAt ne peut pas être dans le futur")
    valid_until = _parse_datetime(payload.get("validUntil"), "validUntil")
    proof_retain_until = None

    if channel == "phone":
        if valid_until is None:
            raise ValueError("la période de consentement téléphonique est requise")
        maximum = _calendar_years_later(consented, PHONE_MAX_YEARS)
        if valid_until <= consented or valid_until > maximum:
            raise ValueError("la période téléphonique doit être positive et ne pas dépasser un an")
        proof_retain_until = _calendar_years_later(consented, PHONE_PROOF_YEARS)
    elif valid_until is not None and valid_until <= consented:
        raise ValueError("validUntil doit être postérieur au consentement")

    statement_hash = hashlib.sha256(statement.encode("utf-8")).hexdigest()
    evidence_hash = hashlib.sha256(evidence_ref.encode("utf-8")).hexdigest()
    stamp = _now_iso()
    consent_id = uuid.uuid4().hex
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """UPDATE marketing_consent
               SET state='superseded',superseded_at=?
               WHERE subject_kind=? AND subject_hash=? AND channel=? AND state='active'""",
            (stamp, kind, subject_hash, channel),
        )
        db.execute(
            """INSERT INTO marketing_consent(
                 consent_id,subject_kind,subject_hash,channel,state,controller_name,
                 third_party_name,goods_services_scope,statement_version,statement_text,
                 statement_hash,positive_action,source,evidence_ref_hash,consented_at,
                 valid_until,proof_retain_until,withdrawal_method,created_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                consent_id,
                kind,
                subject_hash,
                channel,
                "active",
                controller,
                third_party,
                scope,
                version,
                statement,
                statement_hash,
                1,
                source,
                evidence_hash,
                consented.isoformat(timespec="seconds"),
                valid_until.isoformat(timespec="seconds") if valid_until else "",
                proof_retain_until.isoformat(timespec="seconds") if proof_retain_until else "",
                withdrawal_method,
                stamp,
            ),
        )

    # A fresh, explicit consent may only lift the purpose-specific suppression.
    # An all-processing suppression (restriction/erasure) always remains authoritative.
    privacy_suppression.unsuppress(
        kind,
        normalized,
        [PURPOSE_FOR_CHANNEL[channel]],
        db_path=db_path,
    )
    with compliance_store.connect(db_path) as db:
        row = db.execute(
            "SELECT * FROM marketing_consent WHERE consent_id=?",
            (consent_id,),
        ).fetchone()
    return _public_row(row)


def expire_due(db_path: Path | str | None = None) -> int:
    init_db(db_path)
    now = _now_iso()
    with compliance_store.connect(db_path) as db:
        cursor = db.execute(
            """UPDATE marketing_consent
               SET state='expired'
               WHERE state='active' AND valid_until<>'' AND valid_until<?""",
            (now,),
        )
    return int(cursor.rowcount or 0)


def _active_row(
    channel: str,
    kind: str,
    subject_hash: str,
    db_path: Path | str | None = None,
):
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        return db.execute(
            """SELECT * FROM marketing_consent
               WHERE subject_kind=? AND subject_hash=? AND channel=? AND state='active'
               ORDER BY consented_at DESC LIMIT 1""",
            (kind, subject_hash, channel),
        ).fetchone()


def authorize(
    channel: object,
    subject_ref: object,
    *,
    at: datetime.datetime | None = None,
    db_path: Path | str | None = None,
) -> dict:
    clean_channel = _channel(channel)
    kind = SUBJECT_KIND_FOR_CHANNEL[clean_channel]
    _, normalized = privacy_suppression.normalize(kind, subject_ref)
    purpose = PURPOSE_FOR_CHANNEL[clean_channel]
    if privacy_suppression.is_suppressed(kind, normalized, purpose, db_path=db_path):
        return {
            "authorized": False,
            "channel": clean_channel,
            "reason": "privacy_suppressed",
        }
    digest = privacy_suppression.identity_hash(kind, normalized)
    row = _active_row(clean_channel, kind, digest, db_path)
    if row is None:
        return {
            "authorized": False,
            "channel": clean_channel,
            "reason": "explicit_consent_missing",
        }
    current = at or _now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=datetime.timezone.utc)
    current = current.astimezone(datetime.timezone.utc)
    valid_until = _parse_datetime(row["valid_until"], "validUntil")
    if valid_until is not None and current > valid_until:
        with compliance_store.connect(db_path) as db:
            db.execute(
                """UPDATE marketing_consent SET state='expired'
                   WHERE consent_id=? AND state='active'""",
                (row["consent_id"],),
            )
        return {
            "authorized": False,
            "channel": clean_channel,
            "reason": "consent_expired",
        }
    return {
        "authorized": True,
        "channel": clean_channel,
        "reason": "explicit_consent",
        "consentId": str(row["consent_id"]),
        "statementVersion": str(row["statement_version"]),
        "statementHash": str(row["statement_hash"]),
        "validUntil": str(row["valid_until"]),
    }


def withdraw(
    channel: object,
    subject_ref: object,
    *,
    source: object = "admin",
    db_path: Path | str | None = None,
) -> dict:
    clean_channel = _channel(channel)
    kind = SUBJECT_KIND_FOR_CHANNEL[clean_channel]
    _, normalized = privacy_suppression.normalize(kind, subject_ref)
    digest = privacy_suppression.identity_hash(kind, normalized)
    stamp = _now_iso()
    source_text = _text(source, "source", 120, required=True)
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        cursor = db.execute(
            """UPDATE marketing_consent
               SET state='withdrawn',withdrawn_at=?,withdrawal_source=?
               WHERE subject_kind=? AND subject_hash=? AND channel=? AND state='active'""",
            (stamp, source_text, kind, digest, clean_channel),
        )
    privacy_suppression.suppress(
        kind,
        normalized,
        [PURPOSE_FOR_CHANNEL[clean_channel]],
        request_id="marketing-withdrawal",
        db_path=db_path,
    )
    return {
        "ok": True,
        "channel": clean_channel,
        "withdrawnAt": stamp,
        "activeConsentRowsWithdrawn": int(cursor.rowcount or 0),
        "source": source_text,
    }


def require_authorized(
    channel: object,
    subject_ref: object,
    *,
    at: datetime.datetime | None = None,
    db_path: Path | str | None = None,
) -> dict:
    result = authorize(channel, subject_ref, at=at, db_path=db_path)
    if not result.get("authorized"):
        raise PermissionError(str(result.get("reason") or "marketing_consent_required"))
    return result


def proof(
    channel: object,
    subject_ref: object,
    *,
    db_path: Path | str | None = None,
) -> dict:
    clean_channel = _channel(channel)
    kind = SUBJECT_KIND_FOR_CHANNEL[clean_channel]
    _, normalized = privacy_suppression.normalize(kind, subject_ref)
    digest = privacy_suppression.identity_hash(kind, normalized)
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        rows = db.execute(
            """SELECT * FROM marketing_consent
               WHERE subject_kind=? AND subject_hash=? AND channel=?
               ORDER BY consented_at DESC LIMIT 50""",
            (kind, digest, clean_channel),
        ).fetchall()
    return {
        "channel": clean_channel,
        "subjectKind": kind,
        "generatedAt": _now_iso(),
        "records": [_public_row(row) for row in rows],
    }


def recent(db_path: Path | str | None = None, limit: int = 100) -> list[dict]:
    init_db(db_path)
    expire_due(db_path)
    with compliance_store.connect(db_path) as db:
        rows = db.execute(
            """SELECT * FROM marketing_consent
               ORDER BY consented_at DESC LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [_public_row(row) for row in rows]


def capability(db_path: Path | str | None = None) -> dict:
    rows = recent(db_path, 500)
    active = sum(1 for row in rows if row["state"] == "active")
    phone = [row for row in rows if row["channel"] == "phone"]
    return {
        "bound": True,
        "defaultB2CMarketing": "denied",
        "explicitPositiveActionRequired": True,
        "termsAcceptanceIsNotConsent": True,
        "withdrawalEnforcedBySuppressionRegistry": True,
        "telephoneMaxConsentYears": PHONE_MAX_YEARS,
        "telephoneProofRetentionYears": PHONE_PROOF_YEARS,
        "activeConsentCount": active,
        "phoneConsentCount": len(phone),
        "customerSimilarProductExceptionImplemented": False,
        "channels": sorted(CHANNELS),
    }
