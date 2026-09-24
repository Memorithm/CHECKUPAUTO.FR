"""HTTP surface for the staging reservation + payment rehearsal."""
from __future__ import annotations

import html
import json
import secrets
from urllib.parse import urlsplit

import payment_test_lab as lab

PAGE_ROUTE="/payment/test"
PROVIDER_ROUTE="/payment/test/provider"
SESSION_ROUTE="/api/payment-test/session"
CREATE_ROUTE="/api/payment-test/create"
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
<div class="card"><small>STAGING · AUCUN DÉBIT BANCAIRE</small><h1>Test réservation + paiement</h1>
<p>Ce parcours crée un vrai rendez-vous <strong>synthétique</strong> dans Mercure puis exerce le domaine de paiement CheckupAuto avec un résultat Payline simulé. Aucune banque n’est appelée.</p></div>
<div class="card">
<div class="grid">
<label>Prestation<select id="service"><option value="technical">Contrôle technique · 80 €</option><option value="fitted">Véhicule aménagé · 90 €</option></select></label>
<label>Date<input id="date" type="date"></label>
</div>
<p><button id="load" type="button" class="secondary">Charger les créneaux Mercure</button></p>
<div id="slots" class="slots"></div>
<label><input id="terms" type="checkbox"> J’ai lu et j’accepte les <a href="/cgv" target="_blank" rel="noopener">CGV</a> pour ce test.</label>
<label><input id="immediate" type="checkbox"> J’accepte l’exécution immédiate dans le cadre de ce test de parcours.</label>
<p><button id="create" type="button" disabled>Créer le rendez-vous test et préparer le paiement</button></p>
<div id="status" class="status">Initialisation de la session de test…</div>
</div>
</main><script nonce="{n}">
(()=>{{'use strict';
const $=id=>document.getElementById(id),service=$('service'),date=$('date'),slots=$('slots'),status=$('status'),
 load=$('load'),create=$('create'),terms=$('terms'),immediate=$('immediate');
let token='',selected='';
const tomorrow=new Date(Date.now()+86400000);date.value=tomorrow.toISOString().slice(0,10);
const post=async(url,payload)=>{{const r=await fetch(url,{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(payload)}});const d=await r.json().catch(()=>({{}}));if(!r.ok)throw new Error(d.error||'request_failed');return d;}};
const refreshCreate=()=>{{create.disabled=!(token&&selected&&terms.checked&&immediate.checked)}};
terms.addEventListener('change',refreshCreate);immediate.addEventListener('change',refreshCreate);
(async()=>{{try{{const d=await post('{SESSION_ROUTE}',{{}});token=d.token;status.textContent='Session prête. Choisissez une date et un créneau.';}}catch(e){{status.textContent='Impossible de créer la session test : '+e.message;}}}})();
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
for(const b of document.querySelectorAll('[data-outcome]'))b.addEventListener('click',async()=>{{for(const x of document.querySelectorAll('[data-outcome]'))x.disabled=true;status.textContent='Application du résultat Payline simulé…';try{{const d=await post('{RESULT_ROUTE}',{{token,paymentId,outcome:b.dataset.outcome}});status.textContent='Résultat vérifié : '+d.state+' · '+(d.amountCents/100).toFixed(2)+' EUR. Aucun débit bancaire réel.';}}catch(e){{status.textContent='Erreur : '+e.message;}}finally{{for(const x of document.querySelectorAll('[data-outcome]'))x.disabled=false;}}}});
cleanup.addEventListener('click',async()=>{{cleanup.disabled=true;try{{const d=await post('{REMOVE_ROUTE}',{{token}});status.textContent='Rendez-vous test Mercure supprimé.';}}catch(e){{status.textContent='Suppression impossible : '+e.message;cleanup.disabled=false;}}}});
}})();</script></body></html>""".encode("utf-8")
    handler.send_bytes(body,"text/html; charset=utf-8",200,"no-store",{"X-Robots-Tag":"noindex, nofollow, noarchive"})
    return True


def handle(handler) -> bool:
    parsed=urlsplit(handler.path)
    path=parsed.path
    command=getattr(handler,"command","")
    if command=="GET" and path==PAGE_ROUTE:
        return _page(handler)
    if command=="GET" and path==PROVIDER_ROUTE:
        return _provider_page(handler)
    if command=="POST" and path==SESSION_ROUTE:
        return _json(handler,lambda payload: lab.create_session(),created=True)
    if command=="POST" and path==CREATE_ROUTE:
        return _json(handler,lambda p: lab.create_reservation(
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
