from __future__ import annotations

import datetime
import hashlib
import json
import re
import uuid
from pathlib import Path

import compliance_store
import marketing_delivery


MAX_AUDIENCE = 250
_CAMPAIGN_CHANNELS = {"email", "push"}
_RUN_STATES = {"running", "completed", "partial", "blocked", "failed", "pending"}


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _text(value: object, name: str, limit: int, *, required: bool = False) -> str:
    clean = str(value or "").strip()
    if required and not clean:
        raise ValueError(f"{name} requis")
    if len(clean) > limit:
        raise ValueError(f"{name} trop long")
    return clean


def _reference(value: object) -> str:
    return _text(value, "reference", 120, required=True)


def _channel(value: object) -> str:
    clean = str(value or "").strip().lower()
    if clean not in _CAMPAIGN_CHANNELS:
        raise ValueError("canal de campagne non pris en charge")
    return clean


def _audience(channel: str, values: object) -> list[str]:
    if not isinstance(values, (list, tuple)):
        raise ValueError("audience invalide")
    if not values or len(values) > MAX_AUDIENCE:
        raise ValueError("taille d'audience invalide")
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value or "").strip()
        if not clean or len(clean) > 320:
            raise ValueError("destinataire invalide")
        if channel == "email":
            if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", clean):
                raise ValueError("destinataire email invalide")
            normalized = clean.lower()
        else:
            normalized = clean.lower()
            try:
                parsed = uuid.UUID(normalized)
            except (ValueError, AttributeError) as exc:
                raise ValueError("installationId invalide") from exc
            if str(parsed) != normalized:
                raise ValueError("installationId invalide")
        if normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    if not output:
        raise ValueError("audience vide")
    return output


