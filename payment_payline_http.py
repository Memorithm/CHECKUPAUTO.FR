"""Public Payline sandbox return/notification routes.

Every provider signal is treated as a trigger to reread the transaction from
Payline over authenticated TLS. Browser query strings never mutate payment state.
"""
from __future__ import annotations

import html
import json
import os
import re
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import payment_payline as payline
import payment_checkout as checkout
import payment_payline_private as private_config
from payment_core import PaymentError, SandboxJournal

RETURN_ROUTE = "/payment/payline/return"
CANCEL_ROUTE = "/payment/payline/cancel"
NOTIFY_ROUTE = "/api/payments/payline/notify"
START_ROUTE = "/api/payments/payline/start"
CHECKOUT_ROUTE = "/payment/payline/checkout"


def journal_path() -> Path:
    data_dir = Path(os.environ.get("CYBERCHECK_DATA_DIR", "/root/CyberCheckData"))
    return data_dir / "payments.sqlite3"


def _journal_existing() -> SandboxJournal:
    path = journal_path()
    if not path.is_file():
        raise PaymentError("intent_not_found")
    return SandboxJournal(path)


def _single(query: str, name: str, pattern: str, code: str) -> str:
    values = parse_qs(query, keep_blank_values=True).get(name, [])
    if len(values) != 1 or not re.fullmatch(pattern, values[0]):
        raise PaymentError(code)
    return values[0]


def _apply_by_payment_id(payment_id: str):
    store = _journal_existing()
    intent = store.get(payment_id)
    if intent.provider != "payline" or not intent.provider_reference:
        raise PaymentError("payline_bound_intent_required")
    config = private_config.load()
    event = payline.refresh(intent, config)
    return store._apply_verified(event)


def _apply_by_token(token: str):
    store = _journal_existing()
    intent = store.get_by_provider_reference("payline", token)
    config = private_config.load()
    event = payline.refresh(intent, config)
    return store._apply_verified(event)


