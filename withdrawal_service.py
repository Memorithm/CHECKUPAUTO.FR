from __future__ import annotations

import datetime
import hashlib
import html
import json
import re
import uuid
from pathlib import Path

import compliance_store
import notification_broker as notifications


STANDARD_WITHDRAWAL_DAYS = 14
RECEIPT_CATEGORY = "withdrawal_receipt"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _now_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _text(value: object, name: str, limit: int, *, required: bool = False) -> str:
    value = str(value or "").strip()
    if required and not value:
        raise ValueError(f"{name} requis")
    if len(value) > limit:
        raise ValueError(f"{name} trop long")
    return value


def _email(value: object) -> str:
    value = _text(value, "receiptEmail", 254, required=True).lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
        raise ValueError("adresse e-mail invalide")
    return value


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def init_db(db_path: Path | str | None = None) -> None:
    compliance_store.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS withdrawal_requests(
              request_id TEXT PRIMARY KEY,
              contract_ref TEXT NOT NULL,
              contract_ref_hash TEXT NOT NULL,
              first_name TEXT NOT NULL,
              last_name TEXT NOT NULL,
              receipt_email TEXT NOT NULL,
              receipt_email_hash TEXT NOT NULL,
              submitted_at TEXT NOT NULL,
              declaration_hash TEXT NOT NULL,
              contract_match INTEGER NOT NULL,
              contract_accepted_at TEXT NOT NULL DEFAULT '',
              standard_deadline_at TEXT NOT NULL DEFAULT '',
              standard_deadline_passed INTEGER NOT NULL DEFAULT 0,
              immediate_performance_requested INTEGER NOT NULL DEFAULT 0,
              receipt_status TEXT NOT NULL DEFAULT 'pending',
              receipt_attempts INTEGER NOT NULL DEFAULT 0,
              receipt_sent_at TEXT NOT NULL DEFAULT '',
              receipt_last_error TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_withdrawal_contract
              ON withdrawal_requests(contract_ref_hash,submitted_at);
            CREATE INDEX IF NOT EXISTS idx_withdrawal_receipt
              ON withdrawal_requests(receipt_status,submitted_at);
            """
        )


def _contract_receipt(contract_ref: str, db_path: Path | str | None = None):
    compliance_store.init_db(db_path)
    with compliance_store.connect(db_path) as db:
        return db.execute(
            """SELECT contract_ref,accepted_at,immediate_performance
               FROM consent_receipts
               WHERE contract_ref=? AND purpose='contract_terms' AND document_type='terms'
               ORDER BY accepted_at DESC LIMIT 1""",
            (contract_ref,),
        ).fetchone()


def _public_row(row) -> dict:
    return {
        "id": row["request_id"],
        "submittedAt": row["submitted_at"],
        "contractMatched": bool(row["contract_match"]),
        "standardDeadlineAt": row["standard_deadline_at"],
        "standardDeadlinePassed": bool(row["standard_deadline_passed"]),
        "immediatePerformanceRequested": bool(row["immediate_performance_requested"]),
        "receiptStatus": row["receipt_status"],
        "receiptSentAt": row["receipt_sent_at"],
        "manualReviewRequired": not bool(row["contract_match"]),
    }


def _row(request_id: str, db_path: Path | str | None = None):
    request_id = _text(request_id, "requestId", 32, required=True).lower()
    if not re.fullmatch(r"[0-9a-f]{32}", request_id):
        raise ValueError("identifiant de rétractation invalide")
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        row = db.execute(
            "SELECT * FROM withdrawal_requests WHERE request_id=?",
            (request_id,),
        ).fetchone()
    if row is None:
        raise LookupError("demande de rétractation introuvable")
    return row


def submit(payload: dict, db_path: Path | str | None = None, *, dispatch: bool = True) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("déclaration de rétractation invalide")
    first_name = _text(payload.get("firstName"), "prénom", 120, required=True)
    last_name = _text(payload.get("lastName"), "nom", 120, required=True)
    contract_ref = _text(payload.get("contractRef"), "référence du contrat", 200, required=True)
    receipt_email = _email(payload.get("receiptEmail"))
    if payload.get("confirm") is not True:
        raise ValueError("confirmation de rétractation requise")

    matched = _contract_receipt(contract_ref, db_path)
    accepted_at = ""
    deadline_at = ""
    deadline_passed = False
    immediate = False
    if matched:
        accepted_at = str(matched["accepted_at"] or "")
        immediate = bool(matched["immediate_performance"])
        try:
            accepted = datetime.datetime.fromisoformat(accepted_at.replace("Z", "+00:00"))
            if accepted.tzinfo is None:
                accepted = accepted.replace(tzinfo=datetime.timezone.utc)
            deadline = accepted + datetime.timedelta(days=STANDARD_WITHDRAWAL_DAYS)
            deadline_at = deadline.isoformat(timespec="seconds")
            deadline_passed = _now() > deadline
        except (TypeError, ValueError):
            # Never reject a consumer declaration because historical evidence is malformed.
            deadline_at = ""
            deadline_passed = False

    submitted_at = _now_iso()
    declaration = {
        "firstName": first_name,
        "lastName": last_name,
        "contractRef": contract_ref,
        "receiptEmail": receipt_email,
        "submittedAt": submitted_at,
    }
    declaration_hash = _hash(
        json.dumps(declaration, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    request_id = uuid.uuid4().hex
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        db.execute(
            """INSERT INTO withdrawal_requests(
              request_id,contract_ref,contract_ref_hash,first_name,last_name,
              receipt_email,receipt_email_hash,submitted_at,declaration_hash,
              contract_match,contract_accepted_at,standard_deadline_at,
              standard_deadline_passed,immediate_performance_requested
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                request_id,
                contract_ref,
                _hash(contract_ref),
                first_name,
                last_name,
                receipt_email,
                _hash(receipt_email),
                submitted_at,
                declaration_hash,
                int(bool(matched)),
                accepted_at,
                deadline_at,
                int(deadline_passed),
                int(immediate),
            ),
        )

    delivery = None
    if dispatch:
        try:
            delivery = dispatch_receipt(request_id, db_path)
        except Exception:
            # The withdrawal declaration remains effective and retryable even if
            # the acknowledgement transport is temporarily unavailable.
            delivery = _public_row(_row(request_id, db_path))
    result = _public_row(_row(request_id, db_path))
    result["receiptDelivery"] = delivery
    return result


