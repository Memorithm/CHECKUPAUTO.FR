"""Authenticated customer contact-request intake.

A contact request is accepted only from an authenticated customer session.
Customer identity is derived from the verified customer account rather than
free-form contact fields. The workflow never invokes payment, refund, booking
or provider APIs; refund-related messages remain manual correspondence only.
"""
from __future__ import annotations

import datetime as dt
import html
import os
import re
import secrets
import sqlite3
from pathlib import Path

CATEGORIES = {
    "general": "Question générale",
    "booking": "Réservation",
    "payment": "Paiement",
    "refund_request": "Demande concernant un remboursement",
}
RETENTION_DAYS = 180


def db_path() -> Path:
    return Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData")) / "contact-requests.sqlite3"


def _text(value, *, minimum: int, maximum: int, code: str) -> str:
    if not isinstance(value, str):
        raise ValueError(code)
    value = " ".join(value.strip().split())
    if not minimum <= len(value) <= maximum:
        raise ValueError(code)
    return value


def _message(value) -> str:
    if not isinstance(value, str):
        raise ValueError("contact_message_invalid")
    value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not 10 <= len(value) <= 3000:
        raise ValueError("contact_message_invalid")
    return value


def _email(value) -> str:
    value = _text(value, minimum=5, maximum=254, code="contact_email_invalid").lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("contact_email_invalid")
    return value


def _phone(value) -> str:
    if value in (None, ""):
        return ""
    value = _text(value, minimum=6, maximum=32, code="contact_phone_invalid")
    if not re.fullmatch(r"[+0-9(). /-]{6,32}", value):
        raise ValueError("contact_phone_invalid")
    return value


def _customer_identity(customer: object) -> tuple[str, str, str, str]:
    if not isinstance(customer, dict):
        raise ValueError("contact_customer_required")
    account_id = _text(
        customer.get("accountId"), minimum=8, maximum=80, code="contact_customer_required"
    )
    name = _text(
        customer.get("displayName"), minimum=2, maximum=120, code="contact_customer_required"
    )
    email = _email(customer.get("email"))
    phone = _phone(customer.get("phone"))
    return account_id, name, email, phone


