"""Staging-only reservation + payment rehearsal.

This module creates real Mercure synthetic appointments and exercises the local
Payline payment domain without contacting a bank. It is disabled unless
CYBERCHECK_PAYMENT_TEST_ENABLED is explicitly enabled.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
from urllib.parse import quote

import analytics_store as analytics
import booking_bridge as booking
import booking_test
import mercure_admin_client as mercure_admin
import compliance_store as compliance
import payment_checkout as checkout
import payment_payline as payline
import payment_payline_private as payline_private
from payment_core import PaymentError, SandboxJournal


SERVICE_LABELS = {
    "technical": "Contrôle technique",
    "fitted": "Véhicule aménagé",
}
OUTCOME_RESULTS = {
    "captured": ("00000", "ACCEPTED"),
    "declined": ("01001", "REFUSED"),
    "pending": ("02005", "INPROGRESS"),
    "cancelled": ("02319", "CANCELLED"),
    "error": ("02101", "ERROR"),
}


class PaymentTestError(ValueError):
    pass


def enabled() -> bool:
    return str(os.environ.get("CYBERCHECK_PAYMENT_TEST_ENABLED", "0")).strip().lower() in {
        "1", "true", "yes", "on"
    }


def _require_enabled() -> None:
    if not enabled():
        raise PermissionError("payment_test_disabled")


def _step(code: str, fn):
    try:
        return fn()
    except PaymentTestError:
        raise
    except Exception:
        raise PaymentTestError(code) from None


def _hash(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def init_db() -> None:
    with analytics.connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS payment_test_runs(
          test_token_hash TEXT PRIMARY KEY,
          payment_id TEXT NOT NULL UNIQUE,
          external_id TEXT NOT NULL,
          service_key TEXT NOT NULL,
          appointment_at TEXT NOT NULL,
          state TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )""")


def _payline_demo_status() -> dict:
    status = payline_private.status()
    return {
        "provider": "payline",
        "environment": "sandbox",
        "configured": bool(status.get("configured")),
        "configurationValid": bool(status.get("configurationValid")),
        "checkoutBound": bool(status.get("checkoutBound")),
        "callbacksBound": bool(status.get("callbacksBound")),
        "livePaymentsEnabled": False,
        "blockingReasons": list(status.get("blockingReasons") or []),
    }


def demo_status() -> dict:
    _require_enabled()
    return {
        "ok": True,
        "mode": "staging-demo",
        "site": {"homepage": "/", "booking": "/#reservation", "contact": "/contact"},
        "payment": {
            "simulation": "/payment/test",
            "checkout": "/payment/payline/checkout",
            "paylineSandbox": _payline_demo_status(),
        },
        "backend": {
            "bookingServices": "/api/booking/services",
            "bookingAvailability": "/api/booking/availability",
            "mobileBootstrap": "/api/mobile/bootstrap",
        },
        "refundPolicy": "contact-only",
    }


def create_session() -> dict:
    _require_enabled()
    if not mercure_admin.session_status().get("connected"):
        raise PaymentTestError("payment_test_mercure_session_required")
    session=booking_test.create_session()
    return {
        "ok": True,
        "mode": "reservation-payment-test",
        "token": session["token"],
        "expiresAt": session["expiresAt"],
        "paylineSandbox": _payline_demo_status(),
        "safety": "Synthetic Mercure appointment; sandbox payment only; no live production debit.",
    }


def _service(value: object) -> tuple[str,str]:
    key=str(value or "").strip()
    label=SERVICE_LABELS.get(key)
    if not label:
        raise PaymentTestError("payment_test_service_invalid")
    return key,label


def _appointment(value: object, name: str, pattern: str) -> str:
    raw=str(value or "").strip()
    if not re.fullmatch(pattern,raw):
        raise PaymentTestError(f"payment_test_{name}_invalid")
    return raw


