"""Booking paid through Mercure's own Payline checkout (rdv.checkupauto.fr).

Mercure only starts its Payline payment from the public booking call
``POST /add_rendezvous_client_libre`` with ``p_centre=1`` (online payment); the
answer is the URL the browser must follow. That call creates a real
appointment, so it is sent at most once per idempotency key and never
replayed: any doubt leaves the request in ``reconciliation_required``.

Confirmation never comes from the browser. After the customer returns, the
appointment is looked up in the admin planning and is only confirmed when
Mercure shows an online payment for it. The Payline token is never returned.

A real paid test on 2026-10-14 showed that Mercure creates the appointment
and blocks the slot before payment, answers with the Payline production page
(webpayment.payline.com), and records the payment as a billing line. Still to
confirm (see docs/api-mercure.md): the page Payline returns the customer to,
what happens to an appointment that is never paid, and the date/time and
energy formats the public call expects.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import customer_booking_api
import customer_booking_journal as journal
import mercure_admin_client
import mercure_customer_booking_assembly
import mercure_public_client as public
from mercure_booking_write_contract import BookingWriteRequest

ENABLE_ENV = "CHECKUPAUTO_MERCURE_HOSTED_PAYMENT_ENABLED"
# Live test 2026-10-14: Mercure answers with the Payline hosted page directly.
CHECKOUT_HOSTS = ("webpayment.payline.com", "rdv.checkupauto.fr")


class HostedCheckoutError(RuntimeError):
    """Stable, non-sensitive error code."""


class HostedCheckoutInvalid(ValueError):
    pass


def enabled(environ=None) -> bool:
    env = os.environ if environ is None else environ
    return str(env.get(ENABLE_ENV) or "").strip().lower() == "true"


def build_form(*, appointment: dict, service_id: str, date: str, time: str) -> dict:
    """Fields of the public Mercure booking call, online payment selected."""
    required = ("nom", "prenom", "email", "telephone", "marque", "modele",
                "energie", "immatriculation")
    if not isinstance(appointment, dict) or not all(
            isinstance(appointment.get(k), str) and appointment[k].strip() for k in required):
        raise HostedCheckoutInvalid("mercure_checkout_customer_incomplete")
    if not re.fullmatch(r"[0-9]{1,12}", str(service_id)):
        raise HostedCheckoutInvalid("mercure_checkout_service_invalid")
    phone = re.sub(r"\D", "", appointment["telephone"])
    if phone.startswith("33") and len(phone) == 11:
        phone = "0" + phone[2:]
    if len(phone) < 10:
        raise HostedCheckoutInvalid("mercure_checkout_phone_invalid")
    return {
        "prestation_vl": str(service_id), "prestation_pl[]": "",
        "date_rdv": date, "heure_rdv": time,
        "nom": appointment["nom"].strip(), "prenom": appointment["prenom"].strip(),
        "telephone": phone, "civilite": "", "email": appointment["email"].strip(),
        "marque": appointment["marque"], "modele": appointment["modele"],
        "energie": appointment["energie"], "immatriculation": appointment["immatriculation"],
        "code_promo": "", "pay2x": "0", "payassucv": "0", "paymodif": "0",
        # Mercure's naming is inverted: p_centre=1 is the online (Payline) button.
        "p_centre": "1",
        "iframe": "false", "id": "", "smsrappel": "0", "smsconfirm": "0",
    }


def checkout_url(raw: object) -> str:
    """Accept only an https URL on Payline's hosted page or Mercure."""
    value = str(raw or "").strip()
    if value.lower() == "error":
        raise HostedCheckoutError("mercure_checkout_refused")
    if value.startswith("/"):
        value = public.BASE + value
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        raise HostedCheckoutError("mercure_checkout_response_uncertain") from None
    if (parsed.scheme != "https" or parsed.username or parsed.password
            or port not in (None, 443) or len(value) > 2048
            or host not in CHECKOUT_HOSTS):
        raise HostedCheckoutError("mercure_checkout_response_uncertain")
    return value


def _vehicle(account: dict, vehicle_id: str) -> dict:
    vehicles = account.get("vehicles")
    matches = [v for v in vehicles if isinstance(v, dict) and v.get("vehicleId") == vehicle_id] \
        if isinstance(vehicles, list) else []
    if len(matches) != 1:
        raise HostedCheckoutInvalid("booking_vehicle_not_owned")
    return matches[0]


def _journal_request(service: str, date: str, time: str, vehicle_id: str) -> dict:
    return {"channel": "mercure-hosted", "service": service, "date": date,
            "time": time, "vehicleId": vehicle_id}


