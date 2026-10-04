"""Public customer dashboard and federated-login HTTP surface."""
from __future__ import annotations

import html
import json
import re
import secrets
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, quote, unquote, urlsplit

import customer_accounts
import customer_ct_reports
import customer_oidc
import referral_wallet_claims
import mobile_auth_ticket

ACCOUNT_ROUTE="/compte"
PROVIDERS_ROUTE="/api/customer/providers"
ME_ROUTE="/api/customer/me"
PROFILE_ROUTE="/api/customer/profile"
LOGOUT_ROUTE="/api/customer/logout"
REPORTS_ROUTE="/api/customer/reports"
REPORT_DELETE_ROUTE="/api/customer/reports/delete"
WALLET_MOBILE_CLAIM_ROUTE="/api/customer/wallet/mobile-claim"
MOBILE_APPLE_AUTH_ROUTE="/api/mobile/auth/apple"
MOBILE_AUTH_EXCHANGE_ROUTE="/api/mobile/auth/exchange"
COOKIE_NAME="checkupauto_customer"
PUBLIC_PROVIDER_IDS=("google","apple")


def _cookie(handler, name=COOKIE_NAME) -> str:
    raw=str(handler.headers.get("Cookie") or "")
    jar=SimpleCookie()
    try:
        jar.load(raw)
    except Exception:
        return ""
    morsel=jar.get(name)
    return str(morsel.value) if morsel else ""


def _account(handler):
    token=_cookie(handler)
    if not token:
        return "",None
    try:
        account_id=customer_accounts.authenticate_session(token)
        return token,customer_accounts.profile(account_id)
    except Exception:
        return "",None


def _flow_cookie_name(provider: str, state: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}",state):
        raise customer_oidc.CustomerOIDCError("customer_oidc_state_invalid")
    return "__Host-checkupauto_oidc_"+provider+"_"+state


def _flow_cookie(provider: str, state: str, binding: str="", *, clear=False) -> str:
    # Apple's cross-site form_post callback needs SameSite=None; all cookies
    # remain host-only, Secure and HttpOnly.
    same_site="None" if provider=="apple" else "Lax"
    max_age=0 if clear else customer_oidc.FLOW_TTL_MINUTES*60
    return f"{_flow_cookie_name(provider,state)}={binding}; Path=/; Max-Age={max_age}; HttpOnly; Secure; SameSite={same_site}"


def _send_cookie_redirect(handler, location: str, session: dict, provider: str, state: str):
    token=str(session["token"])
    max_age=int(session["maxAge"])
    handler.send_response(303)
    handler.send_header("Location",location)
    handler.send_header("Cache-Control","no-store")
    handler.send_header(
        "Set-Cookie",
        f"{COOKIE_NAME}={token}; Path=/; Max-Age={max_age}; HttpOnly; Secure; SameSite=Lax",
    )
    handler.send_header("Content-Length","0")
    handler.send_header("Set-Cookie",_flow_cookie(provider,state,clear=True))
    handler.end_headers()


def _clear_cookie(handler, location="/compte"):
    handler.send_response(303)
    handler.send_header("Location",location)
    handler.send_header("Cache-Control","no-store")
    handler.send_header(
        "Set-Cookie",
        f"{COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax",
    )
    handler.send_header("Content-Length","0")
    handler.end_headers()


def _public_provider_status() -> list[dict]:
    return [provider for provider in customer_oidc.provider_status() if provider["id"] in PUBLIC_PROVIDER_IDS]


def _providers_html() -> str:
    rows=[]
    for provider in _public_provider_status():
        if provider["configured"]:
            rows.append(
                f'<a class="sso" href="/auth/customer/{html.escape(provider["id"])}">'
                f'Continuer avec {html.escape(provider["label"])}</a>'
            )
        else:
            rows.append(
                f'<span class="sso disabled">{html.escape(provider["label"])} · bientôt disponible</span>'
            )
    return "".join(rows)