def _connect(path: Path | None = None):
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS contact_requests(
      request_id TEXT PRIMARY KEY,
      category TEXT NOT NULL CHECK(category IN ('general','booking','payment','refund_request')),
      name TEXT NOT NULL,
      email TEXT NOT NULL,
      phone TEXT NOT NULL DEFAULT '',
      message TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
      created_at TEXT NOT NULL
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS contact_requests_created ON contact_requests(created_at)")
    db.commit()
    return db


def submit(payload: dict, *, path: Path | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("contact_payload_invalid")
    allowed = {"category", "name", "email", "phone", "message", "website", "consent"}
    if set(payload) - allowed:
        raise ValueError("contact_payload_invalid")
    if str(payload.get("website") or ""):
        raise ValueError("contact_payload_invalid")
    if payload.get("consent") not in {"yes", True}:
        raise ValueError("contact_consent_required")
    category = str(payload.get("category") or "")
    if category not in CATEGORIES:
        raise ValueError("contact_category_invalid")
    name = _text(payload.get("name"), minimum=2, maximum=120, code="contact_name_invalid")
    email = _email(payload.get("email"))
    phone = _phone(payload.get("phone"))
    message = _message(payload.get("message"))
    request_id = secrets.token_hex(16)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
    db = _connect(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM contact_requests WHERE created_at < ?", (cutoff,))
        db.execute(
            """INSERT INTO contact_requests(
                 request_id,category,name,email,phone,message,status,created_at
               ) VALUES(?,?,?,?,?,?,'open',?)""",
            (request_id, category, name, email, phone, message, now),
        )
        db.commit()
    finally:
        db.close()
    return {
        "requestId": request_id,
        "category": category,
        "createdAt": now,
        "paymentActionTriggered": False,
        "refundActionTriggered": False,
    }


def privacy_snapshot(email: object, *, path: Path | None = None) -> dict:
    """Return every retained contact row for one exact normalized e-mail subject."""
    normalized=_email(email)
    db=_connect(path)
    try:
        rows=db.execute(
            """SELECT request_id,category,name,email,phone,message,status,created_at
               FROM contact_requests WHERE email=? ORDER BY created_at,request_id""",
            (normalized,),
        ).fetchall()
    finally:
        db.close()
    return {
        "subjectKind":"email",
        "requestCount":len(rows),
        "requests":[
            {
                "requestId":str(row["request_id"]),
                "category":str(row["category"]),
                "name":str(row["name"]),
                "email":str(row["email"]),
                "phone":str(row["phone"]),
                "message":str(row["message"]),
                "status":str(row["status"]),
                "createdAt":str(row["created_at"]),
            }
            for row in rows
        ],
        "retentionDays":RETENTION_DAYS,
    }


def erase_subject(email: object, *, path: Path | None = None) -> dict:
    """Physically erase all contact requests for one exact normalized e-mail."""
    normalized=_email(email)
    db=_connect(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        before=int(db.execute(
            "SELECT COUNT(*) FROM contact_requests WHERE email=?",
            (normalized,),
        ).fetchone()[0])
        db.execute("DELETE FROM contact_requests WHERE email=?",(normalized,))
        remaining=int(db.execute(
            "SELECT COUNT(*) FROM contact_requests WHERE email=?",
            (normalized,),
        ).fetchone()[0])
        if remaining:
            db.rollback()
            raise RuntimeError("contact_subject_erasure_incomplete")
        db.commit()
    finally:
        db.close()
    return {
        "ok":True,
        "removedCount":before,
        "remainingCount":0,
        "subjectKind":"email",
    }


def render_form() -> bytes:
    options = "".join(
        f'<option value="{html.escape(key)}">{html.escape(label)}</option>'
        for key, label in CATEGORIES.items()
    )
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,follow"><title>Contact | Checkup Auto</title>
<style>
:root{{--paper:#f6f7f2;--ink:#213b30;--muted:#747d71;--line:#d9dfd3;--green:#1f5443}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:Arial,Helvetica,sans-serif}}
main{{width:min(860px,calc(100% - 32px));margin:0 auto;padding:42px 0 64px}}a{{color:inherit}}.brand{{font-weight:700;text-decoration:none}}
.card{{margin-top:28px;background:#fff;border:1px solid var(--line);padding:clamp(24px,5vw,48px);box-shadow:0 24px 70px rgba(31,84,67,.07)}}
.eyebrow{{font:10px Consolas,monospace;letter-spacing:.13em;color:var(--green)}}h1{{font:400 clamp(38px,7vw,68px)/1 Georgia,serif;letter-spacing:-.04em;margin:14px 0 18px}}
p{{color:var(--muted);line-height:1.7}}form{{display:grid;gap:18px;margin-top:28px}}label{{display:grid;gap:8px;font-size:12px;font-weight:700}}
input,select,textarea{{width:100%;border:1px solid var(--line);background:#fbfcfa;padding:13px 14px;font:14px Arial,sans-serif;color:var(--ink)}}textarea{{min-height:160px;resize:vertical}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.consent{{display:flex;gap:10px;align-items:flex-start;font-weight:400;line-height:1.5}}.consent input{{width:auto;margin-top:3px}}
button{{border:0;background:var(--green);color:#fff;padding:15px 20px;font-weight:700;cursor:pointer;justify-self:start}}.notice{{padding:14px 16px;background:#eef3ed;border-left:3px solid var(--green);font-size:12px}}
.hp{{position:absolute!important;left:-10000px!important;width:1px!important;height:1px!important;overflow:hidden!important}}
@media(max-width:640px){{.row{{grid-template-columns:1fr}}}}
</style></head><body><main><a class="brand" href="/">✓ CHECKUP AUTO</a><section class="card">
<div class="eyebrow">CONTACT / TRAITEMENT MANUEL</div><h1>Nous contacter.</h1>
<p>Utilisez ce formulaire pour une question sur une réservation, un paiement ou toute autre demande.</p>
<div class="notice"><strong>Demande concernant un remboursement :</strong> ce formulaire ouvre uniquement une demande de contact. Il ne déclenche aucun remboursement ni aucune opération Payline. La demande est étudiée séparément.</div>
<form method="post" action="/contact" autocomplete="on">
<div class="row"><label>Nom<input name="name" maxlength="120" required autocomplete="name"></label><label>E-mail<input name="email" type="email" maxlength="254" required autocomplete="email"></label></div>
<div class="row"><label>Téléphone (facultatif)<input name="phone" maxlength="32" autocomplete="tel"></label><label>Objet<select name="category" required>{options}</select></label></div>
<label>Votre message<textarea name="message" maxlength="3000" required></textarea></label>
<label class="hp" aria-hidden="true">Site web<input name="website" tabindex="-1" autocomplete="off"></label>
<label class="consent"><input type="checkbox" name="consent" value="yes" required><span>J’accepte que ces informations soient utilisées pour traiter ma demande. Elles ne sont pas utilisées pour déclencher une opération bancaire.</span></label>
<button type="submit">Envoyer ma demande →</button>
</form></section></main></body></html>""".encode("utf-8")


def render_confirmation(result: dict) -> bytes:
    request_id = html.escape(str(result.get("requestId") or ""))
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>Demande enregistrée | Checkup Auto</title><style>
body{{margin:0;background:#f6f7f2;color:#213b30;font-family:Arial,sans-serif}}main{{max-width:760px;margin:auto;padding:64px 24px}}
.card{{background:#fff;border:1px solid #d9dfd3;padding:42px}}h1{{font:400 48px/1 Georgia,serif}}p{{line-height:1.7;color:#66776e}}code{{font-size:12px}}a{{color:#1f5443}}
</style></head><body><main><div class="card"><h1>Demande enregistrée.</h1>
<p>Votre demande a été transmise pour traitement manuel. Aucune opération bancaire ni aucun remboursement n’a été déclenché.</p>
<p>Référence : <code>{request_id}</code></p><p><a href="/">Revenir à Checkup Auto →</a></p></div></main></body></html>""".encode("utf-8")
