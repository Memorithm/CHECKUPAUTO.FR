"""The customer's next validated appointment, read from the Mercure planning.

Mercure is the source of truth: a booking made from this site or directly on
rdv.checkupauto.fr shows up as long as it carries the account's e-mail. Only a
*verified* account e-mail is matched, otherwise anyone could register with
someone else's address and read their appointment.

"Validated" means present in the planning and not waiting for an online
payment: Mercure creates the booking before payment with a Payline token and
no billing line, then adds the billing line once paid (live tests 2026-10-14
and 15). The Payline token, the customer's name and phone never leave here.

One planning snapshot is shared by every customer for a short time, so page
views do not multiply the reads on Mercure.
"""
from __future__ import annotations

import datetime
import threading
import time

import mercure_admin_client as mercure
import mercure_public_client as public

WINDOW_DAYS = 120
SNAPSHOT_TTL_SECONDS = 90
# After a failed read, waiters are not queued behind new slow calls: for this
# long they get the last good snapshot (if recent) or an immediate failure.
FAILURE_BACKOFF_SECONDS = 30
STALE_SNAPSHOT_SECONDS = 600
WAIT_FOR_READ_SECONDS = 30
_LOCK = threading.Lock()
_SNAPSHOT: dict = {"at": 0.0, "day": "", "events": None, "failedAt": None, "inflight": None}


def _labels() -> dict:
    return {str(item["id"]): item["label"] for item in public.SERVICES.values()}


def _ids(value) -> list[str]:
    values = value if isinstance(value, (list, tuple)) else [value]
    return [str(v).strip() for v in values if v is not None and str(v).strip()]


def _start(value) -> datetime.datetime | None:
    raw = str(value or "").strip().replace(" ", "T", 1)
    try:
        parsed = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=mercure.MERCURE_TIMEZONE)
    return parsed


def _planning(now: float, fetch=None, *, wait: bool = True) -> list:
    """One Mercure read at a time, shared by every caller (single flight).

    The lock is only held to look at or update the snapshot, never during the
    Mercure call, so a slow or failing Mercure cannot pile up page requests.
    """
    today = mercure.business_today(datetime.datetime.fromtimestamp(now, datetime.timezone.utc)).isoformat()
    with _LOCK:
        events, same_day = _SNAPSHOT["events"], _SNAPSHOT["day"] == today
        age = now - _SNAPSHOT["at"]
        if events is not None and same_day and age < SNAPSHOT_TTL_SECONDS:
            return events
        stale = events if events is not None and same_day and age < STALE_SNAPSHOT_SECONDS else None
        failed_at = _SNAPSHOT["failedAt"]
        if failed_at is not None and 0 <= now - failed_at < FAILURE_BACKOFF_SECONDS:
            if stale is not None:
                return stale
            raise RuntimeError("Mercure planning recently unavailable")
        inflight = _SNAPSHOT["inflight"]
        if inflight is None:
            inflight = _SNAPSHOT["inflight"] = threading.Event()
            reader = True
        else:
            reader = False
    if not reader:
        if stale is not None:
            return stale
        if not wait or not inflight.wait(WAIT_FOR_READ_SECONDS):
            raise RuntimeError("Mercure planning read still running")
        return _planning(now, fetch, wait=False)
    end = (datetime.date.fromisoformat(today) + datetime.timedelta(days=WINDOW_DAYS)).isoformat()
    try:
        if fetch is None:
            events = mercure._calendar_events(mercure._session(), today, end)
        else:
            events = fetch(today, end)
    except Exception:
        with _LOCK:
            _SNAPSHOT.update(failedAt=now, inflight=None)
        inflight.set()
        if stale is not None:
            return stale
        raise
    with _LOCK:
        _SNAPSHOT.update(at=now, day=today, events=events, failedAt=None, inflight=None)
    inflight.set()
    return events


def _view(event: dict, labels: dict) -> dict:
    ext = event.get("extendedProps") or {}
    start = _start(event.get("start"))
    end = _start(event.get("end"))
    paid = bool(ext.get("rendezVousFacturation"))
    service_ids = _ids(ext.get("prestationId"))
    return {
        "appointmentId": mercure._event_id(event),
        "start": start.isoformat(timespec="minutes") if start else "",
        "end": end.isoformat(timespec="minutes") if end else "",
        "service": next((labels[i] for i in service_ids if i in labels), "Prestation au centre"),
        "vehicle": str(ext.get("vehiculeNom") or "").strip()[:80],
        "paidOnline": paid,
        "amount": round(mercure._price(ext.get("tarifTotal")), 2) if paid else None,
    }


def upcoming(account: dict, *, now: float | None = None, fetch=None) -> dict:
    """Return the next validated appointment of this account, and how many follow."""
    if not isinstance(account, dict) or account.get("emailVerified") is not True:
        return {"ok": True, "available": False, "reason": "email_not_verified"}
    email = str(account.get("email") or "").strip().lower()
    if "@" not in email:
        return {"ok": True, "available": False, "reason": "email_not_verified"}
    instant = time.time() if now is None else now
    try:
        events = _planning(instant, fetch)
    except Exception:
        return {"ok": True, "available": False, "reason": "provider_unavailable"}
    current = datetime.datetime.fromtimestamp(instant, mercure.MERCURE_TIMEZONE)
    labels = _labels()
    mine = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        ext = event.get("extendedProps") or {}
        if ext.get("rdvDispo") is True or ext.get("blocageId"):
            continue
        if str(ext.get("email") or "").strip().lower() != email:
            continue
        start = _start(event.get("start"))
        if start is None or start < current:
            continue
        # Created by the online checkout but not paid yet: not validated.
        if str(ext.get("tokenPayline") or "").strip() and not ext.get("rendezVousFacturation"):
            continue
        mine.append((start, _view(event, labels)))
    mine.sort(key=lambda item: item[0])
    return {"ok": True, "available": True,
            "next": mine[0][1] if mine else None,
            "others": [view for _, view in mine[1:4]]}
