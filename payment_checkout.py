"""Trusted booking-to-payment bridge.

This module creates only internal sandbox intents. Price, service and contract
terms are resolved from server-side Mercure/compliance evidence; no browser
amount or service selection reaches payment_core. No provider call is made here.
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
from pathlib import Path

import booking_bridge as booking
import compliance_store as compliance
import payment_payline as payline
import payment_payline_private as payline_private
from payment_core import PaymentError, Quote, SandboxJournal


def journal_path() -> Path:
    return Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData")) / "payments.sqlite3"


def quote_for_confirmed_booking(external_id: str) -> Quote:
    try:
        basis = booking.authoritative_payment_basis(external_id)
    except Exception:
        raise PaymentError("authoritative_booking_required") from None
    try:
        receipt = compliance.contract_acceptance_receipt(external_id)
    except Exception:
        raise PaymentError("contract_acceptance_unavailable") from None
    if not receipt:
        raise PaymentError("contract_acceptance_required")
    terms_hash = str(receipt.get("contentHash") or "").lower()
    if receipt.get("contractRef") != external_id or receipt.get("documentType") != "terms":
        raise PaymentError("contract_acceptance_mismatch")
    return Quote(
        basis["bookingReference"],
        basis["service"],
        int(basis["amountCents"]),
        terms_hash,
    )


def create_sandbox_intent(external_id: str, provider: str = "payline") -> dict:
    if provider != "payline":
        raise PaymentError("payline_sandbox_required")
    quote = quote_for_confirmed_booking(external_id)
    intent = SandboxJournal(journal_path()).create(quote, provider)
    return {
        "paymentId": intent.payment_id,
        "provider": intent.provider,
        "environment": intent.environment,
        "state": intent.state,
        "amountCents": intent.amount_cents,
        "currency": "EUR",
    }


def _start_connection():
    path=journal_path()
    store=SandboxJournal(path)
    db=sqlite3.connect(path,timeout=5)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("""CREATE TABLE IF NOT EXISTS payment_provider_starts(
      payment_id TEXT PRIMARY KEY REFERENCES payment_intents(payment_id),
      provider TEXT NOT NULL CHECK(provider='payline'),
      state TEXT NOT NULL CHECK(state IN ('attempting','ready','indeterminate')),
      provider_reference TEXT NOT NULL DEFAULT '',
      redirect_url TEXT NOT NULL DEFAULT '',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )""")
    db.commit()
    return store,db


def start_payline_for_browser(ccid: str, cct: str, *, starter=None) -> dict:
    try:
        external_id=booking.authoritative_external_id_for_browser_token(ccid,cct)
    except PermissionError:
        raise PaymentError("payment_browser_token_invalid") from None
    except Exception:
        raise PaymentError("authoritative_booking_required") from None

    quote=quote_for_confirmed_booking(external_id)
    store,db=_start_connection()
    try:
        intent=store.create(quote,"payline")
        db.execute("BEGIN IMMEDIATE")
        existing=db.execute(
            "SELECT * FROM payment_provider_starts WHERE payment_id=?",
            (intent.payment_id,),
        ).fetchone()
        if existing:
            state=str(existing["state"])
            if state=="ready":
                return {
                    "paymentId":intent.payment_id,
                    "provider":"payline",
                    "environment":"sandbox",
                    "state":intent.state,
                    "amountCents":intent.amount_cents,
                    "currency":"EUR",
                    "redirectUrl":str(existing["redirect_url"]),
                    "reused":True,
                }
            raise PaymentError("payment_start_reconciliation_required")
        config=payline_private.load()
        start_fn=starter or payline.start
        now=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        db.execute("""INSERT INTO payment_provider_starts(
          payment_id,provider,state,provider_reference,redirect_url,created_at,updated_at
        ) VALUES(?,'payline','attempting','','',?,?)""",(intent.payment_id,now,now))
        db.commit()

        try:
            result=start_fn(intent,config)
            bound=store.bind_provider(intent.payment_id,result.token)
            db.execute("BEGIN IMMEDIATE")
            db.execute("""UPDATE payment_provider_starts
              SET state='ready',provider_reference=?,redirect_url=?,updated_at=?
              WHERE payment_id=? AND state='attempting'""",
              (result.token,result.redirect_url,dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),intent.payment_id))
            db.commit()
        except Exception:
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute("""UPDATE payment_provider_starts
                  SET state='indeterminate',updated_at=?
                  WHERE payment_id=? AND state='attempting'""",
                  (dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),intent.payment_id))
                db.commit()
            except Exception:
                pass
            raise

        return {
            "paymentId":bound.payment_id,
            "provider":"payline",
            "environment":"sandbox",
            "state":bound.state,
            "amountCents":bound.amount_cents,
            "currency":"EUR",
            "redirectUrl":result.redirect_url,
            "reused":False,
        }
    finally:
        db.close()


def capability() -> dict:
    return {
        "environment": "sandbox",
        "authoritativeBookingBound": True,
        "contractAcceptanceBound": True,
        "serverAuthoritativePrice": True,
        "browserAmountAccepted": False,
        "browserServiceAccepted": False,
        "sandboxIntentCreationBound": True,
        "providerStartBound": True,
        "publicStartRouteBound": True,
        "ambiguousStartRetryBlocked": True,
        "livePaymentsEnabled": False,
    }
