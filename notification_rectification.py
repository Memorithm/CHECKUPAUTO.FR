from __future__ import annotations

import datetime
import uuid

import notification_broker as notifications


MOBILE_CT_CATEGORY = "ct_due_reminder"
PERMANENT_RESOLUTION = "superseded_by_rectification"


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
    return parsed.isoformat()


def _reference_prefix(deadline_id: str) -> str:
    return f"mobile-ct:{deadline_id}:"


def _current_reference_prefix(deadline_id: str, due_date: str) -> str:
    return f"mobile-ct:{deadline_id}:{due_date}:"


def reconcile_mobile_deadline(deadline_id: object, due_date: object) -> dict:
    """Resolve obsolete permanent push incidents after a due-date rectification.

    Mobile CT push idempotency references contain the opaque deadline UUID and due
    date. Once the due date changes, an open permanent incident for an older date
    is no longer actionable: retrying it would carry stale information and keeping
    it open would keep NotificationBroker readiness degraded. Sent delivery history
    remains immutable.

    The operation is idempotent and persists no new subject identifier. It only
    transitions already-minimized broker rows from open/acknowledged to resolved.
    If the broker store does not exist yet, there is nothing to reconcile.
    """
    clean_deadline = _deadline_id(deadline_id)
    clean_due = _due_date(due_date)
    if not notifications.DB.exists():
        return {
            "storePresent": False,
            "resolvedPermanentFailures": 0,
            "openStalePermanentFailures": 0,
        }

    notifications.init_db()
    prefix = _reference_prefix(clean_deadline)
    current_prefix = _current_reference_prefix(clean_deadline, clean_due)
    stamp = notifications._now_iso()
    with notifications.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """UPDATE notification_delivery
               SET permanent_state='resolved',
                   permanent_state_at=?,
                   permanent_resolution=?
               WHERE channel='push'
                 AND category=?
                 AND reference LIKE ?
                 AND reference NOT LIKE ?
                 AND failure_class='permanent'
                 AND permanent_state IN ('open','acknowledged')""",
            (
                stamp,
                PERMANENT_RESOLUTION,
                MOBILE_CT_CATEGORY,
                prefix + "%",
                current_prefix + "%",
            ),
        )
        resolved = int(
            db.execute(
                """SELECT COUNT(*) n FROM notification_delivery
                   WHERE channel='push'
                     AND category=?
                     AND reference LIKE ?
                     AND reference NOT LIKE ?
                     AND failure_class='permanent'
                     AND permanent_state='resolved'
                     AND permanent_resolution=?""",
                (
                    MOBILE_CT_CATEGORY,
                    prefix + "%",
                    current_prefix + "%",
                    PERMANENT_RESOLUTION,
                ),
            ).fetchone()["n"]
        )
        remaining = int(
            db.execute(
                """SELECT COUNT(*) n FROM notification_delivery
                   WHERE channel='push'
                     AND category=?
                     AND reference LIKE ?
                     AND reference NOT LIKE ?
                     AND failure_class='permanent'
                     AND permanent_state IN ('open','acknowledged')""",
                (
                    MOBILE_CT_CATEGORY,
                    prefix + "%",
                    current_prefix + "%",
                ),
            ).fetchone()["n"]
        )

    return {
        "storePresent": True,
        "resolvedPermanentFailures": resolved,
        "openStalePermanentFailures": remaining,
    }


def capability() -> dict:
    return {
        "store": "notification_delivery",
        "channel": "push",
        "category": MOBILE_CT_CATEGORY,
        "resolvesStalePermanentFailures": True,
        "sentHistoryMutable": False,
        "rawRecipientRequired": False,
        "rawSubjectPersisted": False,
    }
