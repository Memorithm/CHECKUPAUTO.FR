"""Refund of a booking paid online through Mercure's Payline, from the admin.

Mercure is the only party holding the payment: the refund goes through its admin
route ``/admin/rendez_vous_remboursement`` (``token`` = the booking's Payline
token, ``montant`` in euros). Live test of 2026-10-14: the refund empties
``tokenPayline``, ``tarifTotal`` and the billing lines but keeps the booking,
which is then cancelled with ``/admin/rendez_vous_remove``.

Safety rules, all enforced on the server:
- off unless ``CHECKUPAUTO_MERCURE_REFUND_ENABLED=true``;
- two steps: a read-only lookup issues a signed confirmation bound to the
  booking, the amount, the admin's session and a 5-minute expiry; the refund
  needs that confirmation, the booking number and amount typed again, and a
  fresh Google Authenticator code (no recovery code);
- the planning is re-read just before the refund: the booking must still be
  paid online and the amount must not exceed what Mercure recorded;
- one refund per booking, ever: a journal entry is written and fsynced *before*
  Mercure is called, so a timeout leaves the booking blocked as "uncertain"
  until it is checked, never refunded twice;
- a daily ceiling on the total refunded;
- the Payline token never leaves the server and is never journalled.
"""
from __future__ import annotations

import base64
import contextlib
import datetime
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time

import mercure_admin_client as mercure

ENABLE_ENV = "CHECKUPAUTO_MERCURE_REFUND_ENABLED"
DAILY_CAP_ENV = "CHECKUPAUTO_MERCURE_REFUND_DAILY_CAP_EUR"
DEFAULT_DAILY_CAP_CENTS = 30000
CONFIRMATION_TTL_SECONDS = 300
# A "pending" entry older than this was left by an interrupted worker (the
# Mercure call times out after 40 s) and is settled like an uncertain one.
STALE_PENDING_SECONDS = 120
_ID_RE = re.compile(r"^[0-9]{1,12}$")
_AMOUNT_RE = re.compile(r"^[0-9]{1,5}([.,][0-9]{1,2})?$")
FINAL_STATES = {"pending", "uncertain", "refunded"}


class RefundError(Exception):
    """Stable error code, safe to show; never carries customer or token data."""

    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def enabled(environ=None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get(ENABLE_ENV) or "").strip().lower() == "true"


def daily_cap_cents(environ=None) -> int:
    env = os.environ if environ is None else environ
    raw = str(env.get(DAILY_CAP_ENV) or "").strip()
    if not raw:
        return DEFAULT_DAILY_CAP_CENTS
    try:
        value = int(round(float(raw.replace(",", ".")) * 100))
    except ValueError:
        return DEFAULT_DAILY_CAP_CENTS
    return value if 0 < value <= 500000 else DEFAULT_DAILY_CAP_CENTS


