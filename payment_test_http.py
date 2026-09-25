"""HTTP surface for the staging reservation + payment rehearsal."""
from __future__ import annotations

import html
import json
import secrets
from urllib.parse import urlsplit

import payment_test_lab as lab

DEMO_ROUTE="/demo"
PAGE_ROUTE="/payment/test"
PROVIDER_ROUTE="/payment/test/provider"
DEMO_STATUS_ROUTE="/api/payment-test/demo-status"
SESSION_ROUTE="/api/payment-test/session"
CREATE_ROUTE="/api/payment-test/create"
PREPARE_PAYLINE_ROUTE="/api/payment-test/prepare-payline"
RESULT_ROUTE="/api/payment-test/result"
STATUS_ROUTE="/api/payment-test/status"
REMOVE_ROUTE="/api/payment-test/remove"


def _json(handler, fn, *, created=False):
    if not lab.enabled():
        handler.send_json({"ok":False,"error":"not_found"},404)
        return True
    if not handler._admin_origin_ok() or handler.headers.get("Sec-Fetch-Site","")=="cross-site":
        handler.send_json({"ok":False,"error":"payment_test_origin_not_allowed"},403)
        return True
    if handler.headers.get("Content-Type","").split(";",1)[0].strip().lower()!="application/json":
        handler.send_json({"ok":False,"error":"payment_test_content_type_invalid"},415)
        return True
    try:
        payload=handler._read_json()
        if not isinstance(payload,dict):
            raise ValueError
        result=fn(payload)
        handler.send_json(result,201 if created else 200)
    except PermissionError:
        handler.send_json({"ok":False,"error":"payment_test_forbidden"},403)
    except Exception as exc:
        code=str(exc)
        safe=code if code.startswith("payment_test_") else "payment_test_request_invalid"
        handler.send_json({"ok":False,"error":safe},400)
    return True



def _demo_page(handler) -> bool:
    if not lab.enabled():
        handler.send_json({"error":"not_found"},404)
        return True
    status=lab.demo_status()
    payline=status["payment"]["paylineSandbox"]
    configured=bool(payline.get("configured") and payline.get("configurationValid"))
    badge="PRÊT POUR HOMOLOGATION" if configured else "CONFIG API SANDBOX À INSTALLER"
    badge_class="ready" if configured else "blocked"
    blockers=", ".join(payline.get("blockingReasons") or []) or "aucun"
    body=f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>Démo complète | Checkup Auto</title>