def _test_terms() -> dict:
    current=compliance.published_document("terms")
    if current:
        return current
    if not enabled():
        raise PaymentTestError("payment_test_terms_unavailable")
    return compliance.save_document({
        "type":"terms",
        "version":"staging-test-v1",
        "title":"Conditions de test — staging",
        "body":(
            "Document exclusivement destiné aux essais du parcours CheckupAuto sur l’environnement "
            "de staging. Il ne constitue pas les conditions générales de vente de production et "
            "n’autorise aucun encaissement bancaire réel. Les rendez-vous créés par ce parcours "
            "sont synthétiques et doivent être supprimés à l’issue du test."
        ),
        "action":"publish",
    })


def create_reservation(token: str, service_key: str, date_value: str, time_value: str,
                       *, accept_terms: bool, immediate_performance: bool) -> dict:
    _require_enabled()
    if accept_terms is not True:
        raise PaymentTestError("payment_test_terms_required")
    token=str(token or "")
    booking_test.status(token)
    key,label=_service(service_key)
    date_value=_appointment(date_value,"date",r"\d{4}-\d{2}-\d{2}")
    time_value=_appointment(time_value,"time",r"\d{2}:\d{2}")

    created_appointment=False
    try:
        appointment=_step(
            "payment_test_mercure_create_failed",
            lambda: booking_test.create_appointment(token,key,date_value,time_value),
        )
        created_appointment=True

        site_booking=_step("payment_test_booking_intent_failed",lambda: booking.create_intent({
            "service":label,
            "preferredDate":date_value,
            "preferredTime":time_value,
            "device":"desktop",
            "path":"/payment/test",
            "utmSource":"reservation-payment-test",
            "utmCampaign":"hostinger-staging",
        }, "https://rdv.checkupauto.fr/"))
        ccid=str(site_booking["token"])
        cct=_step("payment_test_browser_binding_failed",lambda: booking.browser_token(ccid))

        terms=_step("payment_test_terms_lookup_failed",_test_terms)
        _step("payment_test_terms_acceptance_failed",lambda: booking.record_terms_acceptance({
            "ccid":ccid,
            "cct":cct,
            "termsVersion":terms.get("version"),
            "termsContentHash":terms.get("contentHash"),
            "accepted":True,
            "reviewed":True,
            "immediatePerformance":bool(immediate_performance),
        }))

        external_id=str(appointment["appointmentId"])
        conversion=_step("payment_test_conversion_failed",lambda: booking.apply_conversion({
            "externalId":external_id,
            "status":"confirmed",
            "ccid":ccid,
            "appointmentDate":str(appointment["appointmentAt"]),
            "service":label,
            "amount":float(appointment["price"]),
        }, acceptance_source="staging_synthetic_mercure_contract_confirmation"))
        if not conversion.get("contractAcceptanceBound"):
            raise PaymentTestError("payment_test_contract_binding_failed")

        payment=_step("payment_test_payment_intent_failed",lambda: checkout.create_sandbox_intent(external_id))
        payment_id=str(payment["paymentId"])
        store=_step("payment_test_payment_store_failed",lambda: SandboxJournal(checkout.journal_path()))
        provider_reference="TESTPAY_"+payment_id
        _step("payment_test_payment_binding_failed",lambda: store.bind_provider(payment_id,provider_reference))

        _step("payment_test_ledger_init_failed",init_db)
        now=_now()
        with analytics.connect() as db:
            db.execute("""INSERT INTO payment_test_runs(
              test_token_hash,payment_id,external_id,service_key,appointment_at,state,created_at,updated_at
            ) VALUES(?,?,?,?,?,'payment-ready',?,?)""",
            (_hash(token),payment_id,external_id,key,str(appointment["appointmentAt"]),now,now))

        return {
            "ok":True,
            "mode":"reservation-payment-test",
            "appointment":{
                "id":external_id,
                "service":key,
                "appointmentAt":str(appointment["appointmentAt"]),
                "price":float(appointment["price"]),
                "providerVerified":bool(appointment.get("providerVerified")),
            },
            "payment":{
                "paymentId":payment_id,
                "provider":"payline-simulator",
                "environment":"sandbox",
                "amountCents":int(payment["amountCents"]),
                "currency":"EUR",
                "state":"created",
            },
            "providerUrl":f"/payment/test/provider#token={token}&paymentId={payment_id}",
            "safety":"No bank request has been made.",
        }
    except Exception:
        if created_appointment:
            try:
                booking_test.remove_appointment(token)
            except Exception:
                pass
        raise


