from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import uuid
from pathlib import Path

import data_subject_rights as rights
import mobile_devices
import notification_rectification


ADAPTER = "mobile_deadline_rectification"
FIELD = "device_deadline_due_date"


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
    if parsed.year < 2020 or parsed.year > 2100:
        raise ValueError("dueDate invalide")
    return parsed.isoformat()


def _correction(value: object) -> tuple[str, str]:
    if not isinstance(value, dict) or set(value) != {"deadlineId", "dueDate"}:
        raise ValueError("correction invalide")
    return _deadline_id(value["deadlineId"]), _due_date(value["dueDate"])


def _verify_primary_subject(row, installation_id: str) -> None:
    digest = hashlib.sha256(installation_id.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(str(row["subject_ref_hash"]), digest):
        raise PermissionError("référence du demandeur refusée")


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _correction_hash(deadline_id: str, due_date: str) -> str:
    return _sha256(
        json.dumps(
            {"deadlineId": deadline_id, "dueDate": due_date},
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _receipt_hash(
    request_hash: str,
    subject_ref_hash: str,
    correction_hash: str,
    executed_at: str,
) -> str:
    return _sha256(
        json.dumps(
            {
                "requestHash": request_hash,
                "subjectRefHash": subject_ref_hash,
                "correctionHash": correction_hash,
                "executedAt": executed_at,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _assert_recovery_state(
    db,
    installation_id: str,
    deadline_id: str,
    due_date: str,
    executed_at: str,
) -> None:
    """Require the receipt to still describe the current mobile state.

    A receipt proves that the correction transaction committed, but a later device sync
    may legitimately replace or delete that local deadline before the compliance audit
    is retried. The retry therefore accepts the receipt only while the exact device
    deadline generation written by the correction still exists. The correction writes
    a microsecond-precision ``updated_at`` marker, whereas ordinary mobile syncs use the
    public store clock, so even a same-value later sync invalidates the stale receipt.
    """
    device = db.execute(
        "SELECT installation_id FROM mobile_device WHERE installation_id=?",
        (installation_id,),
    ).fetchone()
    deadline = db.execute(
        """SELECT due_date,source,updated_at FROM mobile_deadline
           WHERE installation_id=? AND deadline_id=?""",
        (installation_id, deadline_id),
    ).fetchone()
    if (
        not device
        or not deadline
        or str(deadline["source"]) != mobile_devices.DEVICE_DEADLINE_SOURCE
        or str(deadline["due_date"]) != due_date
        or str(deadline["updated_at"]) != executed_at
    ):
        raise RuntimeError("preuve de rectification obsolète")


def _apply_with_receipt(
    request_id: str,
    installation_id: str,
    deadline_id: str,
    due_date: str,
) -> dict:
    """Apply a device-owned correction and persist its recovery receipt atomically.

    The mobile store keeps only SHA-256 links to the compliance request/subject and to
    the requested correction. If a later cross-store reconciliation or compliance audit
    write fails after this transaction commits, an exact retry can recover from the
    receipt without mutating the deadline again. A retry carrying a different correction,
    or a receipt whose corrected deadline has since changed, fails closed.
    """
    request_hash = _sha256(request_id)
    subject_ref_hash = _sha256(installation_id)
    correction_hash = _correction_hash(deadline_id, due_date)
    mobile_devices.init_db()

    with mobile_devices.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """CREATE TABLE IF NOT EXISTS mobile_rectification_receipt(
                 request_hash TEXT PRIMARY KEY,
                 subject_ref_hash TEXT NOT NULL,
                 correction_hash TEXT NOT NULL,
                 executed_at TEXT NOT NULL
               )"""
        )
        existing = db.execute(
            """SELECT subject_ref_hash,correction_hash,executed_at
               FROM mobile_rectification_receipt WHERE request_hash=?""",
            (request_hash,),
        ).fetchone()
        if existing:
            if not hmac.compare_digest(str(existing["subject_ref_hash"]), subject_ref_hash):
                raise RuntimeError("preuve de rectification contradictoire")
            if not hmac.compare_digest(str(existing["correction_hash"]), correction_hash):
                raise RuntimeError("preuve de rectification contradictoire")
            executed_at = str(existing["executed_at"])
            _assert_recovery_state(
                db,
                installation_id,
                deadline_id,
                due_date,
                executed_at,
            )
            return {
                "correctionHash": correction_hash,
                "receiptHash": _receipt_hash(
                    request_hash,
                    subject_ref_hash,
                    correction_hash,
                    executed_at,
                ),
                "executedAt": executed_at,
                "recovered": True,
            }

        device = db.execute(
            "SELECT installation_id FROM mobile_device WHERE installation_id=?",
            (installation_id,),
        ).fetchone()
        if not device:
            raise LookupError("installation mobile introuvable")
        deadline = db.execute(
            """SELECT source FROM mobile_deadline
               WHERE installation_id=? AND deadline_id=?""",
            (installation_id, deadline_id),
        ).fetchone()
        if not deadline:
            raise LookupError("échéance mobile introuvable")
        if str(deadline["source"]) != mobile_devices.DEVICE_DEADLINE_SOURCE:
            raise PermissionError("échéance autoritaire non rectifiable")

        executed_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds")
        db.execute(
            """UPDATE mobile_deadline SET due_date=?,updated_at=?
               WHERE installation_id=? AND deadline_id=? AND source=?""",
            (
                due_date,
                executed_at,
                installation_id,
                deadline_id,
                mobile_devices.DEVICE_DEADLINE_SOURCE,
            ),
        )
        db.execute(
            """INSERT INTO mobile_rectification_receipt(
                 request_hash,subject_ref_hash,correction_hash,executed_at
               ) VALUES(?,?,?,?)""",
            (request_hash, subject_ref_hash, correction_hash, executed_at),
        )

    return {
        "correctionHash": correction_hash,
        "receiptHash": _receipt_hash(
            request_hash,
            subject_ref_hash,
            correction_hash,
            executed_at,
        ),
        "executedAt": executed_at,
        "recovered": False,
    }


def execute(
    request_id: object,
    subject_ref: object,
    correction: object,
    db_path: Path | str | None = None,
) -> dict:
    """Rectify one user-managed mobile deadline and reconcile dependent push evidence.

    The operation is deliberately narrow: only an existing ``source=device`` due
    date can be changed. Authoritative Mercure deadlines, vehicle bindings and
    device credentials are outside this executor and therefore fail closed.

    Mobile mutation and its minimized recovery receipt are committed atomically.
    NotificationBroker is then reconciled so permanent incidents tied to older due
    dates no longer remain actionable or degrade readiness. Sent notification history
    is not modified. The compliance audit lives in a separate store; if either later
    step fails, an exact retry resumes from the receipt only while the corrected mobile
    state is still current.
    """
    rid = rights._request_id(request_id)
    row = rights._request(rid, db_path)
    if str(row["status"]) not in {"open", "in_progress"}:
        raise RuntimeError("demande non exécutable")
    if str(row["request_type"]) != "rectification":
        raise NotImplementedError("type de droit non pris en charge par cet adaptateur")

    installation_id = rights._mobile_installation(subject_ref)
    _verify_primary_subject(row, installation_id)
    if rights._adapter_executed(rid, ADAPTER, db_path):
        raise RuntimeError("adaptateur déjà exécuté pour cette demande")
    deadline_id, due_date = _correction(correction)

    receipt = _apply_with_receipt(rid, installation_id, deadline_id, due_date)
    broker_reconciliation = notification_rectification.reconcile_mobile_deadline(
        deadline_id,
        due_date,
    )
    if int(broker_reconciliation.get("openStalePermanentFailures") or 0) != 0:
        raise RuntimeError("incidents de notification obsolètes non réconciliés")

    evidence = {
        "requestId": rid,
        "requestType": "rectification",
        "adapter": ADAPTER,
        "field": FIELD,
        "source": mobile_devices.DEVICE_DEADLINE_SOURCE,
        "recordCount": 1,
        "correctionHash": receipt["correctionHash"],
        "receiptHash": receipt["receiptHash"],
        "notificationBroker": {
            "storePresent": bool(broker_reconciliation.get("storePresent")),
            "resolvedPermanentFailures": int(
                broker_reconciliation.get("resolvedPermanentFailures") or 0
            ),
            "openStalePermanentFailures": 0,
        },
    }
    execution_id = rights._audit_execution(row, ADAPTER, "rectify", evidence, db_path)
    return {
        "ok": True,
        "requestId": rid,
        "requestType": "rectification",
        "adapter": ADAPTER,
        "field": FIELD,
        "source": mobile_devices.DEVICE_DEADLINE_SOURCE,
        "updated": True,
        "recoveredFromReceipt": bool(receipt["recovered"]),
        "notificationBrokerReconciled": True,
        "resolvedNotificationIncidents": int(
            broker_reconciliation.get("resolvedPermanentFailures") or 0
        ),
        "executionId": execution_id,
        "requestStatus": "in_progress",
        "requestComplete": False,
    }


def capability() -> dict:
    notification = notification_rectification.capability()
    return {
        "bound": False,
        "partial": True,
        "adapter": ADAPTER,
        "requestType": "rectification",
        "supportedFields": [FIELD],
        "mutableSources": [mobile_devices.DEVICE_DEADLINE_SOURCE],
        "authoritativeSourcesMutable": False,
        "primarySubjectRequired": True,
        "reconciledStores": ["mobile_deadline", notification["store"]],
        "notificationBrokerStaleIncidentResolution": bool(
            notification["resolvesStalePermanentFailures"]
        ),
        "sentNotificationHistoryMutable": bool(notification["sentHistoryMutable"]),
        "rawSubjectReferencePersisted": False,
        "auditStoresEvidenceHashOnly": True,
        "crashRecoverable": True,
        "recoveryRequiresCurrentState": True,
        "receiptStoresRawSubject": False,
    }