def _page(title: str, message: str, state: str) -> bytes:
    safe_title = html.escape(title)
    safe_message = html.escape(message)
    safe_state = html.escape(state)
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>{safe_title} | Checkup Auto</title>
<style>body{{font-family:system-ui;margin:0;background:#f6f7f3;color:#17372b}}main{{max-width:720px;margin:auto;padding:72px 24px}}
a{{color:#1f5845}}.card{{background:#fff;border:1px solid #dbe1d8;border-radius:18px;padding:32px}}
small{{letter-spacing:.12em;text-transform:uppercase;color:#66776e}}h1{{font-size:clamp(34px,7vw,64px);letter-spacing:-.04em}}
p{{line-height:1.65;color:#40584d}}</style></head>
<body><main><a href="/">← Checkup Auto</a><div class="card"><small>PAIEMENT · {safe_state}</small>
<h1>{safe_title}</h1><p>{safe_message}</p></div></main></body></html>""".encode("utf-8")


def _browser_result(handler, query: str) -> bool:
    try:
        payment_id = _single(query, "paymentId", r"[0-9a-f]{32}", "payment_id_invalid")
        intent = _apply_by_payment_id(payment_id)
    except private_config.PaylinePrivateConfigurationError:
        handler.send_bytes(
            _page("Paiement en cours de vérification",
                  "La confirmation bancaire est temporairement indisponible. Aucun succès n’est enregistré sans vérification auprès du prestataire.",
                  "VÉRIFICATION"),
            "text/html; charset=utf-8", 503, "no-store",
            {"X-Robots-Tag": "noindex, nofollow, noarchive", "Retry-After": "30"},
        )
        return True
    except PaymentError:
        handler.send_bytes(
            _page("Paiement non vérifiable",
                  "Nous ne pouvons pas confirmer ce paiement depuis cette page. Aucun statut bancaire n’a été accepté depuis le navigateur.",
                  "NON CONFIRMÉ"),
            "text/html; charset=utf-8", 400, "no-store",
            {"X-Robots-Tag": "noindex, nofollow, noarchive"},
        )
        return True
    except Exception:
        handler.send_bytes(
            _page("Paiement en cours de vérification",
                  "Le résultat bancaire n’est pas disponible pour le moment. Aucun succès n’est enregistré sans preuve du prestataire.",
                  "VÉRIFICATION"),
            "text/html; charset=utf-8", 503, "no-store",
            {"X-Robots-Tag": "noindex, nofollow, noarchive", "Retry-After": "30"},
        )
        return True

    if intent.state == "captured":
        title = "Paiement confirmé"
        message = "Le paiement a été relu et confirmé auprès du prestataire. Votre réservation peut poursuivre son rapprochement."
        state = "CONFIRMÉ"
    elif intent.state == "declined":
        title = "Paiement refusé"
        message = "Le prestataire a refusé le paiement. Aucun succès n’a été enregistré."
        state = "REFUSÉ"
    elif intent.state == "cancelled":
        title = "Paiement annulé"
        message = "Le parcours bancaire a été annulé. Aucun paiement n’a été enregistré."
        state = "ANNULÉ"
    elif intent.state == "error":
        title = "Paiement non finalisé"
        message = "Le prestataire signale une erreur technique finale. Aucun paiement n’a été enregistré."
        state = "ERREUR"
    else:
        title = "Paiement en cours de confirmation"
        message = "Le prestataire n’a pas encore fourni de résultat final. La réservation ne sera pas marquée payée avant confirmation."
        state = "EN ATTENTE"
    handler.send_bytes(
        _page(title, message, state),
        "text/html; charset=utf-8", 200, "no-store",
        {"X-Robots-Tag": "noindex, nofollow, noarchive"},
    )
    return True


def _cancel(handler, query: str) -> bool:
    # The browser redirect remains non-authoritative, but it is a useful trigger
    # for an authenticated getWebPaymentDetails reread. This prevents a genuine
    # Payline cancellation from leaving the local intent stuck in "created".
    return _browser_result(handler, query)


def _notify(handler, query: str) -> bool:
    try:
        notification_type = _single(query, "notificationType", r"[A-Za-z0-9_-]{1,32}", "notification_type_invalid")
        if notification_type.lower() != "webtrs":
            raise PaymentError("notification_type_invalid")
        token = _single(query, "token", r"[A-Za-z0-9_-]{1,80}", "payline_token_invalid")
        _apply_by_token(token)
    except private_config.PaylinePrivateConfigurationError:
        handler.send_bytes(b"", "text/plain; charset=utf-8", 503, "no-store", {"Retry-After": "30"})
        return True
    except PaymentError as exc:
        code = str(exc)
        status = 404 if code == "intent_not_found" else 400
        handler.send_bytes(b"", "text/plain; charset=utf-8", status, "no-store")
        return True
    except Exception:
        handler.send_bytes(b"", "text/plain; charset=utf-8", 503, "no-store", {"Retry-After": "30"})
        return True
    handler.send_bytes(b"", "text/plain; charset=utf-8", 204, "no-store")
    return True


def _checkout_page(handler) -> bool:
    nonce=secrets.token_urlsafe(18)
    handler._csp_nonce=nonce
    nonce_attr=html.escape(nonce,quote=True)
    start_route=json.dumps(START_ROUTE)
    document=f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>Paiement sécurisé | Checkup Auto</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#f5f6f1;color:#17372b}}
main{{max-width:760px;margin:auto;padding:64px 22px}}.card{{background:#fff;border:1px solid #dbe1d8;border-radius:24px;padding:32px}}
.eyebrow{{font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#66776e}}h1{{font-size:clamp(34px,7vw,60px);letter-spacing:-.045em;margin:.3em 0}}
p{{line-height:1.65;color:#40584d}}button{{border:0;border-radius:999px;padding:15px 22px;background:#17372b;color:white;font-weight:700;cursor:pointer}}
button:disabled{{opacity:.45;cursor:wait}}a{{color:#1f5845}}.status{{margin-top:18px;padding:14px 16px;border-radius:14px;background:#f0f3ef}}
.secure{{display:flex;gap:10px;align-items:center;font-size:13px;color:#66776e;margin-top:20px}}
</style></head><body><main><a href="/">← Checkup Auto</a><div class="card">
<div class="eyebrow">CHECKUP AUTO · PAIEMENT</div><h1>Finaliser le paiement.</h1>
<p>Le montant et la prestation sont relus côté serveur depuis votre réservation confirmée. Les données de carte sont saisies uniquement sur la page bancaire Payline / Monext.</p>
<button id="pay" type="button">Continuer vers le paiement sécurisé</button>
<div id="status" class="status" role="status" aria-live="polite">Vérification de votre réservation…</div>
<div class="secure">🔒 Aucun numéro de carte ni cryptogramme n’est traité par Checkup Auto.</div>
</div></main>
<script nonce="{nonce_attr}">
(()=>{{'use strict';
const button=document.getElementById('pay'),status=document.getElementById('status');
const params=new URLSearchParams(location.hash.slice(1)),ccid=params.get('ccid')||'',cct=params.get('cct')||'';
history.replaceState(null,'',location.pathname);
if(!ccid||!cct){{button.disabled=true;status.textContent='Lien de paiement incomplet. Revenez à votre réservation.';return;}}
status.textContent='Réservation identifiée. Le paiement ne démarre qu’après votre clic.';
button.addEventListener('click',async()=>{{
 button.disabled=true;status.textContent='Préparation du paiement sécurisé…';
 try{{
  const r=await fetch({start_route},{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{ccid,cct}})}});
  const data=await r.json().catch(()=>({{}}));
  if(r.ok&&data.ok&&typeof data.redirectUrl==='string'&&data.redirectUrl.startsWith('https://')){{location.assign(data.redirectUrl);return;}}
  if(data.error==='authoritative_booking_required')status.textContent='La réservation est confirmée côté navigateur mais son rapprochement Mercure est encore en cours. Réessayez dans quelques instants.';
  else if(data.error==='payment_provider_not_configured')status.textContent='Le paiement bancaire est en cours de configuration. Votre réservation reste enregistrée et aucun débit n’a été tenté.';
  else if(data.error==='payment_start_reconciliation_required')status.textContent='Une tentative précédente doit être vérifiée avant de relancer un paiement. Aucun nouvel encaissement automatique ne sera tenté.';
  else status.textContent='Le paiement ne peut pas être préparé pour le moment. Aucun débit n’a été tenté.';
 }}catch(_e){{status.textContent='Connexion momentanément indisponible. Aucun débit n’a été tenté.';}}
 finally{{button.disabled=false;}}
}});
}})();
</script></body></html>""".encode("utf-8")
    handler.send_bytes(
        document,
        "text/html; charset=utf-8",
        200,
        "no-store",
        {"X-Robots-Tag":"noindex, nofollow, noarchive"},
    )
    return True


def _start(handler) -> bool:
    if not handler._admin_origin_ok() or handler.headers.get("Sec-Fetch-Site","")=="cross-site":
        handler.send_json({"ok":False,"error":"payment_origin_not_allowed"},403)
        return True
    if handler.headers.get("Content-Type","").split(";",1)[0].strip().lower()!="application/json":
        handler.send_json({"ok":False,"error":"payment_content_type_invalid"},415)
        return True
    try:
        payload=handler._read_json()
        if not isinstance(payload,dict) or set(payload)!={"ccid","cct"}:
            raise PaymentError("payment_start_payload_invalid")
        result=checkout.start_payline_for_browser(payload.get("ccid"),payload.get("cct"))
    except private_config.PaylinePrivateConfigurationError:
        handler.send_json({"ok":False,"error":"payment_provider_not_configured"},503,{"Retry-After":"60"})
        return True
    except PaymentError as exc:
        code=str(exc)
        status=409 if code=="payment_start_reconciliation_required" else 400
        handler.send_json({"ok":False,"error":code},status)
        return True
    except Exception:
        handler.send_json({"ok":False,"error":"payment_start_unavailable"},503,{"Retry-After":"30"})
        return True
    handler.send_json({"ok":True,**result},201 if not result.get("reused") else 200)
    return True


def handle(handler) -> bool:
    parsed = urlsplit(handler.path)
    if getattr(handler, "command", "") == "POST" and parsed.path == START_ROUTE:
        return _start(handler)
    if getattr(handler, "command", "") != "GET":
        return False
    if parsed.path == CHECKOUT_ROUTE:
        return _checkout_page(handler)
    if parsed.path == RETURN_ROUTE:
        return _browser_result(handler, parsed.query)
    if parsed.path == CANCEL_ROUTE:
        return _cancel(handler, parsed.query)
    if parsed.path == NOTIFY_ROUTE:
        return _notify(handler, parsed.query)
    return False