def prepare_payline_checkout(token: str, service_key: str, date_value: str, time_value: str,
                             *, accept_terms: bool, immediate_performance: bool) -> dict:
    """Prepare a synthetic Mercure booking for the real Payline homologation checkout.

    This function deliberately stops before creating a payment intent or calling Payline.
    The normal first-party checkout creates the intent and invokes doWebPayment only after
    the tester explicitly clicks its payment button.
    """
    _require_enabled()
    payline_status = _payline_demo_status()
    if not payline_status["configured"] or not payline_status["configurationValid"]:
        raise PaymentTestError("payment_test_payline_not_configured")
    if accept_terms is not True:
        raise PaymentTestError("payment_test_terms_required")
    token=str(token or "")
    booking_test.status(token)
    key,label=_service(service_key)
    date_value=_appointment(date_value,"date",r"\d{4}-\d{2}-\d{2}")
    time_value=_appointment(time_value,"time",r"\d{2}:\d{2}")

    created_appointment=False
    try:
        appointment=_step(
            "payment_test_mercure_create_failed",
            lambda: booking_test.create_appointment(token,key,date_value,time_value),
        )
        created_appointment=True

        site_booking=_step("payment_test_booking_intent_failed",lambda: booking.create_intent({
            "service":label,
            "preferredDate":date_value,
            "preferredTime":time_value,
            "device":"desktop",
            "path":"/payment/test",
            "utmSource":"reservation-payment-test",
            "utmCampaign":"hostinger-staging-payline",
        }, "https://rdv.checkupauto.fr/"))
        ccid=str(site_booking["token"])
        cct=_step("payment_test_browser_binding_failed",lambda: booking.browser_token(ccid))

        terms=_step("payment_test_terms_lookup_failed",_test_terms)
        _step("payment_test_terms_acceptance_failed",lambda: booking.record_terms_acceptance({
            "ccid":ccid,
            "cct":cct,
            "termsVersion":terms.get("version"),
            "termsContentHash":terms.get("contentHash"),
            "accepted":True,
            "reviewed":True,
            "immediatePerformance":bool(immediate_performance),
        }))

        external_id=str(appointment["appointmentId"])
        conversion=_step("payment_test_conversion_failed",lambda: booking.apply_conversion({
            "externalId":external_id,
            "status":"confirmed",
            "ccid":ccid,
            "appointmentDate":str(appointment["appointmentAt"]),
            "service":label,
            "amount":float(appointment["price"]),
        }))
        if not conversion.get("contractAcceptanceBound"):
            raise PaymentTestError("payment_test_contract_binding_failed")

        checkout_url=(
            "/payment/payline/checkout#ccid="+quote(ccid,safe="")
            +"&cct="+quote(cct,safe="")
        )
        return {
            "ok": True,
            "mode": "reservation-payline-homologation-test",
            "appointment": {
                "id": external_id,
                "service": key,
                "appointmentAt": str(appointment["appointmentAt"]),
                "price": float(appointment["price"]),
                "providerVerified": bool(appointment.get("providerVerified")),
            },
            "checkoutUrl": checkout_url,
            "paylineSandbox": payline_status,
            "safety": "Payline homologation only; live production payments remain disabled.",
        }
    except Exception:
        if created_appointment:
            try:
                booking_test.remove_appointment(token)
            except Exception:
                pass
        raise