def _root() -> Path:
    private = Path(os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate"))
    root = private / "mercure-refunds"
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    return root


@contextlib.contextmanager
def _lock():
    fd = os.open(_root() / ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _atomic_json(path: Path, value) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".refund-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        # The rename itself must survive a crash before Mercure is called.
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def _read_json(path: Path, default):
    if path.is_symlink():
        raise RefundError("refund_storage_invalid", 500)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        raise RefundError("refund_storage_invalid", 500) from None


def _journal_path() -> Path:
    return _root() / "journal.json"


def _audit(event: dict) -> None:
    line = json.dumps({"at": int(time.time()), **event}, ensure_ascii=False, sort_keys=True)
    fd = os.open(_root() / "audit.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, (line + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def _key() -> bytes:
    path = _root() / "confirmation.key"
    with _lock():
        if not path.exists():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                os.write(fd, secrets.token_bytes(32))
                os.fsync(fd)
            finally:
                os.close(fd)
    if path.is_symlink():
        raise RefundError("refund_storage_invalid", 500)
    data = path.read_bytes()
    if len(data) != 32:
        raise RefundError("refund_storage_invalid", 500)
    return data


def binding(headers) -> str:
    """Tie a confirmation to this admin's HTTP Basic login and MFA cookie."""
    raw = (headers.get("Authorization", "") + "\x00" + headers.get("Cookie", "")).encode()
    return hashlib.sha256(raw).hexdigest()


def csrf_token(headers, *, hour: int | None = None) -> str:
    period = int(time.time() // 3600) if hour is None else hour
    return hmac.new(_key(), f"mercure-refund-csrf:{period}:{binding(headers)}".encode(),
                    hashlib.sha256).hexdigest()


def verify_csrf(value, headers) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    hour = int(time.time() // 3600)
    return any(hmac.compare_digest(value, csrf_token(headers, hour=h)) for h in (hour, hour - 1))


def appointment_id(value) -> str:
    text = str(value or "").strip()
    if not _ID_RE.fullmatch(text):
        raise RefundError("refund_appointment_invalid")
    return text


def appointment_date(value) -> str:
    try:
        return datetime.date.fromisoformat(str(value or "").strip()).isoformat()
    except ValueError:
        raise RefundError("refund_date_invalid") from None


def amount_cents(value) -> int:
    text = str(value if value is not None else "").strip().replace("€", "").strip()
    if not _AMOUNT_RE.fullmatch(text):
        raise RefundError("refund_amount_invalid")
    cents = int(round(float(text.replace(",", ".")) * 100))
    if cents <= 0:
        raise RefundError("refund_amount_invalid")
    return cents


def _euros(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def _mask_email(value) -> str:
    text = str(value or "").strip()
    if "@" not in text:
        return ""
    local, domain = text.split("@", 1)
    return (local[:1] or "?") + "•••@" + domain


def _mask_name(value) -> str:
    parts = [p for p in str(value or "").split() if p]
    return " ".join(p[:1].upper() + "." for p in parts[:3])


def _find(session, rid: str, day: str) -> dict:
    end = (datetime.date.fromisoformat(day) + datetime.timedelta(days=1)).isoformat()
    events = mercure._calendar_events(session, day, end)
    found = [e for e in events if isinstance(e, dict)
             and not (e.get("extendedProps") or {}).get("rdvDispo")
             and mercure._event_id(e) == rid]
    if not found:
        raise RefundError("refund_appointment_not_found", 404)
    if len(found) != 1:
        raise RefundError("refund_appointment_ambiguous", 409)
    return found[0]


def _facts(event: dict) -> dict:
    """Public summary plus the private token, kept apart by the callers."""
    ext = event.get("extendedProps") or {}
    billing = ext.get("rendezVousFacturation") or []
    paid = bool(billing)
    token = str(ext.get("tokenPayline") or "").strip()
    total = int(round(mercure._price(ext.get("tarifTotal")) * 100))
    modes = sorted({str(line.get("optModeReglement") or "").strip()
                    for line in billing if isinstance(line, dict)} - {""})
    summary = {
        "appointmentId": mercure._event_id(event),
        "start": str(event.get("start") or "").replace(" ", "T", 1)[:16],
        "service": str(ext.get("prestationId") if not isinstance(ext.get("prestationId"), list)
                       else ",".join(str(x) for x in ext.get("prestationId"))),
        "customer": _mask_name(ext.get("nom")),
        "email": _mask_email(ext.get("email")),
        "paidOnline": paid,
        "paymentModes": modes,
        "paidCents": total if paid else 0,
        "refundable": bool(paid and token and total > 0),
    }
    return {"summary": summary, "token": token}


def _journal_entry(rid: str):
    return _read_json(_journal_path(), {}).get(rid)


def _refunded_today_cents(journal: dict, now: float) -> int:
    today = datetime.datetime.fromtimestamp(now, mercure.MERCURE_TIMEZONE).date().isoformat()
    return sum(int(e.get("amountCents") or 0) for e in journal.values()
               if e.get("state") in FINAL_STATES and e.get("day") == today)


def _sign(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode().rstrip("=")
    mac = hmac.new(_key(), ("mercure-refund-confirm:" + body).encode(), hashlib.sha256).hexdigest()
    return body + "." + mac


def _unsign(token) -> dict:
    if not isinstance(token, str) or token.count(".") != 1 or len(token) > 2048:
        raise RefundError("refund_confirmation_invalid", 403)
    body, mac = token.split(".")
    expected = hmac.new(_key(), ("mercure-refund-confirm:" + body).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        raise RefundError("refund_confirmation_invalid", 403)
    try:
        return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except ValueError:
        raise RefundError("refund_confirmation_invalid", 403) from None


def lookup(payload: dict, *, headers, environ=None, session_factory=None, now=None) -> dict:
    """Read-only: describe the booking and, if refundable, issue a confirmation."""
    if not enabled(environ):
        raise RefundError("refund_disabled", 403)
    if not isinstance(payload, dict) or not set(payload) <= {"appointmentId", "date", "amount", "cancelAfter"}:
        raise RefundError("refund_body_invalid")
    rid = appointment_id(payload.get("appointmentId"))
    day = appointment_date(payload.get("date"))
    session = (session_factory or mercure._session)()
    facts = _facts(_find(session, rid, day))
    summary = facts["summary"]
    entry = _journal_entry(rid)
    if entry:
        summary["previousRefund"] = {k: entry.get(k) for k in ("state", "amountCents", "at", "cancelled")}
    result = {"ok": True, "appointment": summary, "confirmation": None}
    if not summary["refundable"] or (entry and entry.get("state") in FINAL_STATES):
        return result
    cents = summary["paidCents"] if payload.get("amount") in (None, "") else amount_cents(payload.get("amount"))
    if cents > summary["paidCents"]:
        raise RefundError("refund_amount_exceeds_paid")
    instant = int(time.time() if now is None else now)
    claims = {"id": rid, "day": day, "cents": cents, "cancel": payload.get("cancelAfter") is not False,
              "bind": binding(headers), "exp": instant + CONFIRMATION_TTL_SECONDS,
              "nonce": secrets.token_hex(16)}
    result["confirmation"] = _sign(claims)
    result["amountCents"] = cents
    result["cancelAfter"] = claims["cancel"]
    result["expiresInSeconds"] = CONFIRMATION_TTL_SECONDS
    return result


def _refund_call(session, token: str, cents: int) -> str:
    """Return 'refunded', or 'refused' only on Mercure's explicit JSON answer.

    Anything else (HTTP error, unreadable body) may hide a processed refund
    and raises, so the caller records the outcome as uncertain."""
    montant = str(cents // 100) if cents % 100 == 0 else _euros(cents)
    response = mercure._check_auth(session.post(
        mercure.BASE + "/admin/rendez_vous_remboursement",
        data={"token": token, "montant": montant}, timeout=40, allow_redirects=False))
    if response.status_code not in (200, 201):
        raise RuntimeError("refund_http_status")
    try:
        data = response.json()
    except ValueError:
        raise RuntimeError("refund_response_unreadable") from None
    if not isinstance(data, dict):
        raise RuntimeError("refund_response_unreadable")
    if str(data.get("result") or "").upper() == "OK":
        return "refunded"
    if data.get("Msg") or data.get("result"):
        return "refused"
    raise RuntimeError("refund_response_unreadable")


def _cancel_call(session, rid: str, day: str) -> bool:
    response = mercure._check_auth(session.post(
        mercure.BASE + "/admin/rendez_vous_remove", data={"rendezvous_id": rid},
        timeout=25, allow_redirects=False))
    if response.status_code not in (200, 201):
        return False
    try:
        _find(session, rid, day)
    except RefundError as exc:
        return exc.code == "refund_appointment_not_found"
    return False


def execute(payload: dict, *, headers, verify_code, environ=None, session_factory=None, now=None) -> dict:
    """Refund once, after every check; ``verify_code`` consumes a fresh TOTP."""
    if not enabled(environ):
        raise RefundError("refund_disabled", 403)
    if not isinstance(payload, dict) or set(payload) != {"confirmation", "appointmentId", "amount", "code"}:
        raise RefundError("refund_body_invalid")
    claims = _unsign(payload.get("confirmation"))
    instant = time.time() if now is None else now
    if int(claims.get("exp") or 0) < instant:
        raise RefundError("refund_confirmation_expired", 403)
    if not hmac.compare_digest(str(claims.get("bind") or ""), binding(headers)):
        raise RefundError("refund_confirmation_invalid", 403)
    rid = appointment_id(payload.get("appointmentId"))
    if rid != claims.get("id") or amount_cents(payload.get("amount")) != claims.get("cents"):
        raise RefundError("refund_retype_mismatch")
    if not verify_code(str(payload.get("code") or "")):
        raise RefundError("refund_second_factor_invalid", 403)
    cents = int(claims["cents"])
    day = str(claims["day"])
    today = datetime.datetime.fromtimestamp(instant, mercure.MERCURE_TIMEZONE).date().isoformat()
    session = (session_factory or mercure._session)()
    with _lock():
        journal = _read_json(_journal_path(), {})
        nonces = _read_json(_root() / "used-confirmations.json", {})
        if claims.get("nonce") in nonces:
            raise RefundError("refund_confirmation_used", 409)
        nonces = {n: t for n, t in nonces.items() if t > instant - 86400}
        nonces[claims["nonce"]] = int(instant)
        _atomic_json(_root() / "used-confirmations.json", nonces)
        if journal.get(rid, {}).get("state") in FINAL_STATES:
            raise RefundError("refund_already_recorded", 409)
        if _refunded_today_cents(journal, instant) + cents > daily_cap_cents(environ):
            raise RefundError("refund_daily_cap_reached", 409)
        facts = _facts(_find(session, rid, day))
        if not facts["summary"]["refundable"]:
            raise RefundError("refund_not_refundable", 409)
        if cents > facts["summary"]["paidCents"]:
            raise RefundError("refund_amount_exceeds_paid", 409)
        journal[rid] = {"state": "pending", "amountCents": cents, "day": today, "bookingDay": day,
                        "at": int(instant), "cancelled": False}
        _atomic_json(_journal_path(), journal)
        _audit({"event": "refund_requested", "appointmentId": rid, "amountCents": cents})
        try:
            outcome = _refund_call(session, facts["token"], cents)
        except Exception:
            journal[rid]["state"] = "uncertain"
            _atomic_json(_journal_path(), journal)
            _audit({"event": "refund_uncertain", "appointmentId": rid, "amountCents": cents})
            raise RefundError("refund_outcome_uncertain", 502) from None
        if outcome != "refunded":
            journal[rid]["state"] = "refused"
            _atomic_json(_journal_path(), journal)
            _audit({"event": "refund_refused", "appointmentId": rid, "amountCents": cents})
            raise RefundError("refund_refused_by_mercure", 502)
        journal[rid]["state"] = "refunded"
        _atomic_json(_journal_path(), journal)
        _audit({"event": "refund_done", "appointmentId": rid, "amountCents": cents})
    cancelled = False
    if claims.get("cancel"):
        try:
            cancelled = _cancel_call(session, rid, day)
        except Exception:
            cancelled = False
        with _lock():
            journal = _read_json(_journal_path(), {})
            if rid in journal:
                journal[rid]["cancelled"] = cancelled
                _atomic_json(_journal_path(), journal)
        _audit({"event": "cancel_done" if cancelled else "cancel_failed", "appointmentId": rid})
    return {"ok": True, "appointmentId": rid, "refundedCents": cents,
            "cancelRequested": bool(claims.get("cancel")), "cancelled": cancelled}


def verify_uncertain(payload: dict, *, environ=None, session_factory=None, now=None) -> dict:
    """Settle an "uncertain" refund from the planning, without calling Payline.

    Mercure empties the token and the billing lines once a refund is approved:
    seeing them empty proves the refund; seeing them still there proves it did
    not happen, and the booking may be refunded again. A booking that is gone
    stays uncertain: check it in Mercure and Payline."""
    if not enabled(environ):
        raise RefundError("refund_disabled", 403)
    if not isinstance(payload, dict) or set(payload) != {"appointmentId"}:
        raise RefundError("refund_body_invalid")
    rid = appointment_id(payload.get("appointmentId"))
    session = (session_factory or mercure._session)()
    with _lock():
        journal = _read_json(_journal_path(), {})
        entry = journal.get(rid)
        instant = time.time() if now is None else now
        stale = (entry or {}).get("state") == "pending" and int(entry.get("at") or 0) < instant - STALE_PENDING_SECONDS
        if not entry or (entry.get("state") != "uncertain" and not stale):
            raise RefundError("refund_not_uncertain", 409)
        try:
            facts = _facts(_find(session, rid, str(entry.get("bookingDay") or "")))
        except RefundError as exc:
            if exc.code != "refund_appointment_not_found":
                raise
            return {"ok": True, "appointmentId": rid, "state": "uncertain"}
        summary = facts["summary"]
        state = "refused" if summary["refundable"] else ("refunded" if not summary["paidOnline"] else "uncertain")
        entry["state"] = state
        _atomic_json(_journal_path(), journal)
        _audit({"event": "uncertain_settled", "appointmentId": rid, "state": state})
    return {"ok": True, "appointmentId": rid, "state": state}


def history(limit: int = 20) -> list[dict]:
    journal = _read_json(_journal_path(), {})
    rows = [{"appointmentId": rid, **{k: e.get(k) for k in ("state", "amountCents", "at", "cancelled")}}
            for rid, e in journal.items()]
    return sorted(rows, key=lambda r: r.get("at") or 0, reverse=True)[:limit]