def _canonical_hash(payload: dict) -> str:
    try:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("contenu de campagne invalide") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def init_db(db_path: Path | str | None = None) -> None:
    compliance_store.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS marketing_campaign_run(
              run_id TEXT PRIMARY KEY,
              channel TEXT NOT NULL,
              reference_hash TEXT NOT NULL,
              content_hash TEXT NOT NULL,
              audience_count INTEGER NOT NULL,
              attempted_count INTEGER NOT NULL DEFAULT 0,
              delivered_count INTEGER NOT NULL DEFAULT 0,
              blocked_count INTEGER NOT NULL DEFAULT 0,
              failed_count INTEGER NOT NULL DEFAULT 0,
              pending_count INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL,
              started_at TEXT NOT NULL,
              completed_at TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_marketing_campaign_started
              ON marketing_campaign_run(started_at,status);
            """
        )


def _start_run(
    channel: str,
    reference: str,
    content_hash: str,
    audience_count: int,
    db_path: Path | str | None,
) -> tuple[str, str]:
    init_db(db_path)
    run_id = uuid.uuid4().hex
    started = _now_iso()
    with compliance_store.connect(db_path) as db:
        db.execute(
            """INSERT INTO marketing_campaign_run(
                 run_id,channel,reference_hash,content_hash,audience_count,status,started_at
               ) VALUES(?,?,?,?,?,'running',?)""",
            (
                run_id,
                channel,
                hashlib.sha256(reference.encode("utf-8")).hexdigest(),
                content_hash,
                int(audience_count),
                started,
            ),
        )
    return run_id, started


def _run_state(
    audience_count: int,
    delivered: int,
    blocked: int,
    failed: int,
    pending: int,
) -> str:
    if pending:
        return "pending" if delivered == 0 and failed == 0 else "partial"
    if delivered == audience_count:
        return "completed"
    if blocked == audience_count:
        return "blocked"
    if delivered:
        return "partial"
    if failed:
        return "failed"
    return "blocked"


def _finish_run(
    run_id: str,
    *,
    audience_count: int,
    attempted: int,
    delivered: int,
    blocked: int,
    failed: int,
    pending: int,
    db_path: Path | str | None,
) -> dict:
    status = _run_state(audience_count, delivered, blocked, failed, pending)
    if status not in _RUN_STATES:  # pragma: no cover - internal invariant
        raise RuntimeError("état de campagne invalide")
    completed = _now_iso()
    with compliance_store.connect(db_path) as db:
        db.execute(
            """UPDATE marketing_campaign_run
               SET attempted_count=?,delivered_count=?,blocked_count=?,failed_count=?,
                   pending_count=?,status=?,completed_at=?
               WHERE run_id=?""",
            (attempted, delivered, blocked, failed, pending, status, completed, run_id),
        )
        row = db.execute(
            "SELECT * FROM marketing_campaign_run WHERE run_id=?",
            (run_id,),
        ).fetchone()
    return _public_run(row)


def _public_run(row) -> dict:
    return {
        "runId": str(row["run_id"]),
        "channel": str(row["channel"]),
        "referenceHash": str(row["reference_hash"]),
        "contentHash": str(row["content_hash"]),
        "audienceCount": int(row["audience_count"]),
        "attemptedCount": int(row["attempted_count"]),
        "deliveredCount": int(row["delivered_count"]),
        "blockedCount": int(row["blocked_count"]),
        "failedCount": int(row["failed_count"]),
        "pendingCount": int(row["pending_count"]),
        "status": str(row["status"]),
        "startedAt": str(row["started_at"]),
        "completedAt": str(row["completed_at"]),
    }


def _delivery_state(result: dict) -> str:
    delivery = result.get("delivery") if isinstance(result, dict) else None
    if not isinstance(delivery, dict):
        return "failed"
    if delivery.get("alreadySent") is True or str(delivery.get("status") or "") == "sent":
        return "delivered"
    if delivery.get("inFlight") is True or delivery.get("deferred") is True:
        return "pending"
    return "failed"


def run_email_campaign(
    recipients: object,
    subject: object,
    text: object,
    html: object = "",
    *,
    reference: object,
    db_path: Path | str | None = None,
) -> dict:
    channel = _channel("email")
    audience = _audience(channel, recipients)
    ref = _reference(reference)
    clean_subject = _text(subject, "subject", 240, required=True)
    clean_text = _text(text, "text", 20000, required=True)
    clean_html = _text(html, "html", 60000)
    content_hash = _canonical_hash(
        {"channel": channel, "subject": clean_subject, "text": clean_text, "html": clean_html}
    )
    run_id, _ = _start_run(channel, ref, content_hash, len(audience), db_path)
    attempted = delivered = blocked = failed = pending = 0
    for recipient in audience:
        attempted += 1
        try:
            result = marketing_delivery.send_email(
                recipient,
                clean_subject,
                clean_text,
                clean_html,
                reference=ref,
                consent_db_path=db_path,
            )
        except PermissionError:
            blocked += 1
            continue
        except Exception:
            failed += 1
            continue
        state = _delivery_state(result)
        if state == "delivered":
            delivered += 1
        elif state == "pending":
            pending += 1
        else:
            failed += 1
    return _finish_run(
        run_id,
        audience_count=len(audience),
        attempted=attempted,
        delivered=delivered,
        blocked=blocked,
        failed=failed,
        pending=pending,
        db_path=db_path,
    )


def run_push_campaign(
    installation_ids: object,
    title: object,
    body: object,
    *,
    reference: object,
    data: dict | None = None,
    db_path: Path | str | None = None,
) -> dict:
    channel = _channel("push")
    audience = _audience(channel, installation_ids)
    ref = _reference(reference)
    clean_title = _text(title, "title", 240, required=True)
    clean_body = _text(body, "body", 4000, required=True)
    if data is not None and not isinstance(data, dict):
        raise ValueError("data push invalide")
    push_data = dict(data or {})
    content_hash = _canonical_hash(
        {"channel": channel, "title": clean_title, "body": clean_body, "data": push_data}
    )
    run_id, _ = _start_run(channel, ref, content_hash, len(audience), db_path)
    attempted = delivered = blocked = failed = pending = 0
    for installation_id in audience:
        attempted += 1
        try:
            result = marketing_delivery.send_push(
                installation_id,
                clean_title,
                clean_body,
                reference=ref,
                data=push_data,
                consent_db_path=db_path,
            )
        except PermissionError:
            blocked += 1
            continue
        except Exception:
            failed += 1
            continue
        state = _delivery_state(result)
        if state == "delivered":
            delivered += 1
        elif state == "pending":
            pending += 1
        else:
            failed += 1
    return _finish_run(
        run_id,
        audience_count=len(audience),
        attempted=attempted,
        delivered=delivered,
        blocked=blocked,
        failed=failed,
        pending=pending,
        db_path=db_path,
    )


def recent_runs(db_path: Path | str | None = None, limit: int = 50) -> list[dict]:
    init_db(db_path)
    bounded = max(1, min(int(limit), 200))
    with compliance_store.connect(db_path) as db:
        rows = db.execute(
            "SELECT * FROM marketing_campaign_run ORDER BY started_at DESC,run_id DESC LIMIT ?",
            (bounded,),
        ).fetchall()
    return [_public_run(row) for row in rows]


def capability(db_path: Path | str | None = None) -> dict:
    runs = recent_runs(db_path, 200)
    return {
        "bound": True,
        "channels": ["email", "push"],
        "smsConfigured": False,
        "phoneConfigured": False,
        "audienceLimit": MAX_AUDIENCE,
        "deliveryFacade": "marketing_delivery",
        "consentGateRequiredPerRecipient": True,
        "rawRecipientsPersisted": False,
        "rawContentPersisted": False,
        "runCount": len(runs),
        "latestRun": runs[0] if runs else None,
    }
