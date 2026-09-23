from __future__ import annotations

import datetime
import hashlib
import re

import notification_broker


_MARKETING_CATEGORY = {
    "email": "marketing_email",
    "push": "marketing_push",
}
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _subject_hash(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not _HASH_RE.fullmatch(clean):
        raise ValueError("subject_hash invalide")
    return clean


def _channel(value: object) -> str:
    clean = str(value or "").strip().lower()
    if clean not in _MARKETING_CATEGORY:
        raise ValueError("canal notification marketing invalide")
    return clean


def _recipient_hash(value: object) -> str:
    clean = str(value or "").strip().lower()
    if not clean or len(clean) > 512:
        raise ValueError("destinataire notification invalide")
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def init_db() -> None:
    """Initialize pseudonymous subject-to-delivery bindings in broker storage."""
    notification_broker.init_db()
    with notification_broker.connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS notification_privacy_binding(
              subject_hash TEXT NOT NULL,
              channel TEXT NOT NULL,
              recipient_hash TEXT NOT NULL,
              created_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              PRIMARY KEY(subject_hash,channel,recipient_hash)
            );
            CREATE INDEX IF NOT EXISTS idx_notification_privacy_subject
              ON notification_privacy_binding(subject_hash,channel);
            """
        )


def bind_marketing_recipient(
    subject_hash: object,
    channel: object,
    recipient_key: object,
) -> dict:
    """Bind one privacy identity to a broker recipient without raw identifiers.

    ``recipient_key`` is used only transiently to derive the same SHA-256 key as
    NotificationBroker. Neither an e-mail address, an installation id nor an
    APNs token is persisted by this bridge.
    """
    subject = _subject_hash(subject_hash)
    clean_channel = _channel(channel)
    recipient = _recipient_hash(recipient_key)
    stamp = _now_iso()
    init_db()
    with notification_broker.connect() as db:
        db.execute(
            """INSERT INTO notification_privacy_binding(
                 subject_hash,channel,recipient_hash,created_at,last_seen_at
               ) VALUES(?,?,?,?,?)
               ON CONFLICT(subject_hash,channel,recipient_hash) DO UPDATE SET
                 last_seen_at=excluded.last_seen_at""",
            (subject, clean_channel, recipient, stamp, stamp),
        )
    return {"ok": True, "channel": clean_channel, "identityProtection": "HMAC-SHA256+SHA-256"}


def _active_delivery_lease(row, now: datetime.datetime) -> bool:
    # NotificationBroker owns the lease semantics. Reuse its bounded predicate so
    # privacy mutation never claims to cancel a transport call already in flight.
    return bool(notification_broker._lease_active(row, now))


def suppress_retryable_marketing(
    subject_hash: object,
    channel: object,
    *,
    fallback_recipient_key: object = "",
) -> dict:
    """Terminalize marketing deliveries that could otherwise be retried.

    Already-sent rows are retained as delivery evidence. A currently active
    transport lease is also retained because it was initiated before this
    operation and cannot truthfully be represented as cancelled. Failed,
    deferred and stale-delivering rows become a resolved terminal privacy state;
    NotificationBroker's existing permanent-delivery guard then rejects a retry.
    """
    subject = _subject_hash(subject_hash)
    clean_channel = _channel(channel)
    category = _MARKETING_CATEGORY[clean_channel]
    fallback = str(fallback_recipient_key or "").strip()
    now = _now()
    stamp = now.isoformat(timespec="seconds")
    init_db()

    with notification_broker.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        bound = {
            str(row["recipient_hash"])
            for row in db.execute(
                """SELECT recipient_hash FROM notification_privacy_binding
                   WHERE subject_hash=? AND channel=?""",
                (subject, clean_channel),
            ).fetchall()
        }
        persisted_binding_count = len(bound)
        if fallback:
            bound.add(_recipient_hash(fallback))

        if not bound:
            return {
                "ok": True,
                "store": "notification_broker",
                "scope": clean_channel,
                "operation": "suppress_retryable_marketing",
                "matchedRows": 0,
                "affectedRows": 0,
                "remainingActiveRows": 0,
                "inFlightRows": 0,
                "retainedSentRows": 0,
                "bindingCount": 0,
            }

        placeholders = ",".join("?" for _ in bound)
        params = (clean_channel, category, *sorted(bound))
        rows = db.execute(
            f"""SELECT * FROM notification_delivery
                WHERE channel=? AND category=? AND recipient_hash IN ({placeholders})""",
            params,
        ).fetchall()

        affected = 0
        in_flight = 0
        retained_sent = 0
        for row in rows:
            status = str(row["status"] or "")
            if status == "sent":
                retained_sent += 1
                continue
            if status == "delivering" and _active_delivery_lease(row, now):
                in_flight += 1
                continue
            if (
                str(row["failure_class"] or "") == "permanent"
                and str(row["permanent_state"] or "") == "resolved"
                and str(row["permanent_resolution"] or "") == "privacy_suppressed"
            ):
                continue
            cursor = db.execute(
                """UPDATE notification_delivery
                   SET status='failed',failure_class='permanent',next_attempt_at='',
                       last_error='PrivacySuppressed',permanent_state='resolved',
                       permanent_state_at=?,permanent_resolution='privacy_suppressed',
                       recipient_check_state='',recipient_checked_at='',
                       recipient_change_detected_at=''
                   WHERE idempotency_key=?""",
                (stamp, str(row["idempotency_key"])),
            )
            affected += int(cursor.rowcount or 0)

        verify_rows = db.execute(
            f"""SELECT * FROM notification_delivery
                WHERE channel=? AND category=? AND recipient_hash IN ({placeholders})""",
            params,
        ).fetchall()
        remaining_retryable = 0
        for row in verify_rows:
            status = str(row["status"] or "")
            if status == "sent":
                continue
            if status == "delivering" and _active_delivery_lease(row, now):
                continue
            terminal = (
                str(row["failure_class"] or "") == "permanent"
                and str(row["permanent_state"] or "") == "resolved"
                and str(row["permanent_resolution"] or "") == "privacy_suppressed"
            )
            if not terminal:
                remaining_retryable += 1
        if remaining_retryable:
            raise RuntimeError("suppression des retries marketing NotificationBroker incomplète")

    return {
        "ok": True,
        "store": "notification_broker",
        "scope": clean_channel,
        "operation": "suppress_retryable_marketing",
        "matchedRows": len(rows),
        "affectedRows": affected,
        "remainingActiveRows": remaining_retryable,
        "inFlightRows": in_flight,
        "retainedSentRows": retained_sent,
        "bindingCount": persisted_binding_count,
    }
