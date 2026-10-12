"""Sandbox payment domain. Internal API only; NOT a checkout authorization boundary.

A trusted booking adapter must create Quote from provider-authoritative price and
recorded terms acceptance. That adapter/public routes are intentionally not bound
by this tranche. Payline intents may be "production" only when created by the
gated checkout (payment_payline_private live gate); browser-success mutations
are never supported.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import stat
import uuid

ENVIRONMENTS = ("sandbox", "production")
from dataclasses import dataclass
from pathlib import Path


class PaymentError(ValueError):
    """Errors contain stable codes, never provider bodies or credentials."""


def text(value: object, pattern: str, code: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise PaymentError(code)
    return value


def cents(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 9000:
        raise PaymentError("amount_invalid")
    return value


def decimal_amount(value: int) -> str:
    return f"{cents(value) // 100}.{value % 100:02d}"


def parse_eur(value: object) -> int:
    raw = text(value, r"[0-9]{1,5}(?:\.[0-9]{1,2})?", "amount_invalid")
    whole, _, fraction = raw.partition(".")
    return cents(int(whole) * 100 + int(fraction.ljust(2, "0")))


def digest(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Quote:
    booking_reference: str
    service: str
    amount_cents: int
    terms_hash: str

    def __post_init__(self):
        text(self.booking_reference, r"[A-Za-z0-9:_-]{1,120}", "booking_reference_invalid")
        maximum = {"technical": 8000, "fitted": 9000}.get(self.service)
        if maximum is None or cents(self.amount_cents) > maximum:
            raise PaymentError("service_or_price_invalid")
        text(self.terms_hash, r"[0-9a-f]{64}", "terms_hash_invalid")


@dataclass(frozen=True)
class Intent:
    payment_id: str
    provider: str
    amount_cents: int
    created_at: str
    provider_reference: str = ""
    state: str = "created"
    environment: str = "sandbox"

    def __post_init__(self):
        text(self.payment_id, r"[0-9a-f]{32}", "payment_id_invalid")
        if self.provider not in {"paypal", "monetico", "payline"}:
            raise PaymentError("sandbox_provider_required")
        # Only Payline has a gated production path; other providers stay sandbox.
        if self.environment not in ENVIRONMENTS or (self.environment == "production" and self.provider != "payline"):
            raise PaymentError("sandbox_provider_required")
        cents(self.amount_cents)
        try:
            created = dt.datetime.fromisoformat(self.created_at)
            if created.utcoffset() is None:
                raise ValueError
        except (ValueError, TypeError):
            raise PaymentError("timestamp_invalid") from None
        if self.provider_reference:
            text(self.provider_reference, r"[A-Za-z0-9_-]{1,128}", "provider_reference_invalid")
        if self.state not in {"created", "pending", "declined", "cancelled", "error", "authorized", "captured"}:
            raise PaymentError("state_invalid")


@dataclass(frozen=True)
class VerifiedEvent:
    """Only provider verifiers may supply this internal value to the journal."""
    payment_id: str
    provider: str
    provider_reference: str
    event_id: str
    state: str
    amount_cents: int
    provider_transaction_id: str = ""

    def __post_init__(self):
        text(self.payment_id, r"[0-9a-f]{32}", "payment_id_invalid")
        text(self.provider_reference, r"[A-Za-z0-9_-]{1,128}", "provider_reference_invalid")
        text(self.event_id, r"[A-Za-z0-9:_-]{1,128}", "event_id_invalid")
        allowed = {
            "paypal": {"captured"},
            "monetico": {"authorized", "pending", "declined"},
            "payline": {"captured", "pending", "declined", "cancelled", "error"},
        }
        if self.state not in allowed.get(self.provider, set()):
            raise PaymentError("event_state_invalid")
        cents(self.amount_cents)
        if self.provider_transaction_id:
            text(self.provider_transaction_id, r"[A-Za-z0-9:_-]{1,50}", "provider_transaction_id_invalid")


class SandboxJournal:
    """Persistent, single-intent-per-booking sandbox ledger, without client PII.

    Switching provider, refunds and settlement are not yet supported. A browser
    redirect never calls _apply_verified. An authorization is NOT a capture.
    """
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.geteuid():
                raise PaymentError("private_database_required") from None
        else:
            os.close(fd)
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        """Create or migrate the sandbox ledger without reinterpreting history."""
        with contextlib.closing(sqlite3.connect(self.path, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=OFF")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS payment_intents(
              payment_id TEXT PRIMARY KEY,
              booking_hash TEXT NOT NULL UNIQUE,
              quote_hash TEXT NOT NULL,
              provider TEXT NOT NULL CHECK(provider IN ('paypal','monetico','payline')),
              environment TEXT NOT NULL CHECK(environment IN ('sandbox','production')),
              amount_cents INTEGER NOT NULL CHECK(typeof(amount_cents)='integer' AND amount_cents BETWEEN 1 AND 9000),
              currency TEXT NOT NULL CHECK(currency='EUR'),
              provider_reference TEXT NOT NULL DEFAULT '',
              state TEXT NOT NULL CHECK(state IN ('created','pending','declined','cancelled','error','authorized','captured')),
              created_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS payment_provider_reference
              ON payment_intents(provider,provider_reference) WHERE provider_reference<>'';
            CREATE TABLE IF NOT EXISTS payment_events(
              provider TEXT NOT NULL,
              event_hash TEXT NOT NULL,
              payment_id TEXT NOT NULL REFERENCES payment_intents(payment_id),
              evidence_hash TEXT NOT NULL,
              state TEXT NOT NULL,
              received_at TEXT NOT NULL,
              PRIMARY KEY(provider,event_hash)
            );
            CREATE TABLE IF NOT EXISTS payment_provider_transactions(
              payment_id TEXT PRIMARY KEY REFERENCES payment_intents(payment_id),
              provider TEXT NOT NULL,
              transaction_id TEXT NOT NULL UNIQUE,
              captured_amount_cents INTEGER NOT NULL CHECK(typeof(captured_amount_cents)='integer' AND captured_amount_cents BETWEEN 1 AND 9000),
              updated_at TEXT NOT NULL
            );
            """)
            sql = str(db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='payment_intents'"
            ).fetchone()["sql"] or "")
            needs_rebuild = (
                "'payline'" not in sql
                or "'cancelled'" not in sql
                or "'error'" not in sql
                or "'production'" not in sql
            )
            if needs_rebuild:
                provider_starts_exists = bool(db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='payment_provider_starts'"
                ).fetchone())
                if provider_starts_exists:
                    db.execute("ALTER TABLE payment_provider_starts RENAME TO payment_provider_starts_legacy")
                # Rebuild the complete FK family together. SQLite can rewrite FK
                # targets when a parent table is renamed; rebuilding children
                # prevents a legacy child from retaining a reference to the
                # temporary payment_intents_legacy table.
                db.executescript("""
                ALTER TABLE payment_events RENAME TO payment_events_legacy;
                ALTER TABLE payment_provider_transactions RENAME TO payment_provider_transactions_legacy;
                DROP INDEX IF EXISTS payment_provider_reference;
                ALTER TABLE payment_intents RENAME TO payment_intents_legacy;

                CREATE TABLE payment_intents(
                  payment_id TEXT PRIMARY KEY,
                  booking_hash TEXT NOT NULL UNIQUE,
                  quote_hash TEXT NOT NULL,
                  provider TEXT NOT NULL CHECK(provider IN ('paypal','monetico','payline')),
                  environment TEXT NOT NULL CHECK(environment IN ('sandbox','production')),
                  amount_cents INTEGER NOT NULL CHECK(typeof(amount_cents)='integer' AND amount_cents BETWEEN 1 AND 9000),
                  currency TEXT NOT NULL CHECK(currency='EUR'),
                  provider_reference TEXT NOT NULL DEFAULT '',
                  state TEXT NOT NULL CHECK(state IN ('created','pending','declined','cancelled','error','authorized','captured')),
                  created_at TEXT NOT NULL
                );
                INSERT INTO payment_intents
                  SELECT payment_id,booking_hash,quote_hash,provider,environment,amount_cents,
                         currency,provider_reference,state,created_at
                  FROM payment_intents_legacy;

                CREATE UNIQUE INDEX payment_provider_reference
                  ON payment_intents(provider,provider_reference) WHERE provider_reference<>'';

                CREATE TABLE payment_events(
                  provider TEXT NOT NULL,
                  event_hash TEXT NOT NULL,
                  payment_id TEXT NOT NULL REFERENCES payment_intents(payment_id),
                  evidence_hash TEXT NOT NULL,
                  state TEXT NOT NULL,
                  received_at TEXT NOT NULL,
                  PRIMARY KEY(provider,event_hash)
                );
                INSERT INTO payment_events
                  SELECT provider,event_hash,payment_id,evidence_hash,state,received_at
                  FROM payment_events_legacy;

                CREATE TABLE payment_provider_transactions(
                  payment_id TEXT PRIMARY KEY REFERENCES payment_intents(payment_id),
                  provider TEXT NOT NULL,
                  transaction_id TEXT NOT NULL UNIQUE,
                  captured_amount_cents INTEGER NOT NULL CHECK(typeof(captured_amount_cents)='integer' AND captured_amount_cents BETWEEN 1 AND 9000),
                  updated_at TEXT NOT NULL
                );
                INSERT INTO payment_provider_transactions
                  SELECT payment_id,provider,transaction_id,captured_amount_cents,updated_at
                  FROM payment_provider_transactions_legacy;

                DROP TABLE payment_events_legacy;
                DROP TABLE payment_provider_transactions_legacy;
                DROP TABLE payment_intents_legacy;
                """)
                if provider_starts_exists:
                    db.executescript("""
                    CREATE TABLE payment_provider_starts(
                      payment_id TEXT PRIMARY KEY REFERENCES payment_intents(payment_id),
                      provider TEXT NOT NULL CHECK(provider='payline'),
                      state TEXT NOT NULL CHECK(state IN ('attempting','ready','indeterminate')),
                      provider_reference TEXT NOT NULL DEFAULT '',
                      redirect_url TEXT NOT NULL DEFAULT '',
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL
                    );
                    INSERT INTO payment_provider_starts
                      SELECT payment_id,provider,state,provider_reference,redirect_url,created_at,updated_at
                      FROM payment_provider_starts_legacy;
                    DROP TABLE payment_provider_starts_legacy;
                    """)
            violations = db.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise PaymentError("payment_schema_migration_failed")
            db.commit()
            db.execute("PRAGMA foreign_keys=ON")

    @contextlib.contextmanager
    def _connect(self):
        with contextlib.closing(sqlite3.connect(self.path, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db

    @staticmethod
    def _intent(row) -> Intent:
        if row is None:
            raise PaymentError("intent_not_found")
        return Intent(**{key: row[key] for key in Intent.__dataclass_fields__})

    def get(self, payment_id: str) -> Intent:
        text(payment_id, r"[0-9a-f]{32}", "payment_id_invalid")
        with self._connect() as db:
            return self._intent(db.execute("SELECT * FROM payment_intents WHERE payment_id=?", (payment_id,)).fetchone())

    def get_by_provider_reference(self, provider: str, provider_reference: str) -> Intent:
        if provider not in {"paypal", "monetico", "payline"}:
            raise PaymentError("provider_invalid")
        text(provider_reference, r"[A-Za-z0-9_-]{1,128}", "provider_reference_invalid")
        with self._connect() as db:
            return self._intent(db.execute(
                "SELECT * FROM payment_intents WHERE provider=? AND provider_reference=?",
                (provider, provider_reference),
            ).fetchone())

    def provider_transaction(self, payment_id: str) -> dict:
        text(payment_id, r"[0-9a-f]{32}", "payment_id_invalid")
        with self._connect() as db:
            row=db.execute(
                "SELECT provider,transaction_id,captured_amount_cents,updated_at FROM payment_provider_transactions WHERE payment_id=?",
                (payment_id,),
            ).fetchone()
        if row is None:
            raise PaymentError("provider_transaction_not_found")
        return {
            "provider":str(row["provider"]),
            "transactionId":str(row["transaction_id"]),
            "capturedAmountCents":int(row["captured_amount_cents"]),
            "updatedAt":str(row["updated_at"]),
        }

    def create(self, quote: Quote, provider: str, environment: str = "sandbox") -> Intent:
        if not isinstance(quote, Quote) or provider not in {"paypal", "monetico", "payline"}:
            raise PaymentError("quote_or_provider_invalid")
        if environment not in ENVIRONMENTS or (environment == "production" and provider != "payline"):
            raise PaymentError("quote_or_provider_invalid")
        binding = digest(["mercure-rdv", quote.booking_reference])
        quote_hash = digest([quote.service, quote.amount_cents, quote.terms_hash])
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM payment_intents WHERE booking_hash=?", (binding,)).fetchone()
            if row:
                if (row["provider"] != provider or row["quote_hash"] != quote_hash
                        or row["environment"] != environment):
                    raise PaymentError("booking_payment_conflict")
                return self._intent(row)
            payment_id = uuid.uuid4().hex
            db.execute("""INSERT INTO payment_intents
                (payment_id,booking_hash,quote_hash,provider,environment,amount_cents,currency,state,created_at)
                VALUES(?,?,?,?,?,?,'EUR','created',?)""",
                (payment_id, binding, quote_hash, provider, environment, quote.amount_cents, stamp()))
            return self._intent(db.execute("SELECT * FROM payment_intents WHERE payment_id=?", (payment_id,)).fetchone())

    def bind_provider(self, payment_id: str, provider_reference: str) -> Intent:
        text(provider_reference, r"[A-Za-z0-9_-]{1,128}", "provider_reference_invalid")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._intent(db.execute("SELECT * FROM payment_intents WHERE payment_id=?", (payment_id,)).fetchone())
            if current.provider_reference and current.provider_reference != provider_reference:
                raise PaymentError("provider_reference_conflict")
            if current.provider == "monetico" and provider_reference != current.payment_id:
                raise PaymentError("provider_reference_conflict")
            try:
                db.execute("UPDATE payment_intents SET provider_reference=? WHERE payment_id=?", (provider_reference, payment_id))
            except sqlite3.IntegrityError:
                raise PaymentError("provider_reference_conflict") from None
        return self.get(payment_id)

    def _apply_verified(self, event: VerifiedEvent) -> Intent:
        if not isinstance(event, VerifiedEvent):
            raise PaymentError("verified_event_required")
        evidence = digest([event.payment_id, event.provider, event.provider_reference, event.state, event.amount_cents, event.provider_transaction_id])
        event_hash = digest([event.provider, event.event_id])
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM payment_intents WHERE payment_id=?", (event.payment_id,)).fetchone()
            current = self._intent(row)
            if (current.provider, current.provider_reference, current.amount_cents) != (event.provider, event.provider_reference, event.amount_cents):
                raise PaymentError("event_binding_mismatch")
            # Only a verified capture is authoritative transaction evidence.
            # Pending/declined attempts may legitimately be followed by a new
            # provider transaction during a retry and must not reserve the
            # payment_id -> transaction_id mapping.
            if event.state == "captured":
                if not event.provider_transaction_id:
                    raise PaymentError("provider_transaction_required")
                existing_tx=db.execute(
                    "SELECT payment_id,provider,transaction_id,captured_amount_cents FROM payment_provider_transactions WHERE payment_id=? OR transaction_id=?",
                    (event.payment_id,event.provider_transaction_id),
                ).fetchall()
                for tx in existing_tx:
                    if (
                        str(tx["payment_id"]) != event.payment_id
                        or str(tx["provider"]) != event.provider
                        or str(tx["transaction_id"]) != event.provider_transaction_id
                        or int(tx["captured_amount_cents"]) != event.amount_cents
                    ):
                        raise PaymentError("provider_transaction_conflict")
                if not existing_tx:
                    db.execute(
                        "INSERT INTO payment_provider_transactions(payment_id,provider,transaction_id,captured_amount_cents,updated_at) VALUES(?,?,?,?,?)",
                        (event.payment_id,event.provider,event.provider_transaction_id,event.amount_cents,stamp()),
                    )
            previous = db.execute("SELECT evidence_hash FROM payment_events WHERE provider=? AND event_hash=?", (event.provider, event_hash)).fetchone()
            if previous:
                if previous["evidence_hash"] != evidence:
                    raise PaymentError("event_replay_conflict")
                return current
            # Declines can be followed by success; delayed failures cannot erase it.
            rank = {
                "created": 0,
                "pending": 1,
                "declined": 1,
                "cancelled": 1,
                "error": 1,
                "authorized": 2,
                "captured": 3,
            }
            state = event.state if rank[event.state] >= rank[current.state] else current.state
            db.execute("INSERT INTO payment_events VALUES(?,?,?,?,?,?)", (event.provider, event_hash, event.payment_id, evidence, event.state, stamp()))
            db.execute("UPDATE payment_intents SET state=? WHERE payment_id=?", (state, event.payment_id))
        return self.get(event.payment_id)


def capability() -> dict:
    return {
        "environment": "sandbox", "providers": ["paypal", "monetico", "payline"],
        "livePaymentsEnabled": False, "checkoutBound": False,
        "httpCallbacksBound": False, "refundsBound": False,
        "merchantSecretsConfigured": False,
    }