def _run(token: str, payment_id: str):
    _require_enabled()
    booking_test.status(token)
    init_db()
    with analytics.connect() as db:
        row=db.execute(
            "SELECT * FROM payment_test_runs WHERE test_token_hash=? AND payment_id=? LIMIT 1",
            (_hash(token),str(payment_id or "")),
        ).fetchone()
    if not row:
        raise PermissionError("payment_test_forbidden")
    return dict(row)


def _details_xml(*, code: str, short_message: str, payment_id: str, provider_reference: str,
                 amount_cents: int, transaction_id: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
 xmlns:impl="http://impl.ws.payline.experian.com"
 xmlns:obj="http://obj.ws.payline.experian.com">
 <soapenv:Body>
  <impl:getWebPaymentDetailsResponse>
   <impl:result><obj:code>{code}</obj:code><obj:shortMessage>{short_message}</obj:shortMessage></impl:result>
   <impl:transaction><obj:id>{transaction_id}</obj:id></impl:transaction>
   <impl:payment><obj:amount>{amount_cents}</obj:amount><obj:currency>978</obj:currency></impl:payment>
   <impl:order><obj:ref>{payment_id}</obj:ref><obj:amount>{amount_cents}</obj:amount><obj:currency>978</obj:currency></impl:order>
  </impl:getWebPaymentDetailsResponse>
 </soapenv:Body>
</soapenv:Envelope>""".encode("utf-8")


def apply_result(token: str, payment_id: str, outcome: str) -> dict:
    row=_run(token,payment_id)
    outcome=str(outcome or "").strip().lower()
    result=OUTCOME_RESULTS.get(outcome)
    if not result:
        raise PaymentTestError("payment_test_outcome_invalid")
    code,short_message=result
    store=SandboxJournal(checkout.journal_path())
    intent=store.get(str(payment_id))
    if intent.provider!="payline" or not intent.provider_reference:
        raise PaymentError("payline_bound_intent_required")
    transaction_id="TESTTXN_"+str(payment_id)[:24]
    event=payline.parse_details_response(
        _details_xml(
            code=code,
            short_message=short_message,
            payment_id=intent.payment_id,
            provider_reference=intent.provider_reference,
            amount_cents=intent.amount_cents,
            transaction_id=transaction_id,
        ),
        intent,
        intent.provider_reference,
    )
    updated=store._apply_verified(event)
    now=_now()
    with analytics.connect() as db:
        db.execute(
            "UPDATE payment_test_runs SET state=?,updated_at=? WHERE test_token_hash=? AND payment_id=?",
            (updated.state,now,_hash(token),payment_id),
        )
    return {
        "ok":True,
        "mode":"reservation-payment-test",
        "paymentId":updated.payment_id,
        "state":updated.state,
        "amountCents":updated.amount_cents,
        "currency":"EUR",
        "providerTransactionVerified":bool(event.provider_transaction_id),
        "safety":"Simulated Payline homologation result; no bank debit.",
    }


def status(token: str) -> dict:
    _require_enabled()
    session=booking_test.status(token)
    init_db()
    with analytics.connect() as db:
        row=db.execute(
            "SELECT payment_id,external_id,service_key,appointment_at,state,created_at,updated_at FROM payment_test_runs WHERE test_token_hash=?",
            (_hash(token),),
        ).fetchone()
    return {
        "ok":True,
        "mode":"reservation-payment-test",
        "bookingTest":session,
        "run":dict(row) if row else None,
    }


def remove(token: str) -> dict:
    _require_enabled()
    result=booking_test.remove_appointment(token)
    init_db()
    with analytics.connect() as db:
        db.execute(
            "UPDATE payment_test_runs SET state='removed',updated_at=? WHERE test_token_hash=?",
            (_now(),_hash(token)),
        )
    return {
        "ok":True,
        "mode":"reservation-payment-test",
        "appointmentRemoved":bool(result.get("removed")),
        "safety":"Synthetic Mercure appointment removed.",
    }