<style>
:root{{--paper:#f6f7f2;--ink:#213b30;--muted:#69776f;--line:#d9dfd3;--green:#1f5443;--soft:#edf1eb}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(145deg,#fbfcf9,var(--paper));color:var(--ink);font-family:Arial,Helvetica,sans-serif}}
main{{width:min(1120px,calc(100% - 32px));margin:auto;padding:38px 0 70px}}a{{color:inherit;text-decoration:none}}
.hero{{padding:42px;background:#fff;border:1px solid var(--line);box-shadow:0 26px 70px rgba(31,84,67,.07)}}.eyebrow{{font:10px Consolas,monospace;letter-spacing:.14em;color:var(--green)}}
h1{{font:400 clamp(46px,7vw,76px)/.98 Georgia,serif;letter-spacing:-.045em;margin:14px 0}}p{{line-height:1.7;color:var(--muted)}}
.status{{display:inline-flex;padding:8px 10px;font:700 9px Consolas,monospace;letter-spacing:.08em;border:1px solid;margin-top:8px}}.ready{{background:#eaf3ec;border-color:#abc7b2;color:#174b32}}.blocked{{background:#fff1dd;border-color:#e0c18e;color:#754d0a}}
.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:18px}}.card{{background:#fff;border:1px solid var(--line);padding:24px;min-height:220px;display:flex;flex-direction:column}}
.card small{{font:9px Consolas,monospace;letter-spacing:.1em;color:#718077}}.card h2{{font:400 27px/1.08 Georgia,serif;margin:12px 0}}.card p{{font-size:12px;margin:0 0 20px}}.card a{{margin-top:auto;background:var(--green);color:#fff;padding:12px 14px;font-size:11px;display:inline-block;align-self:flex-start}}
.meta{{margin-top:18px;padding:18px;background:var(--soft);border:1px solid var(--line);font:11px/1.7 Consolas,monospace;overflow-wrap:anywhere}}
@media(max-width:820px){{.grid{{grid-template-columns:1fr}}.hero{{padding:28px}}}}
</style></head><body><main>
<section class="hero"><div class="eyebrow">STAGING · DÉMO QUASI-RÉELLE</div><h1>Checkup Auto, de bout en bout.</h1>
<p>Cette surface regroupe le site, la réservation Mercure, le paiement sandbox et les principaux contrats backend. Aucun DNS de production n’est modifié et aucun paiement live n’est activé.</p>
<span class="status {badge_class}">{html.escape(badge)}</span></section>
<div class="grid">
<article class="card"><small>01 / SITE COMPLET</small><h2>Parcours client</h2><p>Accueil, véhicule, tarifs, disponibilités Mercure, CGV, application et contact.</p><a href="/">Ouvrir le site →</a></article>
<article class="card"><small>02 / PAIEMENT</small><h2>Réservation + Payline</h2><p>Choisissez entre le simulateur intégral et le vrai checkout Payline d’homologation lorsqu’il est configuré.</p><a href="/payment/test">Ouvrir la démo paiement →</a></article>
<article class="card"><small>03 / BACKEND</small><h2>Contrats actifs</h2><p>Mercure, disponibilité, mobile bootstrap, checkout serveur et formulaire de contact sans remboursement automatique.</p><a href="/api/payment-test/demo-status">Voir le statut JSON →</a></article>
</div>
<div class="meta">Payline sandbox configuré={str(bool(payline.get("configured"))).lower()} · configuration valide={str(bool(payline.get("configurationValid"))).lower()} · checkoutBound={str(bool(payline.get("checkoutBound"))).lower()} · callbacksBound={str(bool(payline.get("callbacksBound"))).lower()} · livePaymentsEnabled=false · blockers={html.escape(blockers)}</div>
</main></body></html>""".encode("utf-8")
    handler.send_bytes(body,"text/html; charset=utf-8",200,"no-store",{"X-Robots-Tag":"noindex, nofollow, noarchive"})
    return True


def _page(handler) -> bool:
    if not lab.enabled():
        handler.send_json({"error":"not_found"},404)
        return True
    nonce=secrets.token_urlsafe(18)
    handler._csp_nonce=nonce
    n=html.escape(nonce,quote=True)
    body=f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>Test réservation + paiement | Checkup Auto</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#f4f5f0;color:#17372b}}
main{{max-width:880px;margin:auto;padding:48px 20px 80px}}.card{{background:#fff;border:1px solid #dce2da;border-radius:24px;padding:28px;margin:18px 0}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}label{{display:grid;gap:7px;font-weight:650}}
input,select,button{{font:inherit;padding:13px 14px;border-radius:12px;border:1px solid #c8d2ca}}button{{border:0;background:#17372b;color:#fff;font-weight:750;cursor:pointer}}
button.secondary{{background:#e8eee9;color:#17372b}}button:disabled{{opacity:.5;cursor:wait}}.slots{{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}}
.slot{{background:#eef3ef;color:#17372b}}.slot.active{{background:#17372b;color:#fff}}.status{{padding:14px 16px;background:#eef3ef;border-radius:14px;line-height:1.5}}
.warn{{background:#fff3d7;color:#664b00}}small{{color:#66776e}}@media(max-width:680px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><main><a href="/">← Checkup Auto</a>
<div class="card"><small>STAGING · PAIEMENT SANDBOX UNIQUEMENT</small><h1>Test réservation + paiement</h1>
<p>Ce parcours crée un vrai rendez-vous <strong>synthétique</strong> dans Mercure. Vous pouvez ensuite utiliser soit le simulateur intégral CheckupAuto, soit le vrai checkout Payline / Monext d’homologation lorsque la configuration API sandbox est installée.</p></div>
<div class="card">
<div class="grid">
<label>Prestation<select id="service"><option value="technical">Contrôle technique · 80 €</option><option value="fitted">Véhicule aménagé · 90 €</option></select></label>
<label>Date<input id="date" type="date"></label>
</div>
<p><button id="load" type="button" class="secondary">Charger les créneaux Mercure</button></p>
<div id="slots" class="slots"></div>
<label><input id="terms" type="checkbox"> J’ai lu et j’accepte les <a href="/cgv" target="_blank" rel="noopener">CGV</a> pour ce test.</label>
<label><input id="immediate" type="checkbox"> J’accepte l’exécution immédiate dans le cadre de ce test de parcours.</label>
<p><button id="create" type="button" disabled>Simuler le paiement de bout en bout</button> <button id="realPayline" type="button" class="secondary" disabled>Ouvrir Payline homologation réelle</button></p>
<div id="paylineState" class="status warn">Lecture de la configuration Payline sandbox…</div>
<div id="status" class="status">Initialisation de la session de test…</div>
<p><button id="cleanupPrevious" type="button" class="secondary" hidden>Supprimer le rendez-vous test précédent</button></p>
</div>
</main><script nonce="{n}">
(()=>{{'use strict';
const $=id=>document.getElementById(id),service=$('service'),date=$('date'),slots=$('slots'),status=$('status'),
 load=$('load'),create=$('create'),realPayline=$('realPayline'),terms=$('terms'),immediate=$('immediate'),
 paylineState=$('paylineState'),cleanupPrevious=$('cleanupPrevious');
let token='',selected='',paylineReady=false;
const tomorrow=new Date(Date.now()+86400000);date.value=tomorrow.toISOString().slice(0,10);
const post=async(url,payload)=>{{const r=await fetch(url,{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(payload)}});const d=await r.json().catch(()=>({{}}));if(!r.ok)throw new Error(d.error||'request_failed');return d;}};
const refreshCreate=()=>{{const ready=!!(token&&selected&&terms.checked&&immediate.checked);create.disabled=!ready;realPayline.disabled=!(ready&&paylineReady)}};
terms.addEventListener('change',refreshCreate);immediate.addEventListener('change',refreshCreate);
(async()=>{{try{{const d=await post('{SESSION_ROUTE}',{{}});token=d.token;paylineReady=!!(d.paylineSandbox?.configured&&d.paylineSandbox?.configurationValid);paylineState.textContent=paylineReady?'Payline sandbox configuré : le parcours d’homologation réel est disponible.':'Payline sandbox non configuré : le simulateur reste disponible. Le vrai doWebPayment sera activé automatiquement après installation des identifiants de test.';paylineState.classList.toggle('warn',!paylineReady);status.textContent='Session prête. Choisissez une date et un créneau.';refreshCreate();}}catch(e){{status.textContent='Impossible de créer la session test : '+e.message;}}}})();
const previous=sessionStorage.getItem('checkupautoPaymentTestToken')||'';if(previous){{cleanupPrevious.hidden=false;cleanupPrevious.addEventListener('click',async()=>{{cleanupPrevious.disabled=true;try{{await post('{REMOVE_ROUTE}',{{token:previous}});sessionStorage.removeItem('checkupautoPaymentTestToken');cleanupPrevious.hidden=true;status.textContent='Rendez-vous test précédent supprimé de Mercure.';}}catch(e){{status.textContent='Nettoyage précédent impossible : '+e.message;cleanupPrevious.disabled=false;}}}});}}
load.addEventListener('click',async()=>{{selected='';refreshCreate();slots.replaceChildren();status.textContent='Lecture des disponibilités Mercure…';
 try{{const r=await fetch('/api/booking/availability?service='+encodeURIComponent(service.value)+'&date='+encodeURIComponent(date.value),{{cache:'no-store'}});const d=await r.json();if(!r.ok)throw new Error(d.error||'availability_failed');
 let found=0;for(const day of (d.days||[])){{for(const slot of (day.slots||[])){{const b=document.createElement('button');b.type='button';b.className='slot';b.textContent=String(day.date)+' · '+String(slot.time)+' · '+String(slot.price||'')+' €';b.addEventListener('click',()=>{{date.value=String(day.date);selected=String(slot.time);for(const x of slots.querySelectorAll('.slot'))x.classList.remove('active');b.classList.add('active');status.textContent='Créneau sélectionné : '+day.date+' à '+selected;refreshCreate();}});slots.append(b);found++;}}}}
 if(!found)status.textContent='Aucun créneau disponible sur la période retournée par Mercure.';else status.textContent=found+' créneau(x) disponible(s) sur les prochains jours.';
 }}catch(e){{status.textContent='Disponibilités indisponibles : '+e.message;}}}});
create.addEventListener('click',async()=>{{create.disabled=true;status.textContent='Création du rendez-vous synthétique dans Mercure…';
 try{{const d=await post('{CREATE_ROUTE}',{{token,service:service.value,date:date.value,time:selected,acceptTerms:true,immediatePerformance:true}});
 sessionStorage.setItem('checkupautoPaymentTestToken',token);
 status.textContent='Rendez-vous créé. Ouverture du simulateur de paiement…';location.assign(d.providerUrl);
 }}catch(e){{status.textContent='Échec du test : '+e.message;refreshCreate();}}}});
realPayline.addEventListener('click',async()=>{{realPayline.disabled=true;status.textContent='Préparation du rendez-vous Mercure et du checkout Payline homologation…';
 try{{const d=await post('{PREPARE_PAYLINE_ROUTE}',{{token,service:service.value,date:date.value,time:selected,acceptTerms:true,immediatePerformance:true}});
 sessionStorage.setItem('checkupautoPaymentTestToken',token);
 status.textContent='Réservation prête. Ouverture du checkout Checkup Auto…';location.assign(d.checkoutUrl);
 }}catch(e){{status.textContent='Homologation Payline indisponible : '+e.message;refreshCreate();}}}});
}})();
</script></body></html>""".encode("utf-8")
    handler.send_bytes(body,"text/html; charset=utf-8",200,"no-store",{"X-Robots-Tag":"noindex, nofollow, noarchive"})
    return True


def _provider_page(handler) -> bool:
    if not lab.enabled():
        handler.send_json({"error":"not_found"},404)
        return True
    nonce=secrets.token_urlsafe(18);handler._csp_nonce=nonce;n=html.escape(nonce,quote=True)
    body=f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive"><title>Simulateur Payline | Checkup Auto</title>
<style>body{{font-family:system-ui;margin:0;background:#f4f5f0;color:#17372b}}main{{max-width:720px;margin:auto;padding:64px 22px}}.card{{background:#fff;border:1px solid #dce2da;border-radius:24px;padding:30px}}button{{font:inherit;border:0;border-radius:999px;padding:14px 20px;margin:5px;background:#17372b;color:#fff;font-weight:750}}button.secondary{{background:#dfe8e1;color:#17372b}}button.danger{{background:#8d2f27}}.status{{margin-top:18px;padding:14px;background:#eef3ef;border-radius:14px;line-height:1.5}}</style></head>
<body><main><div class="card"><small>SIMULATEUR PAYLINE · AUCUN DÉBIT</small><h1>Choisir le résultat bancaire de test</h1>
<p>Cette page simule uniquement le résultat d’homologation. Aucune donnée de carte n’est demandée.</p>
<p><button data-outcome="captured">Paiement accepté</button><button class="danger" data-outcome="declined">Paiement refusé</button><button class="secondary" data-outcome="pending">Paiement en attente</button><button class="secondary" data-outcome="cancelled">Paiement annulé</button><button class="secondary" data-outcome="error">Erreur technique Payline</button></p>
<div id="status" class="status">Lecture de la session…</div><p><button id="cleanup" class="secondary" type="button">Supprimer le rendez-vous test Mercure</button></p>
<p><a href="/payment/test">Nouveau test</a></p></div></main>
<script nonce="{n}">
(()=>{{'use strict';const status=document.getElementById('status'),cleanup=document.getElementById('cleanup'),p=new URLSearchParams(location.hash.slice(1));
let token=p.get('token')||sessionStorage.getItem('checkupautoPaymentTestToken')||'',paymentId=p.get('paymentId')||'';history.replaceState(null,'',location.pathname);
const post=async(url,payload)=>{{const r=await fetch(url,{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(payload)}});const d=await r.json().catch(()=>({{}}));if(!r.ok)throw new Error(d.error||'request_failed');return d;}};
if(!token||!paymentId)status.textContent='Session de test incomplète.';
for(const b of document.querySelectorAll('[data-outcome]'))b.addEventListener('click',async()=>{{const buttons=[...document.querySelectorAll('[data-outcome]')];for(const x of buttons)x.disabled=true;status.textContent='Application du résultat Payline simulé…';let terminal=false;try{{const d=await post('{RESULT_ROUTE}',{{token,paymentId,outcome:b.dataset.outcome}});terminal=d.state==='captured';status.textContent='Résultat vérifié : '+d.state+' · '+(d.amountCents/100).toFixed(2)+' EUR. Aucun débit bancaire réel.';}}catch(e){{status.textContent='Erreur : '+e.message;}}finally{{if(!terminal)for(const x of buttons)x.disabled=false;}}}});
cleanup.addEventListener('click',async()=>{{cleanup.disabled=true;try{{const d=await post('{REMOVE_ROUTE}',{{token}});status.textContent='Rendez-vous test Mercure supprimé.';}}catch(e){{status.textContent='Suppression impossible : '+e.message;cleanup.disabled=false;}}}});
}})();</script></body></html>""".encode("utf-8")
    handler.send_bytes(body,"text/html; charset=utf-8",200,"no-store",{"X-Robots-Tag":"noindex, nofollow, noarchive"})
    return True


def handle(handler) -> bool:
    parsed=urlsplit(handler.path)
    path=parsed.path
    command=getattr(handler,"command","")
    if command=="GET" and path==DEMO_ROUTE:
        return _demo_page(handler)
    if command=="GET" and path==PAGE_ROUTE:
        return _page(handler)
    if command=="GET" and path==PROVIDER_ROUTE:
        return _provider_page(handler)
    if command=="POST" and path==DEMO_STATUS_ROUTE:
        return _json(handler,lambda payload: lab.demo_status())
    if command=="POST" and path==SESSION_ROUTE:
        return _json(handler,lambda payload: lab.create_session(),created=True)
    if command=="POST" and path==CREATE_ROUTE:
        return _json(handler,lambda p: lab.create_reservation(
            p.get("token"),p.get("service"),p.get("date"),p.get("time"),
            accept_terms=p.get("acceptTerms") is True,
            immediate_performance=p.get("immediatePerformance") is True,
        ),created=True)
    if command=="POST" and path==PREPARE_PAYLINE_ROUTE:
        return _json(handler,lambda p: lab.prepare_payline_checkout(
            p.get("token"),p.get("service"),p.get("date"),p.get("time"),
            accept_terms=p.get("acceptTerms") is True,
            immediate_performance=p.get("immediatePerformance") is True,
        ),created=True)
    if command=="POST" and path==RESULT_ROUTE:
        return _json(handler,lambda p: lab.apply_result(p.get("token"),p.get("paymentId"),p.get("outcome")))
    if command=="POST" and path==STATUS_ROUTE:
        return _json(handler,lambda p: lab.status(p.get("token")))
    if command=="POST" and path==REMOVE_ROUTE:
        return _json(handler,lambda p: lab.remove(p.get("token")))
    return False