def _receipt_content(row) -> tuple[str, str, str]:
    request_id = row["request_id"]
    submitted_at = row["submitted_at"]
    contract_ref = row["contract_ref"]
    first_name = row["first_name"]
    last_name = row["last_name"]
    subject = f"Accusé de réception de votre rétractation — {request_id[:8]}"
    text = (
        "Checkup Auto — Accusé de réception de rétractation\n\n"
        f"Référence de la demande : {request_id}\n"
        f"Date et heure d'envoi : {submitted_at}\n"
        f"Nom : {last_name}\n"
        f"Prénom : {first_name}\n"
        f"Référence du contrat / rendez-vous : {contract_ref}\n\n"
        "Votre déclaration de rétractation a été enregistrée par Checkup Auto. "
        "Cet accusé reprend le contenu essentiel de votre déclaration et son horodatage.\n"
    )
    rich = (
        "<h1>Accusé de réception de votre rétractation</h1>"
        f"<p><strong>Référence :</strong> {html.escape(request_id)}</p>"
        f"<p><strong>Date et heure d'envoi :</strong> {html.escape(submitted_at)}</p>"
        f"<p><strong>Nom :</strong> {html.escape(last_name)}</p>"
        f"<p><strong>Prénom :</strong> {html.escape(first_name)}</p>"
        f"<p><strong>Contrat / rendez-vous :</strong> {html.escape(contract_ref)}</p>"
        "<p>Votre déclaration de rétractation a été enregistrée par Checkup Auto.</p>"
    )
    return subject, text, rich


