"""Persistent account-scoped booking/payment association; never payment authority.

A bound reference proves only that a trusted server associated identifiers.
It does not prove payment capture, provider authentication or a booking hold.
"""
from __future__ import annotations
import datetime as dt
import os
import re
import sqlite3
from pathlib import Path
from customer_booking_journal import _digest, status as booking_status


class BookingPaymentBindingError(ValueError):
    pass


def _reference(value: object, pattern: str, code: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise BookingPaymentBindingError(code)
    return value


def _connect():
    path = Path(os.environ.get('CYBERCHECK_DATA_DIR', '/root/CyberCheckData')) / 'customer-booking-payment-binding.sqlite3'
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=10000')
    db.execute('''CREATE TABLE IF NOT EXISTS payment_binding (
      request_key TEXT PRIMARY KEY, account_hash TEXT NOT NULL,
      provider_booking_ref TEXT NOT NULL, payment_ref TEXT NOT NULL UNIQUE,
      payment_provider TEXT NOT NULL, created_at TEXT NOT NULL)''')
    return db


def bind(*, account_id: str, request_key: str, provider_booking_ref: str,
         payment_ref: str, payment_provider: str, authorized: bool = False) -> dict:
    if authorized is not True:
        raise BookingPaymentBindingError('payment_binding_not_authorized')
    _reference(account_id, r'[A-Za-z0-9_-]{1,128}', 'account_invalid')
    _reference(request_key, r'[A-Za-z0-9_-]{20,128}', 'request_key_invalid')
    _reference(provider_booking_ref, r'[A-Za-z0-9_-]{1,128}', 'booking_reference_invalid')
    _reference(payment_ref, r'[A-Za-z0-9_-]{1,128}', 'payment_reference_invalid')
    _reference(payment_provider, r'(?:payline|paypal|monetico)', 'payment_provider_invalid')
    booking = booking_status(account_id=account_id, key=request_key)
    if booking.get('confirmed') is not True or booking.get('providerReference') != provider_booking_ref:
        raise BookingPaymentBindingError('booking_not_independently_confirmed')
    account_hash = _digest(account_id)
    with _connect() as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            existing = db.execute('SELECT * FROM payment_binding WHERE request_key=?', (request_key,)).fetchone()
            if existing is None:
                db.execute('''INSERT INTO payment_binding VALUES (?,?,?,?,?,?)''',
                    (request_key, account_hash, provider_booking_ref, payment_ref, payment_provider,
                     dt.datetime.now(dt.timezone.utc).isoformat()))
            elif (existing['account_hash'], existing['provider_booking_ref'], existing['payment_ref'],
                  existing['payment_provider']) != (account_hash, provider_booking_ref, payment_ref, payment_provider):
                raise BookingPaymentBindingError('payment_binding_conflict')
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
    return {'bound': True, 'paymentRef': payment_ref, 'provider': payment_provider, 'paid': False}


def lookup(*, account_id: str, request_key: str) -> dict:
    _reference(account_id, r'[A-Za-z0-9_-]{1,128}', 'account_invalid')
    _reference(request_key, r'[A-Za-z0-9_-]{20,128}', 'request_key_invalid')
    booking = booking_status(account_id=account_id, key=request_key)
    if booking.get('confirmed') is not True:
        return {'bound': False, 'paid': False}
    with _connect() as db:
        row = db.execute('SELECT * FROM payment_binding WHERE request_key=?', (request_key,)).fetchone()
    if row is None or row['account_hash'] != _digest(account_id) or row['provider_booking_ref'] != booking.get('providerReference'):
        return {'bound': False, 'paid': False}
    return {'bound': True, 'paymentRef': row['payment_ref'], 'provider': row['payment_provider'],
            'providerBookingRef': row['provider_booking_ref'], 'paid': False}


def request_key_for_payment(payment_ref: str) -> str | None:
    """Request key bound to a payment, used only to route the browser back.

    Never authority: the confirmation page re-reads booking and payment state
    for the authenticated account.
    """
    _reference(payment_ref, r'[A-Za-z0-9_-]{1,128}', 'payment_reference_invalid')
    with _connect() as db:
        row = db.execute('SELECT request_key FROM payment_binding WHERE payment_ref=?', (payment_ref,)).fetchone()
    return str(row['request_key']) if row else None