def start(payload: object, *, account: dict, environ=None, session_factory=None,
          payment_options=None) -> dict:
    if not enabled(environ):
        raise HostedCheckoutError("mercure_hosted_payment_disabled")
    if not isinstance(payload, dict) or set(payload) != {"service", "date", "time", "vehicleId", "requestKey"}:
        raise HostedCheckoutInvalid("booking_create_request_invalid")
    if not all(isinstance(v, str) for v in payload.values()):
        raise HostedCheckoutInvalid("booking_create_request_invalid")
    try:
        checked = customer_booking_api.preflight(
            {k: payload[k] for k in ("service", "date", "time", "vehicleId")}, account=account)
    except customer_booking_api.BookingPreflightError as exc:
        raise HostedCheckoutInvalid(str(exc)) from None
    options = (payment_options or public.payment_options)(checked["service"])
    if options.get("online") is not True:
        raise HostedCheckoutError("mercure_online_payment_unavailable")
    request = BookingWriteRequest(
        request_key=payload["requestKey"], account_id=account["accountId"],
        vehicle_id=checked["vehicleId"], service=checked["service"],
        date=checked["date"], time=checked["time"], price_cents=checked["priceCents"])
    try:
        assembled = mercure_customer_booking_assembly.assemble(
            request=request, account=account, vehicle=_vehicle(account, checked["vehicleId"]))
    except ValueError as exc:
        raise HostedCheckoutInvalid(str(exc)) from None
    form = build_form(appointment=assembled["appointment"],
                      service_id=public.service(checked["service"])["id"],
                      date=checked["date"], time=checked["time"])

    journal_request = _journal_request(checked["service"], checked["date"],
                                       checked["time"], checked["vehicleId"])
    # Open the Mercure session before claiming the key: a failure here has
    # sent nothing, so the customer can retry with the same key.
    session = (session_factory or public._provider_session)()
    try:
        prepared = journal.prepare(account_id=account["accountId"], key=payload["requestKey"],
                                   request=journal_request)
        if prepared["state"] != "prepared":
            # Already sent once: never replay a call that creates an appointment.
            raise HostedCheckoutError("booking_reconciliation_required")
        journal.require_reconciliation(account_id=account["accountId"], key=payload["requestKey"])
    except BaseException:
        session.close()
        raise
    try:
        response = session.post(public.BASE + "/add_rendezvous_client_libre", data=form,
                                timeout=30, allow_redirects=False)
        if response.status_code != 200:
            raise HostedCheckoutError("mercure_checkout_response_uncertain")
        url = checkout_url(response.text)
    except HostedCheckoutError:
        raise
    except Exception:
        raise HostedCheckoutError("mercure_checkout_response_uncertain") from None
    finally:
        try:
            session.close()
        except Exception:
            pass
    return {"ok": True, "state": "payment_pending", "requestKey": payload["requestKey"],
            "redirectUrl": url, "priceCents": checked["priceCents"]}


def reconcile(payload: object, *, account: dict, finder=None) -> dict:
    """Confirm the request only if the admin planning shows it paid online.

    The slot comes from the browser but must match exactly what this account
    bound to the key when the checkout started."""
    if not isinstance(payload, dict) or set(payload) != {"service", "date", "time", "vehicleId", "requestKey"}:
        raise HostedCheckoutInvalid("booking_status_request_invalid")
    if not all(isinstance(v, str) for v in payload.values()):
        raise HostedCheckoutInvalid("booking_status_request_invalid")
    service_id = public.service(payload["service"])["id"]
    request = _journal_request(payload["service"], payload["date"], payload["time"], payload["vehicleId"])
    if not journal.matches_request(account_id=account["accountId"], key=payload["requestKey"],
                                   request=request):
        raise HostedCheckoutInvalid("booking_request_not_found")
    current = journal.status(account_id=account["accountId"], key=payload["requestKey"])
    if current["confirmed"]:
        return {"ok": True, "state": "confirmed", "confirmed": True, "paid": True,
                "providerReference": current["providerReference"]}
    if current["state"] != "reconciliation_required":
        return {"ok": True, "state": current["state"], "confirmed": False, "paid": False}
    found = (finder or mercure_admin_client.find_online_booking)(
        date=payload["date"], time=payload["time"], email=str(account.get("email") or ""),
        service_id=service_id)
    if not found.get("found"):
        return {"ok": True, "state": "reconciliation_required", "confirmed": False, "paid": False}
    if found.get("paidOnline") is not True:
        return {"ok": True, "state": "payment_pending", "confirmed": False, "paid": False}
    confirmed = journal.confirm_verified(
        account_id=account["accountId"], key=payload["requestKey"],
        provider_reference=found["appointmentId"], verified=True)
    return {"ok": True, "state": "confirmed", "confirmed": True, "paid": True,
            "providerReference": confirmed["providerReference"]}