def dispatch_receipt(request_id: str, db_path: Path | str | None = None) -> dict:
    row = _row(request_id, db_path)
    if row["receipt_status"] == "sent":
        return _public_row(row)
    recipient = str(row["receipt_email"] or "")
    if not recipient:
        raise RuntimeError("adresse d'accusé indisponible")

    subject, text, rich = _receipt_content(row)
    try:
        delivery = notifications.send_email(
            recipient,
            subject,
            text,
            rich,
            category=RECEIPT_CATEGORY,
            reference=row["request_id"],
        )
        deferred = bool(delivery.get("deferred") or delivery.get("inFlight"))
        sent = bool(delivery.get("status") == "sent" or delivery.get("sentAt") or delivery.get("alreadySent"))
        if sent:
            state = "sent"
        elif deferred:
            state = "deferred"
        else:
            state = "pending"
        with compliance_store.connect(db_path) as db:
            db.execute(
                """UPDATE withdrawal_requests
                   SET receipt_status=?,receipt_attempts=receipt_attempts+1,
                       receipt_sent_at=?,receipt_last_error='',
                       receipt_email=CASE WHEN ?='sent' THEN '' ELSE receipt_email END
                   WHERE request_id=?""",
                (
                    state,
                    str(delivery.get("sentAt") or "") if sent else "",
                    state,
                    row["request_id"],
                ),
            )
    except Exception as exc:
        diagnostic = notifications.safe_delivery_error(exc)
        with compliance_store.connect(db_path) as db:
            db.execute(
                """UPDATE withdrawal_requests
                   SET receipt_status='failed',receipt_attempts=receipt_attempts+1,
                       receipt_last_error=?
                   WHERE request_id=?""",
                (diagnostic, row["request_id"]),
            )
        raise
    return _public_row(_row(row["request_id"], db_path))


def dispatch_pending(db_path: Path | str | None = None, limit: int = 25) -> dict:
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        rows = db.execute(
            """SELECT request_id FROM withdrawal_requests
               WHERE receipt_status IN ('pending','deferred','failed') AND receipt_email<>''
               ORDER BY submitted_at ASC LIMIT ?""",
            (max(1, min(int(limit), 100)),),
        ).fetchall()
    sent = deferred = failed = 0
    for row in rows:
        try:
            result = dispatch_receipt(row["request_id"], db_path)
            if result["receiptStatus"] == "sent":
                sent += 1
            else:
                deferred += 1
        except Exception:
            failed += 1
    return {
        "ok": failed == 0,
        "processed": len(rows),
        "sent": sent,
        "deferred": deferred,
        "failed": failed,
    }


def status(db_path: Path | str | None = None) -> dict:
    init_db(db_path)
    with compliance_store.connect(db_path) as db:
        row = db.execute(
            """SELECT COUNT(*) total,
                      SUM(CASE WHEN receipt_status='sent' THEN 1 ELSE 0 END) sent,
                      SUM(CASE WHEN receipt_status<>'sent' THEN 1 ELSE 0 END) pending,
                      SUM(CASE WHEN contract_match=0 THEN 1 ELSE 0 END) manual_match,
                      SUM(CASE WHEN standard_deadline_passed=1 THEN 1 ELSE 0 END) deadline_passed
               FROM withdrawal_requests"""
        ).fetchone()
    return {
        "bound": True,
        "path": "/retractation",
        "confirmationLabel": "Confirmer la rétractation",
        "directlyAccessible": True,
        "acknowledgementOnDurableMedium": True,
        "totalRequests": int(row["total"] or 0),
        "sentReceipts": int(row["sent"] or 0),
        "pendingReceipts": int(row["pending"] or 0),
        "manualMatchRequired": int(row["manual_match"] or 0),
        "standardDeadlinePassed": int(row["deadline_passed"] or 0),
    }


