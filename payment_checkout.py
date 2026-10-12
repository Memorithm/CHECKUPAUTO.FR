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
    return start_payline_for_booking(external_id, starter=starter)


def start_payline_for_booking(external_id: str, *, starter=None) -> dict:
    """Start (or reuse) the Payline checkout of a confirmed Mercure booking.

    Callers must already have resolved ``external_id`` from server-side
    authority (browser token or the authenticated customer journal).
    """
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
        except PaymentError as exc:
            if str(exc) == "payline_start_refused":
                # A provider-level refusal is definitive: no hosted-payment
                # session was created, so keeping an "indeterminate" lock would
                # incorrectly prevent a corrected retry. Remove only this
                # pre-session attempt marker; the server-authoritative payment
                # intent remains unchanged.
                try:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute(
                        "DELETE FROM payment_provider_starts WHERE payment_id=? AND state='attempting'",
                        (intent.payment_id,),
                    )
                    db.commit()
                except Exception:
                    pass
                raise
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


def activity(limit: int = 50) -> dict:
    if type(limit) is not int or not 1 <= limit <= 100:
        raise PaymentError("payment_activity_limit_invalid")
    path=journal_path()
    if not path.is_file():
        return {
            "summary":{"total":0,"created":0,"pending":0,"declined":0,"cancelled":0,"error":0,
                       "authorized":0,"captured":0,"readyStarts":0,"indeterminateStarts":0},
            "transactions":[],
        }
    store=SandboxJournal(path)
    del store
    with sqlite3.connect(path,timeout=5) as db:
        db.row_factory=sqlite3.Row
        has_starts=bool(db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='payment_provider_starts'"
        ).fetchone())
        if has_starts:
            rows=db.execute("""SELECT i.payment_id,i.provider,i.environment,i.amount_cents,i.currency,
              i.state,i.created_at,i.provider_reference,s.state AS start_state
              FROM payment_intents i
              LEFT JOIN payment_provider_starts s ON s.payment_id=i.payment_id
              ORDER BY i.created_at DESC,i.payment_id DESC LIMIT ?""",(limit,)).fetchall()
            start_counts={
                row["state"]:int(row["n"]) for row in db.execute(
                    "SELECT state,COUNT(*) AS n FROM payment_provider_starts GROUP BY state"
                ).fetchall()
            }
        else:
            rows=db.execute("""SELECT payment_id,provider,environment,amount_cents,currency,
              state,created_at,provider_reference,NULL AS start_state
              FROM payment_intents
              ORDER BY created_at DESC,payment_id DESC LIMIT ?""",(limit,)).fetchall()
            start_counts={}
        state_counts={
            row["state"]:int(row["n"]) for row in db.execute(
                "SELECT state,COUNT(*) AS n FROM payment_intents GROUP BY state"
            ).fetchall()
        }
        total=int(db.execute("SELECT COUNT(*) FROM payment_intents").fetchone()[0])
    return {
        "summary":{
            "total":total,
            "created":state_counts.get("created",0),
            "pending":state_counts.get("pending",0),
            "declined":state_counts.get("declined",0),
            "cancelled":state_counts.get("cancelled",0),
            "error":state_counts.get("error",0),
            "authorized":state_counts.get("authorized",0),
            "captured":state_counts.get("captured",0),
            "readyStarts":start_counts.get("ready",0),
            "indeterminateStarts":start_counts.get("indeterminate",0),
        },
        "transactions":[{
            "paymentId":str(row["payment_id"]),
            "provider":str(row["provider"]),
            "environment":str(row["environment"]),
            "amountCents":int(row["amount_cents"]),
            "currency":str(row["currency"]),
            "state":str(row["state"]),
            "createdAt":str(row["created_at"]),
            "providerBound":bool(row["provider_reference"]),
            "startState":str(row["start_state"] or ""),
        } for row in rows],
    }


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
