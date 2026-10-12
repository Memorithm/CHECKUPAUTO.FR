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
import customer_booking_payment_binding as booking_payment_binding
import payment_payline_private as private_config
import payment_mode
import site_config_store
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
    config = private_config.load(intent.environment)
    event = payline.refresh(intent, config)
    return store._apply_verified(event)


def _apply_by_token(token: str):
    store = _journal_existing()
    intent = store.get_by_provider_reference("payline", token)
    config = private_config.load(intent.environment)
    event = payline.refresh(intent, config)
    return store._apply_verified(event)


def _page(title: str, message: str, state: str) -> bytes:
    safe_title = html.escape(title)
    safe_message = html.escape(message)
    safe_state = html.escape(state)
    document = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>__TITLE__ | Checkup Auto</title>
<style>
:root{--paper:#f5f6f1;--ink:#17372b;--muted:#66776e;--line:#d8dfd8;--green:#1f5443;--soft:#edf1eb;--white:#fff}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:linear-gradient(135deg,#fafbf8 0%,var(--paper) 58%,#eef2ec 100%);color:var(--ink);font-family:Arial,Helvetica,sans-serif}
body:before{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(rgba(31,84,67,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(31,84,67,.035) 1px,transparent 1px);background-size:52px 52px;mask-image:linear-gradient(to bottom,black,transparent 78%)}
a{color:inherit;text-decoration:none}.shell{width:min(980px,calc(100% - 32px));margin:0 auto;padding:30px 0 54px}.top{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:0 2px 26px}
.brand{display:flex;align-items:center;gap:12px;font-weight:700;letter-spacing:-.035em}.mark{width:38px;height:38px;border:1px solid #9db2a6;border-radius:50%;display:grid;place-items:center}.back{font-size:12px;color:var(--muted)}
.panel{position:relative;overflow:hidden;background:rgba(255,255,255,.94);border:1px solid var(--line);box-shadow:0 30px 80px rgba(24,55,43,.08);border-radius:28px;padding:clamp(28px,6vw,58px)}
.panel:after{content:"";position:absolute;width:300px;height:300px;border:1px solid rgba(31,84,67,.08);border-radius:50%;right:-130px;top:-155px}
.eyebrow{font:11px Consolas,monospace;letter-spacing:.14em;color:var(--green);text-transform:uppercase}.state{display:inline-flex;margin-top:22px;padding:8px 11px;border:1px solid #c8d6ce;background:var(--soft);font:700 10px Consolas,monospace;letter-spacing:.1em}
h1{font-family:Georgia,'Times New Roman',serif;font-size:clamp(40px,7vw,70px);line-height:.98;letter-spacing:-.045em;font-weight:400;margin:20px 0 18px;max-width:760px}
.lead{max-width:680px;font-size:15px;line-height:1.75;color:#4c6257;margin:0}.proofs{display:grid;grid-template-columns:repeat(3,1fr);gap:1px;background:var(--line);border:1px solid var(--line);margin-top:34px}
.proof{background:#fbfcfa;padding:18px}.proof small{display:block;font:9px Consolas,monospace;letter-spacing:.09em;color:#748178;margin-bottom:7px}.proof strong{font-size:13px;font-weight:600}
.actions{display:flex;align-items:center;gap:18px;flex-wrap:wrap;margin-top:32px}.primary{display:inline-flex;align-items:center;gap:14px;background:var(--green);color:#fff;padding:15px 19px;font-size:12px}.help{font-size:11px;color:var(--muted)}
@media(max-width:680px){.shell{width:min(100% - 22px,980px);padding-top:18px}.top{padding-bottom:18px}.panel{border-radius:20px;padding:26px 22px}.proofs{grid-template-columns:1fr}.back{font-size:10px}}
</style><link rel="stylesheet" href="/assets/action-controls.css?v=20261008-1"></head><body><main class="shell">
<div class="top"><a class="brand" href="/"><span class="mark">✓</span><span>CHECKUP AUTO</span></a><a class="back" href="/">Retour au site</a></div>
<section class="panel" aria-labelledby="paymentResultTitle">
<div class="eyebrow">Paiement sécurisé · vérification prestataire</div>
<div class="state">__STATE__</div>
<h1 id="paymentResultTitle">__TITLE__</h1>
<p class="lead">__MESSAGE__</p>
<div class="proofs" aria-label="Garanties de vérification">
<div class="proof"><small>01 / SOURCE</small><strong>Résultat relu côté serveur</strong></div>
<div class="proof"><small>02 / CARTE</small><strong>Aucune donnée bancaire stockée ici</strong></div>
<div class="proof"><small>03 / ÉTAT</small><strong>Aucun succès sans preuve Payline</strong></div>
</div>
<div class="actions"><a class="primary" href="/">Revenir à Checkup Auto →</a><span class="help">Votre réservation reste protégée pendant la vérification.</span></div>
</section></main></body></html>"""
    return (
        document.replace("__TITLE__", safe_title)
        .replace("__MESSAGE__", safe_message)
        .replace("__STATE__", safe_state)
        .encode("utf-8")
    )


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

    try:
        request_key = booking_payment_binding.request_key_for_payment(payment_id)
    except Exception:
        request_key = None
    if request_key:
        # In-site booking: go back to the confirmation page, which re-reads
        # booking and payment state for the authenticated account.
        handler.send_redirect("/compte/reservation?cle=" + request_key, 303)
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
    nonce = secrets.token_urlsafe(18)
    handler._csp_nonce = nonce
    nonce_attr = html.escape(nonce, quote=True)
    start_route = json.dumps(START_ROUTE)
    document = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>Paiement sécurisé | Checkup Auto</title>
<style>
:root{--paper:#f5f6f1;--ink:#17372b;--muted:#69786f;--line:#d9e0d9;--green:#1f5443;--soft:#edf1eb;--white:#fff}
*{box-sizing:border-box}html{background:var(--paper)}body{margin:0;min-height:100vh;background:radial-gradient(circle at 78% 18%,rgba(171,193,180,.22),transparent 31%),linear-gradient(135deg,#fbfcf9 0%,var(--paper) 60%,#edf1eb 100%);color:var(--ink);font-family:Arial,Helvetica,sans-serif}
body:before{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(rgba(31,84,67,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(31,84,67,.035) 1px,transparent 1px);background-size:54px 54px;mask-image:linear-gradient(to bottom,black,transparent 82%)}
a{color:inherit;text-decoration:none}.shell{width:min(1180px,calc(100% - 34px));margin:0 auto;padding:26px 0 48px}.top{display:flex;align-items:center;justify-content:space-between;gap:22px;padding:0 2px 24px}
.brand{display:flex;align-items:center;gap:12px;font-weight:700;letter-spacing:-.035em}.mark{width:40px;height:40px;border:1px solid #99afa2;border-radius:50%;display:grid;place-items:center;font-size:19px}.back{font-size:11px;color:var(--muted)}
.progress{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid var(--line);background:rgba(255,255,255,.62);margin-bottom:14px}.step{padding:13px 16px;display:flex;gap:10px;align-items:center;border-right:1px solid var(--line);font-size:11px;color:#7a867f}.step:last-child{border-right:0}.step b{font:10px Consolas,monospace}.step.done,.step.current{color:var(--ink)}.step.current{background:#fff}.step.done b{color:var(--green)}
.card{position:relative;overflow:hidden;display:grid;grid-template-columns:minmax(0,1.15fr) minmax(300px,.65fr);background:rgba(255,255,255,.96);border:1px solid var(--line);border-radius:30px;box-shadow:0 32px 90px rgba(23,55,43,.09)}
.content{padding:clamp(30px,5vw,60px)}.side{position:relative;padding:clamp(28px,4vw,44px);background:linear-gradient(150deg,#eef3ed 0%,#e2eae4 100%);border-left:1px solid var(--line);display:flex;flex-direction:column;justify-content:space-between;min-height:510px}
.side:before,.side:after{content:"";position:absolute;border:1px solid rgba(31,84,67,.12);border-radius:50%}.side:before{width:360px;height:360px;right:-210px;top:-110px}.side:after{width:210px;height:210px;left:-110px;bottom:-95px}
.eyebrow{font:10px Consolas,monospace;letter-spacing:.15em;color:var(--green);text-transform:uppercase}.stage{display:inline-flex;margin-top:22px;padding:7px 10px;border:1px solid #c7d5cd;background:#f4f7f3;font:700 9px Consolas,monospace;letter-spacing:.1em}
h1{font-family:Georgia,'Times New Roman',serif;font-size:clamp(44px,6vw,76px);line-height:.96;letter-spacing:-.05em;font-weight:400;margin:20px 0 22px;max-width:720px}.lead{font-size:15px;line-height:1.75;color:#4d6258;max-width:660px;margin:0}
.notice{margin-top:26px;padding:16px 18px;background:#f4f7f3;border-left:3px solid var(--green);font-size:12px;line-height:1.55;color:#4f6258}.actions{margin-top:28px;display:flex;align-items:center;gap:18px;flex-wrap:wrap}
button{appearance:none;border:0;border-radius:0;background:var(--green);color:white;padding:17px 22px;font:700 12px Arial,Helvetica,sans-serif;cursor:pointer;box-shadow:0 12px 28px rgba(31,84,67,.16);transition:transform .18s ease,box-shadow .18s ease,opacity .18s ease}
button:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 15px 34px rgba(31,84,67,.22)}button:focus-visible{outline:3px solid rgba(31,84,67,.28);outline-offset:4px}button:disabled{opacity:.48;cursor:wait;box-shadow:none}
.micro{font-size:10px;color:#7b8780;line-height:1.55;max-width:260px}.status{margin-top:18px;min-height:49px;padding:14px 16px;border:1px solid #dce3dc;background:#fafbf9;font-size:12px;line-height:1.55;color:#52645b}
.status[data-state="ready"]{border-color:#b8ccbf;background:#f1f6f2}.status[data-state="busy"]{border-color:#c6d2cb;background:#f4f7f4}.status[data-state="error"]{border-color:#d7b5ae;background:#fff7f5;color:#76483e}
.side-copy{position:relative;z-index:1}.side small{font:9px Consolas,monospace;letter-spacing:.13em;color:#6f7f75}.side h2{font:400 29px/1.08 Georgia,'Times New Roman',serif;margin:16px 0}.side p{font-size:12px;line-height:1.65;color:#5c6d63;margin:0}
.proofs{position:relative;z-index:1;display:grid;gap:10px;margin-top:36px}.proof{display:grid;grid-template-columns:28px 1fr;gap:10px;align-items:start;padding-top:12px;border-top:1px solid rgba(31,84,67,.15)}.proof b{font:10px Consolas,monospace;color:var(--green)}.proof span{font-size:11px;line-height:1.45}
.secure{position:relative;z-index:1;margin-top:30px;padding:13px 0 0;border-top:1px solid rgba(31,84,67,.15);font-size:10px;line-height:1.55;color:#607168}
@media(max-width:850px){.card{grid-template-columns:1fr}.side{border-left:0;border-top:1px solid var(--line);min-height:0}.progress{grid-template-columns:1fr}.step{border-right:0;border-bottom:1px solid var(--line)}.step:last-child{border-bottom:0}}
@media(max-width:560px){.shell{width:min(100% - 20px,1180px);padding-top:15px}.top{padding-bottom:16px}.brand{font-size:14px}.mark{width:35px;height:35px}.back{font-size:10px}.content{padding:27px 21px}.side{padding:25px 21px}.card{border-radius:20px}.actions{align-items:stretch;flex-direction:column}.actions button{width:100%}.micro{max-width:none}}
@media(prefers-reduced-motion:reduce){button{transition:none}button:hover:not(:disabled){transform:none}}
</style><link rel="stylesheet" href="/assets/action-controls.css?v=20261008-1"></head><body><main class="shell">
<div class="top"><a class="brand" href="/"><span class="mark">✓</span><span>CHECKUP AUTO</span></a><a class="back" href="/">← Revenir à la réservation</a></div>
<div class="progress" aria-label="Progression du paiement">
<div class="step done"><b>01</b><span>Réservation confirmée</span></div>
<div class="step current" aria-current="step"><b>02</b><span>Paiement sécurisé</span></div>
<div class="step"><b>03</b><span>Confirmation</span></div>
</div>
<section class="card" aria-labelledby="checkoutTitle">
<div class="content">
<div class="eyebrow">Checkup Auto · paiement bancaire</div>
<div class="stage">ÉTAPE 2 SUR 3</div>
<h1 id="checkoutTitle">Finaliser votre paiement.</h1>
<p class="lead">Votre réservation a été identifiée. Le montant, la prestation et l’acceptation des conditions de vente sont relus côté serveur avant toute demande adressée à Payline / Monext.</p>
<div class="notice">Vous allez quitter momentanément Checkup Auto pour la page bancaire sécurisée. Les données de carte sont saisies uniquement chez le prestataire de paiement.</div>
<div class="actions">
<button id="pay" type="button">Continuer vers Payline / Monext →</button>
<span class="micro">Aucun débit ne démarre avant votre clic. Une tentative incertaine n’est jamais relancée automatiquement.</span>
</div>
<div id="status" class="status" data-state="busy" role="status" aria-live="polite">Vérification de votre réservation…</div>
</div>
<aside class="side" aria-label="Garanties du paiement">
<div class="side-copy"><small>PAIEMENT / CONTRÔLE TECHNIQUE</small><h2>Une transaction séparée de vos données bancaires.</h2><p>Checkup Auto orchestre la réservation et vérifie le résultat. La saisie de carte reste sur l’infrastructure Payline / Monext.</p></div>
<div class="proofs">
<div class="proof"><b>01</b><span>Montant vérifié côté serveur depuis la réservation Mercure.</span></div>
<div class="proof"><b>02</b><span>Numéro de carte et cryptogramme non traités par Checkup Auto.</span></div>
<div class="proof"><b>03</b><span>Résultat bancaire revalidé auprès de Payline avant confirmation.</span></div>
</div>
<div class="secure">Connexion HTTPS · page bancaire hébergée · résultat vérifié côté serveur</div>
</aside>
</section></main>
<script nonce="__NONCE__">
(()=>{'use strict';
const button=document.getElementById('pay'),status=document.getElementById('status');
const setStatus=(text,state)=>{status.textContent=text;status.dataset.state=state;};
const params=new URLSearchParams(location.hash.slice(1)),ccid=params.get('ccid')||'',cct=params.get('cct')||'';
history.replaceState(null,'',location.pathname);
if(!ccid||!cct){button.disabled=true;setStatus('Lien de paiement incomplet. Revenez à votre réservation pour générer un nouveau lien.','error');return;}
setStatus('Réservation identifiée. Le paiement ne démarre qu’après votre clic.','ready');
button.addEventListener('click',async()=>{
 button.disabled=true;setStatus('Préparation de la session bancaire sécurisée…','busy');
 try{
  const r=await fetch(__START_ROUTE__,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({ccid,cct})});
  const data=await r.json().catch(()=>({}));
  if(r.ok&&data.ok&&typeof data.redirectUrl==='string'&&data.redirectUrl.startsWith('https://')){setStatus('Session sécurisée prête. Redirection vers Payline / Monext…','ready');location.assign(data.redirectUrl);return;}
  if(data.error==='authoritative_booking_required')setStatus('La réservation est confirmée dans votre navigateur mais son rapprochement Mercure est encore en cours. Réessayez dans quelques instants.','error');
  else if(data.error==='payment_provider_not_configured')setStatus('Le paiement bancaire est en cours de configuration. Votre réservation reste enregistrée et aucun débit n’a été tenté.','error');
  else if(data.error==='payment_start_reconciliation_required')setStatus('Une tentative précédente doit être vérifiée avant de relancer un paiement. Aucun nouvel encaissement automatique ne sera tenté.','error');
  else setStatus('Le paiement ne peut pas être préparé pour le moment. Aucun débit n’a été tenté.','error');
 }catch(_e){setStatus('Connexion momentanément indisponible. Aucun débit n’a été tenté.','error');}
 finally{button.disabled=false;}
});
})();
</script></body></html>"""
    document = (
        document.replace("__NONCE__", nonce_attr)
        .replace("__START_ROUTE__", start_route)
    ).encode("utf-8")
    handler.send_bytes(
        document,
        "text/html; charset=utf-8",
        200,
        "no-store",
        {"X-Robots-Tag": "noindex, nofollow, noarchive"},
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
    try:
        delegated = payment_mode.status(site_config_store.load()).get("delegated") is True
    except Exception:
        delegated = False
    if delegated and parsed.path in {START_ROUTE, CHECKOUT_ROUTE}:
        if getattr(handler, "command", "") == "POST" and parsed.path == START_ROUTE:
            handler.send_json({"ok": False, "error": "payment_delegated_to_mercureweb"}, 409)
            return True
        if getattr(handler, "command", "") == "GET" and parsed.path == CHECKOUT_ROUTE:
            handler.send_bytes(
                b"Payment delegated to MercureWeb",
                "text/plain; charset=utf-8",
                404,
                "no-store",
                {"X-Robots-Tag": "noindex, nofollow, noarchive"},
            )
            return True
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