def render_page(
    document: dict | None,
    *,
    canonical_origin: str,
    indexing_enabled: bool = False,
) -> bytes:
    title = "Rétractation"
    body = ""
    version = ""
    published = ""
    if document:
        title = str(document.get("title") or title)
        version = str(document.get("version") or "")
        published = str(document.get("publishedAt") or "")
        chunks = []
        for paragraph in str(document.get("body") or "").split("\n\n"):
            paragraph = paragraph.strip()
            if paragraph:
                chunks.append("<p>" + html.escape(paragraph).replace("\n", "<br>") + "</p>")
        body = "".join(chunks)
    meta = (
        f'<div class="meta">Version {html.escape(version)} · publiée {html.escape(published)}</div>'
        if version else ""
    )
    canonical = canonical_origin.rstrip("/") + "/retractation"
    robots = "index,follow" if indexing_enabled else "noindex,nofollow"
    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="{robots}"><link rel="canonical" href="{html.escape(canonical, quote=True)}"><title>{html.escape(title)} | Checkup Auto</title><style>body{{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#f6f7f3;color:#17372b}}main{{max-width:860px;margin:auto;padding:42px 22px 80px}}a{{color:#1f5845}}h1{{font-size:clamp(36px,6vw,64px);letter-spacing:-.04em}}p{{line-height:1.65}}.meta,.box{{background:#fff;border:1px solid #dbe1d8;border-radius:16px;padding:18px;margin:20px 0}}label{{display:block;margin:16px 0;font-weight:650}}input{{box-sizing:border-box;width:100%;padding:12px;border:1px solid #bdc8c0;border-radius:10px;margin-top:6px;font:inherit}}button{{padding:14px 20px;border:0;border-radius:999px;background:#17372b;color:white;font:inherit;font-weight:750;cursor:pointer}}.notice{{font-size:14px;color:#52665b}}</style></head><body><main><a href="/">← Checkup Auto</a><h1>{html.escape(title)}</h1>{meta}{body}<section class="box" aria-labelledby="withdrawal-action"><h2 id="withdrawal-action">Renoncer au contrat ici</h2><p>Cette fonctionnalité vous permet d'adresser directement votre déclaration de rétractation à Checkup Auto. Un accusé de réception horodaté est envoyé à l'adresse e-mail indiquée.</p><form method="post" action="/retractation"><label>Prénom<input name="firstName" autocomplete="given-name" maxlength="120" required></label><label>Nom<input name="lastName" autocomplete="family-name" maxlength="120" required></label><label>Référence du contrat ou du rendez-vous<input name="contractRef" maxlength="200" required></label><label>Adresse e-mail pour recevoir l'accusé<input name="receiptEmail" type="email" autocomplete="email" maxlength="254" required></label><p class="notice">En confirmant, vous demandez la rétractation du contrat identifié ci-dessus. La demande est enregistrée même si son rapprochement avec le rendez-vous nécessite ensuite une vérification manuelle.</p><button type="submit" name="confirm" value="yes">Confirmer la rétractation</button></form></section></main></body></html>'''.encode("utf-8")


def render_confirmation(result: dict, *, canonical_origin: str) -> bytes:
    delivery = str(result.get("receiptStatus") or "pending")
    if delivery == "sent":
        delivery_text = "L'accusé de réception a été envoyé à l'adresse indiquée."
    else:
        delivery_text = "Votre déclaration est enregistrée. L'envoi de l'accusé sera retenté automatiquement."
    manual = (
        "<p>La référence n'a pas encore été rapprochée automatiquement ; la demande reste enregistrée pour traitement.</p>"
        if result.get("manualReviewRequired") else ""
    )
    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>Rétractation enregistrée | Checkup Auto</title><style>body{{font-family:system-ui;margin:0;background:#f6f7f3;color:#17372b}}main{{max-width:720px;margin:auto;padding:54px 22px}}.receipt{{background:white;border:1px solid #dbe1d8;border-radius:18px;padding:24px}}p{{line-height:1.65}}a{{color:#1f5845}}</style></head><body><main><div class="receipt"><h1>Rétractation enregistrée</h1><p><strong>Référence de la demande :</strong> {html.escape(str(result.get("id") or ""))}</p><p><strong>Date et heure :</strong> {html.escape(str(result.get("submittedAt") or ""))}</p><p>{html.escape(delivery_text)}</p>{manual}<p><a href="/">Retour à Checkup Auto</a></p></div></main></body></html>'''.encode("utf-8")