def _login_page(message: str="") -> bytes:
    note=f'<p class="error">{html.escape(message)}</p>' if message else ""
    providers=_providers_html()
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>Mon compte | Checkup Auto</title>
<style>
:root{{--paper:#f6f7f2;--ink:#213b30;--muted:#6f7b72;--line:#d9dfd3;--green:#1f5443}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(140deg,#fbfcf9,var(--paper));color:var(--ink);font-family:Arial,Helvetica,sans-serif}}
main{{width:min(940px,calc(100% - 32px));margin:auto;padding:38px 0 70px}}a{{color:inherit;text-decoration:none}}
.top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:26px}}.brand{{font-weight:750;letter-spacing:-.03em}}
.card{{background:#fff;border:1px solid var(--line);padding:clamp(28px,6vw,58px);box-shadow:0 28px 80px rgba(31,84,67,.08)}}
.eyebrow{{font:10px Consolas,monospace;letter-spacing:.14em;color:var(--green)}}h1{{font:400 clamp(46px,7vw,76px)/.98 Georgia,serif;letter-spacing:-.05em;margin:16px 0 20px}}
p{{line-height:1.7;color:var(--muted)}}.providers{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:30px}}
.sso{{border:1px solid var(--line);padding:15px 17px;background:#fbfcfa;font-weight:700;text-align:center}}.sso:hover{{border-color:#9ab1a2}}
.sso.disabled{{opacity:.48}}.trust{{margin-top:26px;padding-top:20px;border-top:1px solid var(--line);font-size:11px;color:var(--muted)}}.error{{color:#8c3a31}}
@media(max-width:720px){{.providers{{grid-template-columns:1fr}}}}
</style></head><body><main><div class="top"><a class="brand" href="/">✓ CHECKUP AUTO</a><a href="/">Retour au site</a></div>
<section class="card"><div class="eyebrow">ESPACE CLIENT</div><h1>Votre véhicule, dans la durée.</h1>
<p>Retrouvez votre fidélité et l’analyse de vos rapports de contrôle technique dans un seul espace.</p>
{note}<div class="providers">{providers}</div>
<div class="trust">Connexion fédérée uniquement · aucun mot de passe CheckupAuto à mémoriser · session sécurisée et limitée dans le temps.</div>
</section></main></body></html>""".encode("utf-8")


def _dashboard_page(token: str, account: dict, nonce: str) -> bytes:
    csrf=customer_accounts.csrf_token(token)
    kind=str(account["kind"])
    pro=kind=="professional"
    display=html.escape(str(account["displayName"]))
    email=html.escape(str(account["email"]))
    company=html.escape(str(account["companyName"]))
    siret=html.escape(str(account["siret"]))
    loyalty=account["loyalty"]
    providers=" · ".join(html.escape(customer_oidc.PROVIDERS.get(str(p),{}).get("label",str(p).title())) for p in account["providers"]) or "—"
    balance=f'{int(loyalty["balanceCents"])/100:.2f} €'
    pending=f'{int(loyalty["pendingCents"])/100:.2f} €'
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow,noarchive">
<title>Tableau de bord | Checkup Auto</title>
<style>
:root{{--paper:#f6f7f2;--ink:#213b30;--muted:#6d796f;--line:#d9dfd3;--green:#1f5443;--soft:#edf1eb}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:Arial,Helvetica,sans-serif}}a{{color:inherit;text-decoration:none}}
.shell{{width:min(1240px,calc(100% - 32px));margin:auto;padding:28px 0 64px}}.top{{display:flex;justify-content:space-between;align-items:center;padding:10px 0 24px}}
.brand{{font-weight:750;letter-spacing:-.04em}}.logout{{border:0;background:none;color:var(--muted);cursor:pointer}}
.hero{{background:#fff;border:1px solid var(--line);padding:clamp(28px,5vw,52px);display:grid;grid-template-columns:1fr auto;gap:24px;align-items:end}}
.eyebrow{{font:10px Consolas,monospace;letter-spacing:.14em;color:var(--green)}}h1{{font:400 clamp(42px,6vw,70px)/.98 Georgia,serif;letter-spacing:-.045em;margin:14px 0 8px}}p{{color:var(--muted);line-height:1.6}}
.badge{{padding:9px 12px;border:1px solid #a9bcaf;background:var(--soft);font:700 9px Consolas,monospace;letter-spacing:.1em}}
.grid{{display:grid;grid-template-columns:1.2fr .8fr .8fr;gap:14px;margin-top:14px}}.panel{{background:#fff;border:1px solid var(--line);padding:24px;min-height:210px}}
.panel h2{{font:400 28px Georgia,serif;margin:8px 0 18px}}.metric{{font:400 44px Georgia,serif;letter-spacing:-.04em}}.sub{{font-size:11px;color:var(--muted)}}
.report{{border:1px dashed #aebbb2;background:#fafbf8;padding:18px;margin-top:16px}}.profile{{margin-top:14px;background:#fff;border:1px solid var(--line);padding:24px}}
form{{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}}label{{display:grid;gap:7px;font-size:11px;font-weight:700}}input,select{{padding:12px;border:1px solid var(--line);background:#fbfcfa;font:inherit}}
.actions{{grid-column:1/-1;display:flex;align-items:center;gap:14px}}button.primary{{border:0;background:var(--green);color:#fff;padding:13px 18px;font-weight:700;cursor:pointer}}#profileStatus{{font-size:11px;color:var(--muted)}}
.report-controls{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:12px}}.report-controls input{{max-width:100%;padding:8px}}
.report-list{{display:grid;gap:8px;margin-top:14px}}.report-item{{border:1px solid var(--line);background:#fff;padding:12px;display:flex;justify-content:space-between;gap:12px;align-items:center}}
.report-item button,.report-actions button{{border:1px solid var(--line);background:#fff;padding:9px 11px;cursor:pointer;color:var(--ink)}}.report-analysis{{margin-top:14px;border-top:1px solid var(--line);padding-top:14px}}
.report-analysis h3{{font:400 22px Georgia,serif;margin:12px 0 6px}}.report-analysis ul{{padding-left:18px;color:var(--muted)}}.report-actions{{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}}.report-status{{font-size:11px;color:var(--muted);margin-top:8px}}
@media(max-width:900px){{.grid{{grid-template-columns:1fr}}.hero{{grid-template-columns:1fr}}}}@media(max-width:640px){{form{{grid-template-columns:1fr}}.actions{{grid-column:1}}}}
</style></head><body><main class="shell">
<div class="top"><a class="brand" href="/">✓ CHECKUP AUTO</a><button id="logout" class="logout" type="button">Se déconnecter</button></div>
<section class="hero"><div><div class="eyebrow">TABLEAU DE BORD CLIENT</div><h1>Bonjour, {display}.</h1><p>{email} · Connexion : {providers}</p></div><span class="badge">{"PROFESSIONNEL" if pro else "PARTICULIER"}</span></section>
<div class="grid">
<section class="panel"><div class="eyebrow">MES CONTRÔLES</div><h2>Rapports et rendez-vous</h2><p><a href="/#reservation">Réserver un contrôle →</a> · <a href="https://rdv.checkupauto.fr/" rel="noreferrer">Consulter mes rendez-vous Mercure →</a></p><p class="sub">Le planning utilise son propre compte client. Le rattachement de cet historique nécessite une vérification dédiée.</p><div class="report" id="ct-report"><strong>Rapport de contrôle technique</strong><p>Scannez ou importez votre procès-verbal. L’original est traité puis supprimé; le compte conserve uniquement une version structurée et chiffrée en Markdown.</p><div class="report-controls"><input id="ctReportFile" type="file" accept="application/pdf,image/jpeg,image/png" capture="environment"><button id="ctReportUpload" class="primary" type="button">Analyser le rapport</button></div><div id="ctReportStatus" class="report-status" role="status" aria-live="polite"></div><div id="ctReportList" class="report-list"></div><div id="ctReportAnalysis" class="report-analysis" hidden></div></div></section>
<section class="panel"><div class="eyebrow">FIDÉLITÉ</div><h2>Votre cagnotte</h2><div class="metric">{balance}</div><p class="sub">En attente : {pending} · Code {html.escape(str(loyalty["referralCode"]))}</p><div class="report-actions"><button id="walletToApp" class="primary" type="button">Rattacher à l’app iOS</button></div><div id="walletToAppStatus" class="report-status" role="status" aria-live="polite"></div></section>
<section class="panel"><div class="eyebrow">PARRAINAGE</div><h2>Activité</h2><div class="metric">{int(loyalty["earnedReferrals"])}</div><p class="sub">parrainage(s) acquis · {int(loyalty["pendingReferrals"])} en attente</p></section>
</div>
<section class="profile"><div class="eyebrow">PROFIL</div><h2>Particulier ou professionnel</h2>
<form id="profileForm">
<label>Nom affiché<input id="displayName" value="{display}" maxlength="120" required></label>
<label>Statut<select id="kind"><option value="individual"{" selected" if not pro else ""}>Particulier</option><option value="professional"{" selected" if pro else ""}>Professionnel</option></select></label>
<label>Raison sociale<input id="companyName" value="{company}" maxlength="160"></label>
<label>SIRET<input id="siret" value="{siret}" inputmode="numeric" maxlength="14"></label>
<div class="actions"><button class="primary" type="submit">Enregistrer</button><span id="profileStatus"></span></div>
</form></section>
</main><script nonce="{html.escape(nonce,quote=True)}">
(()=>{{'use strict';const csrf={json.dumps(csrf)},status=document.getElementById('profileStatus'),kind=document.getElementById('kind'),company=document.getElementById('companyName'),siret=document.getElementById('siret'),reportInput=document.getElementById('ctReportFile'),reportUpload=document.getElementById('ctReportUpload'),reportStatus=document.getElementById('ctReportStatus'),reportList=document.getElementById('ctReportList'),reportAnalysis=document.getElementById('ctReportAnalysis'),walletToApp=document.getElementById('walletToApp'),walletToAppStatus=document.getElementById('walletToAppStatus');
const sync=()=>{{const pro=kind.value==='professional';company.disabled=!pro;siret.disabled=!pro;if(!pro){{company.value='';siret.value='';}}}};kind.addEventListener('change',sync);sync();
document.getElementById('profileForm').addEventListener('submit',async e=>{{e.preventDefault();status.textContent='Enregistrement…';const payload={{kind:kind.value,displayName:document.getElementById('displayName').value,companyName:company.value,siret:siret.value}};try{{const r=await fetch('{PROFILE_ROUTE}',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CheckupAuto-Customer-CSRF':csrf}},body:JSON.stringify(payload)}});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'profile_failed');status.textContent='Profil enregistré.';}}catch(e){{status.textContent='Enregistrement impossible.';}}}});
const el=(tag,text='')=>{{const node=document.createElement(tag);if(text)node.textContent=text;return node;}};
const renderReports=rows=>{{reportList.replaceChildren();for(const row of rows){{const item=el('div');item.className='report-item';const copy=el('div');copy.append(el('strong',row.controlDate||'Rapport CT'));copy.append(el('div',(row.registration||'Véhicule non identifié')+' · '+String(row.defectCount||0)+' défaut(s)'));const open=el('button','Ouvrir');open.type='button';open.addEventListener('click',()=>showReport(row.reportId));item.append(copy,open);reportList.append(item);}}if(!rows.length)reportList.append(el('div','Aucun rapport analysé.'));}};
const loadReports=async()=>{{try{{const r=await fetch('{REPORTS_ROUTE}',{{cache:'no-store',credentials:'same-origin'}});const d=await r.json();if(!r.ok||!d.ok)throw new Error();renderReports(d.reports||[]);}}catch(_e){{reportStatus.textContent='Historique des rapports indisponible.';}}}};
const showReport=async id=>{{reportStatus.textContent='Lecture du rapport…';try{{const r=await fetch('{REPORTS_ROUTE}/'+encodeURIComponent(id),{{cache:'no-store',credentials:'same-origin'}});const d=await r.json();if(!r.ok||!d.reportId)throw new Error();reportAnalysis.replaceChildren();reportAnalysis.hidden=false;reportAnalysis.append(el('h3','Analyse du contrôle technique'));reportAnalysis.append(el('p',(d.result||'Résultat non détecté')+' · '+String(d.defectCount||0)+' défaut(s) structuré(s)'));const list=el('ul');for(const finding of (d.advice||[])){{const li=el('li');const title=el('strong',finding.title||'Point à surveiller');li.append(title,document.createTextNode(' — '+(finding.prevention||'')));list.append(li);}}reportAnalysis.append(list);const actions=el('div');actions.className='report-actions';const download=el('a','Télécharger le Markdown');download.href='{REPORTS_ROUTE}/'+encodeURIComponent(id)+'?format=md';download.className='primary';const remove=el('button','Supprimer');remove.type='button';remove.addEventListener('click',async()=>{{if(!confirm('Supprimer ce rapport de votre espace client ?'))return;const rr=await fetch('{REPORT_DELETE_ROUTE}',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CheckupAuto-Customer-CSRF':csrf}},body:JSON.stringify({{reportId:id}})}});if(rr.ok){{reportAnalysis.hidden=true;await loadReports();}}}});actions.append(download,remove);reportAnalysis.append(actions);reportStatus.textContent='Analyse prête.';}}catch(_e){{reportStatus.textContent='Lecture du rapport impossible.';}}}};
reportUpload.addEventListener('click',async()=>{{const file=reportInput.files[0];if(!file){{reportStatus.textContent='Sélectionnez une photo ou un PDF.';return;}}const type=file.type||({{pdf:'application/pdf',jpg:'image/jpeg',jpeg:'image/jpeg',png:'image/png'}}[file.name.split('.').pop().toLowerCase()]||'');if(!['application/pdf','image/jpeg','image/png'].includes(type)){{reportStatus.textContent='Format accepté : PDF, JPEG ou PNG.';return;}}reportUpload.disabled=true;reportStatus.textContent='Extraction et analyse du rapport…';try{{const r=await fetch('{REPORTS_ROUTE}',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':type,'X-CheckupAuto-Customer-CSRF':csrf,'X-CheckupAuto-Filename':encodeURIComponent(file.name)}},body:file}});const d=await r.json();if(!r.ok||!d.reportId)throw new Error(d.error||'upload_failed');reportInput.value='';await loadReports();await showReport(d.reportId);}}catch(_e){{reportStatus.textContent='Analyse impossible. Vérifiez la lisibilité du document.';}}finally{{reportUpload.disabled=false;}}}});
walletToApp.addEventListener('click',async()=>{{walletToApp.disabled=true;walletToAppStatus.textContent='Création du rattachement sécurisé…';try{{const r=await fetch('{WALLET_MOBILE_CLAIM_ROUTE}',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CheckupAuto-Customer-CSRF':csrf}},body:'{{}}'}});const d=await r.json();if(!r.ok||!d.ok||!d.claimUrl)throw new Error(d.error||'claim_failed');walletToAppStatus.textContent='Ouverture de Checkup Auto…';location.assign(d.claimUrl);}}catch(_e){{walletToAppStatus.textContent='Rattachement indisponible. Réessayez.';walletToApp.disabled=false;}}}});
loadReports();
document.getElementById('logout').addEventListener('click',async()=>{{await fetch('{LOGOUT_ROUTE}',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CheckupAuto-Customer-CSRF':csrf}},body:'{{}}'}});location.assign('{ACCOUNT_ROUTE}');}});
}})();</script></body></html>""".encode("utf-8")


def _browser_origin(handler) -> str:
    host = str(handler.headers.get("Host") or "").strip().lower()
    if (
        not host
        or len(host) > 255
        or "/" in host
        or "@" in host
        or not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]{1,5})?", host)
    ):
        raise ValueError("customer_origin_invalid")
    return "https://" + host


def _same_origin(handler) -> bool:
    if handler.headers.get("Sec-Fetch-Site","")=="cross-site":
        return False
    return bool(handler._admin_origin_ok())


def _json_body(handler) -> dict:
    if handler.headers.get("Content-Type","").split(";",1)[0].strip().lower()!="application/json":
        raise ValueError("customer_content_type_invalid")
    payload=handler._read_json()
    if not isinstance(payload,dict):
        raise ValueError("customer_payload_invalid")
    return payload


def handle(handler) -> bool:
    parsed=urlsplit(handler.path)
    path=parsed.path
    command=getattr(handler,"command","")

    if command=="GET" and path==ACCOUNT_ROUTE:
        token,account=_account(handler)
        if not account:
            handler.send_bytes(_login_page(),"text/html; charset=utf-8",200,"no-store",{"X-Robots-Tag":"noindex, nofollow, noarchive"})
            return True
        nonce=secrets.token_urlsafe(18)
        handler._csp_nonce=nonce
        handler.send_bytes(_dashboard_page(token,account,nonce),"text/html; charset=utf-8",200,"no-store",{"X-Robots-Tag":"noindex, nofollow, noarchive"})
        return True

    if command=="GET" and path==PROVIDERS_ROUTE:
        handler.send_json({"ok":True,"providers":_public_provider_status()})
        return True

    if command=="GET" and re.fullmatch(r"/auth/customer/(google|apple)",path):
        provider=path.rsplit("/",1)[-1]
        try:
            binding=secrets.token_urlsafe(32)
            mobile=(provider=="google" and (parse_qs(parsed.query).get("mobile") or [""])[0]=="1")
            target=customer_oidc.begin(provider,_browser_origin(handler),browser_binding=binding,mobile=mobile)
            state=parse_qs(urlsplit(target).query)["state"][0]
            handler.send_response(302)
            handler.send_header("Location",target)
            handler.send_header("Cache-Control","no-store")
            handler.send_header("Set-Cookie",_flow_cookie(provider,state,binding))
            handler.send_header("Content-Length","0")
            handler.end_headers()
        except customer_oidc.CustomerOIDCError:
            handler.send_bytes(_login_page("Ce fournisseur de connexion n’est pas encore configuré."),"text/html; charset=utf-8",503,"no-store")
        return True

    callback=re.fullmatch(r"/auth/customer/(google|apple)/callback",path)
    if callback and command in {"GET","POST"}:
        provider=callback.group(1)
        state=""
        try:
            if command=="POST":
                if provider!="apple" or str(handler.headers.get("Content-Type") or "").split(";",1)[0].lower()!="application/x-www-form-urlencoded":
                    raise customer_oidc.CustomerOIDCError("customer_oidc_callback_invalid")
                length=int(handler.headers.get("Content-Length") or "0")
                if not 0<length<=16384:
                    raise customer_oidc.CustomerOIDCError("customer_oidc_callback_invalid")
                params=parse_qs(handler.rfile.read(length).decode("utf-8"),keep_blank_values=True,max_num_fields=20)
            else:
                if provider=="apple" or len(parsed.query)>16384:
                    raise customer_oidc.CustomerOIDCError("customer_oidc_callback_invalid")
                params=parse_qs(parsed.query,keep_blank_values=True,max_num_fields=20)
            error=(params.get("error") or [""])[0]
            if error:
                raise customer_oidc.CustomerOIDCError("customer_oidc_provider_error")
            if len(params.get("state",[]))!=1 or len(params.get("code",[]))!=1:
                raise customer_oidc.CustomerOIDCError("customer_oidc_callback_invalid")
            state=(params.get("state") or [""])[0]
            code=(params.get("code") or [""])[0]
            result=customer_oidc.complete(provider,state,code,
                browser_binding=_cookie(handler,_flow_cookie_name(provider,state)),origin=_browser_origin(handler))
            if provider=="google" and result.get("mobile"):
                ticket=mobile_auth_ticket.issue(result["session"]["token"])
                handler.send_redirect("checkupauto://auth/google?ticket="+quote(ticket,safe=""),303)
            else:
                _send_cookie_redirect(handler,ACCOUNT_ROUTE,result["session"],provider,state)
        except Exception:
            headers={"Set-Cookie":_flow_cookie(provider,state,clear=True)} if re.fullmatch(r"[A-Za-z0-9_-]{32,128}",state) else {}
            handler.send_bytes(_login_page("La connexion n’a pas pu être finalisée. Réessayez avec le fournisseur utilisé lors de votre inscription."),"text/html; charset=utf-8",400,"no-store",headers)
        return True

    if path==MOBILE_AUTH_EXCHANGE_ROUTE:
        if command!="POST":
            handler.send_json({"ok":False,"error":"customer_method_not_allowed"},405)
            return True
        try:
            payload=_json_body(handler)
            if set(payload)!={"ticket"}:
                raise ValueError
            session_token=mobile_auth_ticket.consume(payload.get("ticket"))
            account_id=customer_accounts.authenticate_session(session_token)
            handler.send_json({"ok":True,"accountId":account_id,"sessionToken":session_token})
        except Exception:
            handler.send_json({"ok":False,"error":"mobile_auth_ticket_invalid"},401)
        return True

    if path==MOBILE_APPLE_AUTH_ROUTE:
        if command!="POST":
            handler.send_json({"ok":False,"error":"customer_method_not_allowed"},405)
            return True
        try:
            payload=_json_body(handler)
            allowed={"identityToken","authorizationCode","userIdentifier","givenName","familyName","email","nonce"}
            if not set(payload).issubset(allowed) or not {"identityToken","authorizationCode","userIdentifier"}.issubset(payload):
                raise ValueError
            claims=customer_oidc.verify_native_apple_identity(
                payload.get("identityToken"),
                client_id="fr.checkupauto.reminder",
                nonce=payload.get("nonce") or "",
            )
            subject=str(claims.get("sub") or "")
            if not hmac.compare_digest(subject,str(payload.get("userIdentifier") or "")):
                raise customer_oidc.CustomerOIDCError("customer_oidc_subject_mismatch")
            email=str(claims.get("email") or payload.get("email") or "")
            if str(claims.get("email_verified") or "").lower() not in {"true","1"} or not email:
                raise customer_oidc.CustomerOIDCError("customer_oidc_email_unverified")
            name=" ".join(x for x in [str(payload.get("givenName") or "").strip(),str(payload.get("familyName") or "").strip()] if x)
            if not name:
                name=email.split("@",1)[0][:120] or "Client Checkup Auto"
            account=customer_accounts.create_from_verified_identity(
                "apple",subject,email,name,email_verified=True
            )
            session=customer_accounts.issue_session(account["accountId"])
            handler.send_json({
                "ok":True,
                "accountId":account["accountId"],
                "sessionToken":session["token"],
                "expiresAt":session["expiresAt"],
            })
        except Exception:
            handler.send_json({"ok":False,"error":"customer_apple_auth_failed"},401)
        return True

    report_match=re.fullmatch(r"/api/customer/reports/([0-9a-f-]{36})",path)
    if path in {REPORTS_ROUTE,REPORT_DELETE_ROUTE} or report_match:
        token,account=_account(handler)
        if not token or not account:
            handler.send_json({"ok":False,"error":"customer_auth_required"},401)
            return True
        account_id=account["accountId"]

        if command=="GET" and path==REPORTS_ROUTE:
            handler.send_json({"ok":True,"reports":customer_ct_reports.list_reports(account_id)})
            return True

        if command=="GET" and report_match:
            try:
                report=customer_ct_reports.get_report(account_id,report_match.group(1))
                query=parse_qs(parsed.query,keep_blank_values=True)
                if query and set(query)!={"format"}:
                    raise customer_ct_reports.CTReportError("ct_report_query_invalid")
                format_value=(query.get("format") or [""])[0]
                if format_value:
                    if format_value!="md":
                        raise customer_ct_reports.CTReportError("ct_report_format_invalid")
                    handler.send_bytes(
                        report["markdown"].encode("utf-8"),
                        "text/markdown; charset=utf-8",
                        200,
                        "no-store",
                        {"Content-Disposition":f'attachment; filename="rapport-{report["reportId"]}.md"'},
                    )
                else:
                    handler.send_json(report)
            except customer_ct_reports.CTReportError:
                handler.send_json({"ok":False,"error":"ct_report_not_found"},404)
            return True

        if command!="POST":
            handler.send_json({"ok":False,"error":"customer_method_not_allowed"},405)
            return True
        if not _same_origin(handler):
            handler.send_json({"ok":False,"error":"customer_origin_not_allowed"},403)
            return True
        if not customer_accounts.verify_csrf(token,handler.headers.get("X-CheckupAuto-Customer-CSRF")):
            handler.send_json({"ok":False,"error":"customer_csrf_invalid"},403)
            return True

        if path==REPORT_DELETE_ROUTE:
            try:
                payload=_json_body(handler)
                if set(payload)!={"reportId"}:
                    raise ValueError
                removed=customer_ct_reports.delete_report(account_id,payload.get("reportId"))
                handler.send_json({"ok":True,"removed":removed})
            except Exception:
                handler.send_json({"ok":False,"error":"ct_report_delete_invalid"},400)
            return True

        if path==REPORTS_ROUTE:
            if handler.headers.get("Transfer-Encoding"):
                handler.send_json({"ok":False,"error":"ct_report_transfer_encoding_invalid"},400)
                return True
            try:
                length=int(handler.headers.get("Content-Length",""))
            except (TypeError,ValueError):
                length=0
            if not 1<=length<=customer_ct_reports.MAX_UPLOAD_BYTES:
                handler.send_json({"ok":False,"error":"ct_report_size_invalid"},413)
                return True
            content_type=handler.headers.get("Content-Type","")
            filename=unquote(str(handler.headers.get("X-CheckupAuto-Filename") or "rapport"))
            raw=handler.rfile.read(length)
            if len(raw)!=length:
                handler.send_json({"ok":False,"error":"ct_report_upload_incomplete"},400)
                return True
            try:
                created=customer_ct_reports.ingest(account_id,filename,content_type,raw)
                handler.send_json(created,201)
            except customer_ct_reports.CTReportError as exc:
                code=str(exc)
                status=503 if code=="ct_extraction_unavailable" else (422 if code in {"ct_extraction_failed","ct_extraction_empty"} else 400)
                handler.send_json({"ok":False,"error":code},status)
            except Exception:
                handler.send_json({"ok":False,"error":"ct_report_processing_unavailable"},503)
            return True

    if path in {ME_ROUTE,PROFILE_ROUTE,LOGOUT_ROUTE,WALLET_MOBILE_CLAIM_ROUTE}:
        token,account=_account(handler)
        if not token or not account:
            handler.send_json({"ok":False,"error":"customer_auth_required"},401)
            return True

        if path==ME_ROUTE:
            if command!="GET":
                handler.send_json({"ok":False,"error":"customer_method_not_allowed"},405)
            else:
                view=dict(account)
                view["csrfToken"]=customer_accounts.csrf_token(token)
                handler.send_json(view)
            return True

        if command!="POST":
            handler.send_json({"ok":False,"error":"customer_method_not_allowed"},405)
            return True
        if not _same_origin(handler):
            handler.send_json({"ok":False,"error":"customer_origin_not_allowed"},403)
            return True
        if not customer_accounts.verify_csrf(token,handler.headers.get("X-CheckupAuto-Customer-CSRF")):
            handler.send_json({"ok":False,"error":"customer_csrf_invalid"},403)
            return True

        if path==WALLET_MOBILE_CLAIM_ROUTE:
            try:
                payload=_json_body(handler)
                if payload:
                    raise ValueError
                claim=referral_wallet_claims.issue(account["loyalty"]["referralCode"])
                claim_url=_browser_origin(handler)+"/app/claim#token="+quote(str(claim["claimToken"]),safe="")
                handler.send_json({
                    "ok":True,
                    "claimType":"referral_wallet",
                    "claimUrl":claim_url,
                    "expiresAt":claim["expiresAt"],
                    "rawTokenPersisted":False,
                },201)
            except Exception:
                handler.send_json({"ok":False,"error":"customer_wallet_claim_unavailable"},400)
            return True

        if path==LOGOUT_ROUTE:
            try:
                _json_body(handler)
            except ValueError:
                handler.send_json({"ok":False,"error":"customer_payload_invalid"},400)
                return True
            customer_accounts.close_session(token)
            handler.send_json({"ok":True},headers={"Set-Cookie":f"{COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax"})
            return True

        try:
            payload=_json_body(handler)
            if set(payload)!={"kind","displayName","companyName","siret"}:
                raise ValueError
            updated=customer_accounts.update_profile(
                account["accountId"],
                kind=payload.get("kind"),
                display_name=payload.get("displayName"),
                company_name=payload.get("companyName"),
                siret=payload.get("siret"),
            )
            handler.send_json(updated)
        except Exception:
            handler.send_json({"ok":False,"error":"customer_profile_invalid"},400)
        return True

    return False
