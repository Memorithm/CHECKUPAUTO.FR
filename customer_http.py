"""Public customer dashboard and federated-login HTTP surface."""
from __future__ import annotations

from responsive_ui import FORM_RESPONSIVE_CSS

import hmac
import html
import json
import re
import secrets
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

import customer_accounts
import customer_ct_reports
import customer_oidc
import referral_wallet_claims
import mobile_auth_ticket
import site_config_store

ACCOUNT_ROUTE="/compte"
CONTACT_ROUTE="/contact"
PASSAGE_ROUTE="/compte/reserver"
PASSAGE_CONFIRM_ROUTE="/api/customer/passage/confirm"
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
GOOGLE_REVIEW_FALLBACK_URL="https://search.google.com/local/writereview?placeid=ChIJZ82oNlGS5kcRj99QzDs2Fwo"


def _google_review_url() -> str:
    try:
        raw=str(
            site_config_store.load().get("business",{}).get("googleReviewUrl")
            or GOOGLE_REVIEW_FALLBACK_URL
        ).strip()
        parsed=urlsplit(raw)
        host=(parsed.hostname or "").lower()
        valid=(
            parsed.scheme=="https"
            and host in {"search.google.com","g.page"}
            and parsed.port in (None,443)
            and not parsed.username
            and not parsed.password
            and not parsed.fragment
        )
        if host=="search.google.com":
            valid=valid and parsed.path=="/local/writereview" and parsed.query.startswith("placeid=")
        if valid:
            return raw
    except Exception:
        pass
    return GOOGLE_REVIEW_FALLBACK_URL


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


def _providers_html(return_to: str="") -> str:
    rows=[]
    suffix=("?"+urlencode({"returnTo":return_to})) if return_to else ""
    for provider in _public_provider_status():
        if provider["configured"]:
            rows.append(
                f'<a class="sso" href="/auth/customer/{html.escape(provider["id"])}{html.escape(suffix,quote=True)}">'
                f'Continuer avec {html.escape(provider["label"])}</a>'
            )
        else:
            rows.append(
                f'<span class="sso disabled">{html.escape(provider["label"])} · bientôt disponible</span>'
            )
    return "".join(rows)


def _login_page(message: str="", info: str="", return_to: str="") -> bytes:
    note=f'<p class="error">{html.escape(message)}</p>' if message else ""
    info_note=f'<p class="info">{html.escape(info)}</p>' if info else ""
    providers=_providers_html(return_to)
    heading="Connectez-vous ou créez votre compte." if return_to else "Votre véhicule, dans la durée."
    intro=(
        "Votre créneau est conservé. Si c’est votre première connexion, votre compte Checkup Auto est créé automatiquement avec votre identité Google ou Apple."
        if return_to else
        "Retrouvez votre fidélité et l’analyse de vos rapports de contrôle technique dans un seul espace."
    )
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
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
.sso.disabled{{opacity:.48}}.trust{{margin-top:26px;padding-top:20px;border-top:1px solid var(--line);font-size:11px;color:var(--muted)}}.error{{color:#8c3a31}}.info{{padding:14px 16px;border-left:3px solid var(--green);background:#edf1eb;color:var(--ink)}}
@media(max-width:720px){{.providers{{grid-template-columns:1fr}}.top{{align-items:flex-start;gap:12px;flex-direction:column}}}}@media(max-width:520px){{main{{width:min(100% - 24px,940px);padding:24px 0 44px}}.card{{padding:24px}}h1{{font-size:clamp(38px,13vw,52px)}}.sso{{min-height:46px;display:grid;place-items:center}}}}
{FORM_RESPONSIVE_CSS}
</style></head><body><main><div class="top"><a class="brand" href="/">✓ CHECKUP AUTO</a><a href="/">Retour au site</a></div>
<section class="card"><div class="eyebrow">ESPACE CLIENT</div><h1>{html.escape(heading)}</h1>
<p>{html.escape(intro)}</p>
{info_note}{note}<div class="providers">{providers}</div>
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
    phone=html.escape(str(account.get("phone") or ""))
    address1=html.escape(str(account.get("addressLine1") or ""))
    address2=html.escape(str(account.get("addressLine2") or ""))
    postal=html.escape(str(account.get("postalCode") or ""))
    city=html.escape(str(account.get("city") or ""))
    loyalty=account["loyalty"]
    providers=" · ".join(html.escape(customer_oidc.PROVIDERS.get(str(p),{}).get("label",str(p).title())) for p in account["providers"]) or "—"
    balance=f'{int(loyalty["balanceCents"])/100:.2f} €'
    pending=f'{int(loyalty["pendingCents"])/100:.2f} €'
    google_review_url=html.escape(_google_review_url(),quote=True)
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow,noarchive">
<title>Tableau de bord | Checkup Auto</title>
<style>
:root{{--paper:#f6f7f2;--ink:#213b30;--muted:#6d796f;--line:#d9dfd3;--green:#1f5443;--soft:#edf1eb}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:Arial,Helvetica,sans-serif}}a{{color:inherit;text-decoration:none}}
.shell{{width:min(1240px,calc(100% - 32px));margin:auto;padding:28px 0 64px}}.top{{display:flex;justify-content:space-between;align-items:center;padding:10px 0 24px}}
.brand{{font-weight:750;letter-spacing:-.04em}}.top-actions{{display:flex;gap:16px;align-items:center}}.contact-link{{color:var(--green);font-weight:700}}.logout{{border:0;background:none;color:var(--muted);cursor:pointer}}
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
.feedback{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}}.feedback-card{{background:#fff;border:1px solid var(--line);padding:24px}}.feedback-card h2{{font:400 28px Georgia,serif;margin:8px 0 12px}}.feedback-card .cta{{display:inline-block;margin-top:8px;border:1px solid var(--green);padding:12px 15px;font-weight:700;color:var(--green)}}.feedback-card .cta.primary{{background:var(--green);color:#fff}}.feedback-note{{font-size:11px;color:var(--muted)}}.review-rating{{display:flex;gap:4px;margin:14px 0 6px}}.review-star{{border:0;background:transparent;color:#a7ada8;font-size:34px;line-height:1;padding:2px;cursor:pointer}}.review-star.selected{{color:#c78b16}}.review-star:focus-visible{{outline:2px solid var(--green);outline-offset:3px}}
@media(max-width:900px){{.grid,.feedback{{grid-template-columns:1fr}}.hero{{grid-template-columns:1fr}}}}@media(max-width:700px){{.shell{{width:min(100% - 24px,1240px);padding:18px 0 48px}}.top{{align-items:flex-start;gap:14px;flex-direction:column}}.top-actions{{width:100%;gap:12px;flex-wrap:wrap;justify-content:space-between}}.hero,.panel,.profile,.feedback-card{{padding:20px}}.report-item{{align-items:stretch;flex-direction:column}}.report-item button{{min-height:44px;width:100%}}.report-controls>*{{max-width:100%}}}}@media(max-width:640px){{form{{grid-template-columns:1fr}}.actions{{grid-column:1}}}}@media(max-width:480px){{h1{{font-size:clamp(38px,13vw,52px)}}.actions,.report-actions{{align-items:stretch;flex-direction:column}}.actions button,.report-actions button,.report-actions a,.report-controls button{{width:100%;min-height:44px;text-align:center}}.metric{{font-size:38px}}.review-rating{{justify-content:space-between;max-width:260px}}}}
{FORM_RESPONSIVE_CSS}
</style></head><body><main class="shell">
<div class="top"><a class="brand" href="/">✓ CHECKUP AUTO</a><div class="top-actions"><a class="contact-link" href="{CONTACT_ROUTE}">Nous contacter</a><button id="logout" class="logout" type="button">Se déconnecter</button></div></div>
<section class="hero"><div><div class="eyebrow">TABLEAU DE BORD CLIENT</div><h1>Bonjour, {display}.</h1><p>{email} · Connexion : {providers}</p></div><span class="badge">{"PROFESSIONNEL" if pro else "PARTICULIER"}</span></section>
<div class="grid">
<section class="panel"><div class="eyebrow">MES CONTRÔLES</div><h2>Rapports et rendez-vous</h2><p><a href="/#reservation">Réserver un contrôle →</a> · <a href="https://rdv.checkupauto.fr/" rel="noreferrer">Consulter mes rendez-vous Mercure →</a></p><p class="sub">Le planning utilise son propre compte client. Le rattachement de cet historique nécessite une vérification dédiée.</p><div class="report" id="ct-report"><strong>Rapport de contrôle technique</strong><p>Scannez ou importez votre procès-verbal. L’original est traité puis supprimé; le compte conserve uniquement une version structurée et chiffrée en Markdown.</p><div class="report-controls"><input id="ctReportFile" type="file" accept="application/pdf,image/jpeg,image/png" capture="environment"><button id="ctReportUpload" class="primary" type="button">Analyser le rapport</button></div><div id="ctReportStatus" class="report-status" role="status" aria-live="polite"></div><div id="ctReportList" class="report-list"></div><div id="ctReportAnalysis" class="report-analysis" hidden></div></div></section>
<section class="panel"><div class="eyebrow">FIDÉLITÉ</div><h2>Votre cagnotte</h2><div class="metric">{balance}</div><p class="sub">En attente : {pending} · Code {html.escape(str(loyalty["referralCode"]))}</p><div class="report-actions"><button id="walletToApp" class="primary" type="button">Rattacher à l’app iOS</button></div><div id="walletToAppStatus" class="report-status" role="status" aria-live="polite"></div></section>
<section class="panel"><div class="eyebrow">PARRAINAGE</div><h2>Activité</h2><div class="metric">{int(loyalty["earnedReferrals"])}</div><p class="sub">parrainage(s) acquis · {int(loyalty["pendingReferrals"])} en attente</p></section>
</div>
<section class="feedback" aria-label="Avis et suggestions">
<article class="feedback-card"><div class="eyebrow">VOTRE AVIS COMPTE</div><h2>Laisser un avis Google</h2><p>Partagez librement votre expérience avec Checkup Auto. Les avis ne sont ni filtrés ni liés à une récompense.</p><div class="review-rating" role="radiogroup" aria-label="Votre note"><button class="review-star selected" type="button" data-rating="1" role="radio" aria-checked="false" aria-label="1 étoile">★</button><button class="review-star selected" type="button" data-rating="2" role="radio" aria-checked="false" aria-label="2 étoiles">★</button><button class="review-star selected" type="button" data-rating="3" role="radio" aria-checked="false" aria-label="3 étoiles">★</button><button class="review-star selected" type="button" data-rating="4" role="radio" aria-checked="false" aria-label="4 étoiles">★</button><button class="review-star selected" type="button" data-rating="5" role="radio" aria-checked="true" aria-label="5 étoiles">★</button></div><p id="reviewRatingText" class="feedback-note">5 étoiles sélectionnées par défaut.</p><a class="cta primary" href="{google_review_url}" target="_blank" rel="noopener noreferrer external">Donner mon avis sur Google ↗</a><p class="feedback-note">La note affichée ici est modifiable avant de continuer. Google demande la confirmation finale de la note. Le commentaire reste vide tant que vous ne le saisissez pas dans Google.</p></article>
<article class="feedback-card"><div class="eyebrow">VOS IDÉES</div><h2>Faire une suggestion</h2><p>Une amélioration, une idée de service ou un point à simplifier ? Envoyez-nous votre suggestion depuis votre compte client.</p><a class="cta" href="{CONTACT_ROUTE}?intent=suggestion">Faire une suggestion →</a><p class="feedback-note">Votre suggestion reste liée à votre compte pour permettre un suivi sécurisé.</p></article>
</section>
<section class="profile"><div class="eyebrow">PROFIL ET COORDONNÉES</div><h2>Vos informations de contact</h2><p class="sub">Nom, e-mail vérifié, téléphone et adresse sont disponibles pour sécuriser le suivi de vos demandes sans les ressaisir dans chaque message.</p>
<form id="profileForm">
<label>Nom affiché<input id="displayName" value="{display}" maxlength="120" required></label>
<label>Statut<select id="kind"><option value="individual"{" selected" if not pro else ""}>Particulier</option><option value="professional"{" selected" if pro else ""}>Professionnel</option></select></label>
<label>Raison sociale<input id="companyName" value="{company}" maxlength="160"></label>
<label>SIRET<input id="siret" value="{siret}" inputmode="numeric" maxlength="14"></label>
<label>Téléphone<input id="phone" value="{phone}" autocomplete="tel" maxlength="32"></label>
<label>Adresse<input id="addressLine1" value="{address1}" autocomplete="street-address" maxlength="180"></label>
<label>Complément d’adresse<input id="addressLine2" value="{address2}" maxlength="180"></label>
<label>Code postal<input id="postalCode" value="{postal}" autocomplete="postal-code" maxlength="16"></label>
<label>Ville<input id="city" value="{city}" autocomplete="address-level2" maxlength="120"></label>
<label>E-mail vérifié<input value="{email}" readonly aria-readonly="true"></label>
<div class="actions"><button class="primary" type="submit">Enregistrer</button><span id="profileStatus"></span></div>
</form></section>
</main><script nonce="{html.escape(nonce,quote=True)}">
(()=>{{'use strict';const csrf={json.dumps(csrf)},status=document.getElementById('profileStatus'),kind=document.getElementById('kind'),company=document.getElementById('companyName'),siret=document.getElementById('siret'),reportInput=document.getElementById('ctReportFile'),reportUpload=document.getElementById('ctReportUpload'),reportStatus=document.getElementById('ctReportStatus'),reportList=document.getElementById('ctReportList'),reportAnalysis=document.getElementById('ctReportAnalysis'),walletToApp=document.getElementById('walletToApp'),walletToAppStatus=document.getElementById('walletToAppStatus'),reviewStars=[...document.querySelectorAll('.review-star')],reviewRatingText=document.getElementById('reviewRatingText');
const sync=()=>{{const pro=kind.value==='professional';company.disabled=!pro;siret.disabled=!pro;if(!pro){{company.value='';siret.value='';}}}};kind.addEventListener('change',sync);sync();
const setReviewRating=rating=>{{reviewStars.forEach(star=>{{const value=Number(star.dataset.rating);star.classList.toggle('selected',value<=rating);star.setAttribute('aria-checked',String(value===rating));}});reviewRatingText.textContent=rating+' étoile'+(rating>1?'s':'')+' sélectionnée'+(rating>1?'s':'')+'.';}};
reviewStars.forEach(star=>star.addEventListener('click',()=>setReviewRating(Number(star.dataset.rating))));
document.getElementById('profileForm').addEventListener('submit',async e=>{{e.preventDefault();status.textContent='Enregistrement…';const payload={{kind:kind.value,displayName:document.getElementById('displayName').value,companyName:company.value,siret:siret.value,phone:document.getElementById('phone').value,addressLine1:document.getElementById('addressLine1').value,addressLine2:document.getElementById('addressLine2').value,postalCode:document.getElementById('postalCode').value,city:document.getElementById('city').value}};try{{const r=await fetch('{PROFILE_ROUTE}',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CheckupAuto-Customer-CSRF':csrf}},body:JSON.stringify(payload)}});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'profile_failed');status.textContent='Profil enregistré.';}}catch(e){{status.textContent='Enregistrement impossible.';}}}});
const el=(tag,text='')=>{{const node=document.createElement(tag);if(text)node.textContent=text;return node;}};
const renderReports=rows=>{{reportList.replaceChildren();for(const row of rows){{const item=el('div');item.className='report-item';const copy=el('div');copy.append(el('strong',row.controlDate||'Rapport CT'));copy.append(el('div',(row.registration||'Véhicule non identifié')+' · '+String(row.defectCount||0)+' défaut(s)'));const open=el('button','Ouvrir');open.type='button';open.addEventListener('click',()=>showReport(row.reportId));item.append(copy,open);reportList.append(item);}}if(!rows.length)reportList.append(el('div','Aucun rapport analysé.'));}};
const loadReports=async()=>{{try{{const r=await fetch('{REPORTS_ROUTE}',{{cache:'no-store',credentials:'same-origin'}});const d=await r.json();if(!r.ok||!d.ok)throw new Error();renderReports(d.reports||[]);}}catch(_e){{reportStatus.textContent='Historique des rapports indisponible.';}}}};
const showReport=async id=>{{reportStatus.textContent='Lecture du rapport…';try{{const r=await fetch('{REPORTS_ROUTE}/'+encodeURIComponent(id),{{cache:'no-store',credentials:'same-origin'}});const d=await r.json();if(!r.ok||!d.reportId)throw new Error();reportAnalysis.replaceChildren();reportAnalysis.hidden=false;reportAnalysis.append(el('h3','Analyse du contrôle technique'));reportAnalysis.append(el('p',(d.result||'Résultat non détecté')+' · '+String(d.defectCount||0)+' défaut(s) structuré(s)'));const list=el('ul');for(const finding of (d.advice||[])){{const li=el('li');const title=el('strong',finding.title||'Point à surveiller');li.append(title,document.createTextNode(' — '+(finding.prevention||'')));list.append(li);}}reportAnalysis.append(list);const actions=el('div');actions.className='report-actions';const download=el('a','Télécharger le Markdown');download.href='{REPORTS_ROUTE}/'+encodeURIComponent(id)+'?format=md';download.className='primary';const remove=el('button','Supprimer');remove.type='button';remove.addEventListener('click',async()=>{{if(!confirm('Supprimer ce rapport de votre espace client ?'))return;const rr=await fetch('{REPORT_DELETE_ROUTE}',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CheckupAuto-Customer-CSRF':csrf}},body:JSON.stringify({{reportId:id}})}});if(rr.ok){{reportAnalysis.hidden=true;await loadReports();}}}});actions.append(download,remove);reportAnalysis.append(actions);reportStatus.textContent='Analyse prête.';}}catch(_e){{reportStatus.textContent='Lecture du rapport impossible.';}}}};
reportUpload.addEventListener('click',async()=>{{const file=reportInput.files[0];if(!file){{reportStatus.textContent='Sélectionnez une photo ou un PDF.';return;}}const type=file.type||({{pdf:'application/pdf',jpg:'image/jpeg',jpeg:'image/jpeg',png:'image/png'}}[file.name.split('.').pop().toLowerCase()]||'');if(!['application/pdf','image/jpeg','image/png'].includes(type)){{reportStatus.textContent='Format accepté : PDF, JPEG ou PNG.';return;}}reportUpload.disabled=true;reportStatus.textContent='Extraction et analyse du rapport…';try{{const r=await fetch('{REPORTS_ROUTE}',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':type,'X-CheckupAuto-Customer-CSRF':csrf,'X-CheckupAuto-Filename':encodeURIComponent(file.name)}},body:file}});const d=await r.json();if(!r.ok||!d.reportId)throw new Error(d.error||'upload_failed');reportInput.value='';await loadReports();await showReport(d.reportId);}}catch(_e){{reportStatus.textContent='Analyse impossible. Vérifiez la lisibilité du document.';}}finally{{reportUpload.disabled=false;}}}});
walletToApp.addEventListener('click',async()=>{{walletToApp.disabled=true;walletToAppStatus.textContent='Création du rattachement sécurisé…';try{{const r=await fetch('{WALLET_MOBILE_CLAIM_ROUTE}',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CheckupAuto-Customer-CSRF':csrf}},body:'{{}}'}});const d=await r.json();if(!r.ok||!d.ok||!d.claimUrl)throw new Error(d.error||'claim_failed');walletToAppStatus.textContent='Ouverture de Checkup Auto…';location.assign(d.claimUrl);}}catch(_e){{walletToAppStatus.textContent='Rattachement indisponible. Réessayez.';walletToApp.disabled=false;}}}});
loadReports();
document.getElementById('logout').addEventListener('click',async()=>{{await fetch('{LOGOUT_ROUTE}',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CheckupAuto-Customer-CSRF':csrf}},body:'{{}}'}});location.assign('{ACCOUNT_ROUTE}');}});
}})();</script></body></html>""".encode("utf-8")


def _passage_return_target(value: object) -> str:
    raw=str(value or "").strip()
    if not raw:
        return ""
    if len(raw)>2048 or any(ord(ch)<32 for ch in raw):
        return ""
    parts=urlsplit(raw)
    if parts.scheme or parts.netloc or parts.fragment or parts.path!="/go/booking":
        return ""
    try:
        query=parse_qs(parts.query,keep_blank_values=True,max_num_fields=20)
    except ValueError:
        return ""
    allowed={
        "referrer","utmSource","utmCampaign","device","path","service",
        "referralCode","preferredDate","preferredTime",
    }
    if not set(query).issubset(allowed) or any(len(values)!=1 for values in query.values()):
        return ""
    service=(query.get("service") or [""])[0].strip()
    preferred_date=(query.get("preferredDate") or [""])[0].strip()
    preferred_time=(query.get("preferredTime") or [""])[0].strip()
    if not service or len(service)>100:
        return ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",preferred_date):
        return ""
    if not re.fullmatch(r"\d{2}:\d{2}",preferred_time):
        return ""
    return "/go/booking"+(("?"+parts.query) if parts.query else "")


def booking_confirmation_url(target: object) -> str:
    return_to=_passage_return_target(target)
    if not return_to:
        return PASSAGE_ROUTE
    return PASSAGE_ROUTE+"?"+urlencode({"returnTo":return_to})


def _account_return_target(value: object) -> str:
    raw=str(value or "").strip()
    if not raw or len(raw)>4096 or any(ord(ch)<32 for ch in raw):
        return ""
    parts=urlsplit(raw)
    if parts.scheme or parts.netloc or parts.fragment or parts.path!=PASSAGE_ROUTE:
        return ""
    try:
        query=parse_qs(parts.query,keep_blank_values=True,max_num_fields=4)
    except ValueError:
        return ""
    if set(query)!={"returnTo"} or len(query["returnTo"])!=1:
        return ""
    inner=_passage_return_target(query["returnTo"][0])
    if not inner:
        return ""
    return PASSAGE_ROUTE+"?"+urlencode({"returnTo":inner})


def _booking_summary(return_to: str) -> dict:
    target=_passage_return_target(return_to)
    if not target:
        return {"service":"","date":"","time":""}
    query=parse_qs(urlsplit(target).query,keep_blank_values=True,max_num_fields=20)
    return {
        "service":str((query.get("service") or [""])[0]),
        "date":str((query.get("preferredDate") or [""])[0]),
        "time":str((query.get("preferredTime") or [""])[0]),
    }


def consume_booking_confirmation(handler, target: object) -> dict:
    return_to=_passage_return_target(target)
    if not return_to:
        raise PermissionError("customer_booking_target_invalid")
    token,account=_account(handler)
    if not token or not account:
        raise PermissionError("customer_auth_required")
    consumed=customer_accounts.consume_latest_passage_confirmation(
        account["accountId"],return_to
    )
    return {
        "required":True,
        "consumed":bool(consumed.get("consumed")),
        "confirmedAt":str(consumed.get("confirmedAt") or ""),
        "vehicleId":str(consumed.get("vehicleId") or ""),
        "vehicle":consumed.get("vehicle"),
    }


def _passage_page(
    token: str,
    account: dict,
    passage: dict,
    nonce: str,
    message: str = "",
    return_to: str = "",
    vehicles: list[dict] | None = None,
) -> bytes:
    csrf=customer_accounts.csrf_token(token)
    passage_token=str(passage["passageToken"])
    complete=bool(account.get("contactDetailsComplete"))
    phone=html.escape(str(account.get("phone") or ""))
    address1=html.escape(str(account.get("addressLine1") or ""))
    address2=html.escape(str(account.get("addressLine2") or ""))
    postal=html.escape(str(account.get("postalCode") or ""))
    city=html.escape(str(account.get("city") or ""))
    email=html.escape(str(account.get("email") or ""))
    note=f'<p class="error">{html.escape(message)}</p>' if message else ""
    incomplete="" if complete else '<p class="warning">Complétez vos coordonnées avant de continuer.</p>'
    booking=_booking_summary(return_to)
    service=html.escape(booking["service"])
    preferred_date=html.escape(booking["date"])
    preferred_time=html.escape(booking["time"])
    options=['<option value="">Ajouter un nouveau véhicule</option>']
    for vehicle in vehicles or []:
        vehicle_id=html.escape(str(vehicle.get("vehicleId") or ""),quote=True)
        system=html.escape(str(vehicle.get("registrationSystem") or "").upper())
        registration=html.escape(str(vehicle.get("registration") or ""))
        options.append(f'<option value="{vehicle_id}">{system} · {registration}</option>')
    vehicle_options="".join(options)
    contact_hidden=" hidden" if complete else ""
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow,noarchive">
<title>Véhicule et coordonnées | Checkup Auto</title>
<style>
:root{{--paper:#f6f7f2;--ink:#213b30;--muted:#6d796f;--line:#d9dfd3;--green:#1f5443;--soft:#edf1eb}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:Arial,Helvetica,sans-serif}}
main{{width:min(820px,calc(100% - 32px));margin:auto;padding:36px 0 70px}}a{{color:inherit}}.card{{background:#fff;border:1px solid var(--line);padding:clamp(24px,5vw,48px)}}
.eyebrow{{font:10px Consolas,monospace;letter-spacing:.14em;color:var(--green)}}h1{{font:400 clamp(38px,7vw,60px)/1 Georgia,serif;letter-spacing:-.04em;margin:14px 0 18px}}
h2{{font:400 28px Georgia,serif;margin:8px 0 14px}}p{{line-height:1.6;color:var(--muted)}}
.booking-summary{{display:grid;gap:5px;background:var(--green);color:#fff;padding:18px;margin:20px 0 26px}}.booking-summary small{{font:9px Consolas,monospace;letter-spacing:.12em;opacity:.75}}.booking-summary strong{{font-size:20px}}.booking-summary span{{font-size:13px}}
.step{{border-top:1px solid var(--line);padding-top:22px;margin-top:22px}}.summary{{background:var(--soft);padding:16px;line-height:1.7;overflow-wrap:anywhere}}
.actions{{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}}button{{padding:13px 18px;border:1px solid var(--green);font-weight:700;cursor:pointer;min-height:44px}}button.primary{{background:var(--green);color:#fff}}button.secondary{{background:#fff;color:var(--green)}}
form{{display:grid;gap:18px}}.fields{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px}}label{{display:grid;gap:7px;font-size:12px;font-weight:700}}input,select{{width:100%;min-width:0;padding:12px;border:1px solid var(--line);background:#fff;font:16px Arial,sans-serif}}label small{{font-weight:400;color:var(--muted);line-height:1.4}}
.full{{grid-column:1/-1}}.error{{color:#8c3a31}}.warning{{color:#7a5111}}[hidden]{{display:none!important}}#passageStatus{{font-size:12px;color:var(--muted)}}
@media(max-width:620px){{.fields{{grid-template-columns:1fr}}.full{{grid-column:1}}main{{width:min(100% - 24px,820px);padding:20px 0 44px}}.card{{padding:20px}}.actions{{align-items:stretch;flex-direction:column}}.actions button{{width:100%}}}}
{FORM_RESPONSIVE_CSS}
</style></head><body><main><section class="card"><div class="eyebrow">RÉSERVATION · ÉTAPE CLIENT</div>
<h1>Votre véhicule pour ce contrôle.</h1>
<p>Votre créneau est conservé pendant cette étape. Identifiez le véhicule concerné avant de poursuivre vers la finalisation du rendez-vous.</p>
<div class="booking-summary"><small>VOTRE CHOIX</small><strong>{service}</strong><span>{preferred_date} · {preferred_time}</span></div>
{note}{incomplete}
<form id="bookingClientForm">
<section class="step"><div class="eyebrow">1 / COORDONNÉES</div><h2>Vos informations de contact</h2>
<div class="summary"><strong>{email}</strong><br>{phone or "Téléphone non renseigné"}<br>{address1 or "Adresse non renseignée"}{("<br>"+address2) if address2 else ""}<br>{postal} {city}</div>
<div class="actions"><button id="showEdit" class="secondary" type="button">Modifier mes coordonnées</button></div>
<div id="contactFields" class="fields"{contact_hidden}>
<label>Téléphone<input id="passagePhone" value="{phone}" autocomplete="tel" maxlength="32" required></label>
<label>Adresse<input id="passageAddress1" value="{address1}" autocomplete="street-address" maxlength="180" required></label>
<label>Complément d’adresse<input id="passageAddress2" value="{address2}" maxlength="180"></label>
<label>Code postal<input id="passagePostal" value="{postal}" autocomplete="postal-code" maxlength="16" required></label>
<label>Ville<input id="passageCity" value="{city}" autocomplete="address-level2" maxlength="120" required></label>
</div></section>
<section class="step"><div class="eyebrow">2 / VÉHICULE</div><h2>Quel véhicule est concerné&nbsp;?</h2>
<label>Véhicule<select id="vehicleChoice">{vehicle_options}</select></label>
<div id="newVehicleFields" class="fields">
<label>Système d’immatriculation<select id="registrationSystem"><option value="siv">SIV · format AA-123-AA</option><option value="fni">Ancien format FNI</option></select></label>
<label>Immatriculation<input id="registration" autocomplete="off" autocapitalize="characters" maxlength="32" placeholder="AA-123-AA" required><small>SIV : AA-123-AA. FNI : par exemple 1234 AB 78.</small></label>
<label id="formulaField" class="full">Numéro de formule<input id="formulaNumber" autocomplete="off" autocapitalize="characters" maxlength="11" minlength="11" pattern="[A-Za-z0-9]{{11}}" placeholder="11 chiffres et lettres" required><small>Pour une carte grise SIV, saisissez les 11 caractères du numéro de formule.</small></label>
<label id="issueDateField" class="full" hidden>Date d’établissement de la carte grise<input id="cardIssueDate" type="date"><small>Demandée pour une immatriculation dans l’ancien système FNI.</small></label>
</div>
<div class="actions"><button class="primary" id="continueBooking" type="submit">Réserver avec ce véhicule →</button><span id="passageStatus" role="status" aria-live="polite"></span></div>
</section>
</form>
<p><a href="/#reservation">← Modifier le type de contrôle ou le créneau</a></p></section></main>
<script nonce="{html.escape(nonce,quote=True)}">
(()=>{{'use strict';
const csrf={json.dumps(csrf)},passageToken={json.dumps(passage_token)},returnTo={json.dumps(return_to)},complete={str(complete).lower()};
const form=document.getElementById('bookingClientForm'),status=document.getElementById('passageStatus'),contactFields=document.getElementById('contactFields'),vehicleChoice=document.getElementById('vehicleChoice'),newFields=document.getElementById('newVehicleFields'),system=document.getElementById('registrationSystem'),formulaField=document.getElementById('formulaField'),issueDateField=document.getElementById('issueDateField'),formula=document.getElementById('formulaNumber'),issueDate=document.getElementById('cardIssueDate'),registration=document.getElementById('registration');
let contactEditing=!complete;
document.getElementById('showEdit').addEventListener('click',()=>{{contactEditing=true;contactFields.hidden=false;}});
const syncVehicle=()=>{{const existing=!!vehicleChoice.value;newFields.hidden=existing;registration.required=!existing;system.required=!existing;const fni=system.value==='fni';formulaField.hidden=existing||fni;issueDateField.hidden=existing||!fni;formula.required=!existing&&!fni;issueDate.required=!existing&&fni;registration.placeholder=fni?'1234 AB 78':'AA-123-AA';}};
vehicleChoice.addEventListener('change',syncVehicle);system.addEventListener('change',syncVehicle);syncVehicle();
form.addEventListener('submit',async e=>{{e.preventDefault();status.textContent='Vérification du véhicule…';const payload={{passageToken,returnTo,action:contactEditing?'modified':'validated',vehicleMode:vehicleChoice.value?'existing':'new'}};
if(contactEditing)Object.assign(payload,{{phone:document.getElementById('passagePhone').value,addressLine1:document.getElementById('passageAddress1').value,addressLine2:document.getElementById('passageAddress2').value,postalCode:document.getElementById('passagePostal').value,city:document.getElementById('passageCity').value}});
if(vehicleChoice.value)payload.vehicleId=vehicleChoice.value;else Object.assign(payload,{{registrationSystem:system.value,registration:registration.value,formulaNumber:formula.value,cardIssueDate:issueDate.value}});
try{{const r=await fetch('{PASSAGE_CONFIRM_ROUTE}',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CheckupAuto-Customer-CSRF':csrf}},body:JSON.stringify(payload)}});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'customer_booking_profile_invalid');status.textContent='Véhicule enregistré. Poursuite de la réservation…';location.assign(d.continueUrl);}}catch(_e){{status.textContent='Vérifiez les coordonnées et les informations de carte grise.';}}}});
}})();
</script></body></html>""".encode("utf-8")

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

    if command=="GET" and path==PASSAGE_ROUTE:
        token,account=_account(handler)
        query=parse_qs(parsed.query,keep_blank_values=True)
        return_to=_passage_return_target((query.get("returnTo") or [""])[0])
        if not return_to:
            handler.send_redirect("/#reservation",303)
            return True
        if not token or not account:
            current=PASSAGE_ROUTE+"?"+urlencode({"returnTo":return_to})
            handler.send_redirect(ACCOUNT_ROUTE+"?"+urlencode({"returnTo":current}),303)
            return True
        supplied=(query.get("passage") or [""])[0]
        if supplied:
            try:
                customer_accounts.validate_passage_confirmation(account["accountId"],supplied,return_to)
                handler.send_redirect(return_to or "/#reservation",303)
                return True
            except Exception:
                message="Cette validation a expiré ou les coordonnées ont changé. Merci de les confirmer à nouveau."
        else:
            message=""
        passage=customer_accounts.begin_passage_confirmation(account["accountId"],return_to)
        nonce=secrets.token_urlsafe(18)
        handler._csp_nonce=nonce
        fresh=customer_accounts.profile(account["accountId"])
        vehicles=customer_accounts.list_vehicles(account["accountId"])
        handler.send_bytes(
            _passage_page(token,fresh,passage,nonce,message=message,return_to=return_to,vehicles=vehicles),
            "text/html; charset=utf-8",200,"no-store",
            {"X-Robots-Tag":"noindex, nofollow, noarchive"},
        )
        return True

    if command=="GET" and path==ACCOUNT_ROUTE:
        token,account=_account(handler)
        query=parse_qs(parsed.query,keep_blank_values=True)
        intent=(query.get("intent") or [""])[0]
        return_to=_account_return_target((query.get("returnTo") or [""])[0])
        if intent not in {"","contact"}:
            intent=""
        if not account:
            info=(
                "Pour nous contacter, connectez-vous ou créez votre compte client avec un fournisseur de connexion disponible. "
                "Cette étape permet de sécuriser et d’identifier les échanges."
                if intent=="contact" else ""
            )
            handler.send_bytes(_login_page(info=info,return_to=return_to),"text/html; charset=utf-8",200,"no-store",{"X-Robots-Tag":"noindex, nofollow, noarchive"})
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
            auth_query=parse_qs(parsed.query,keep_blank_values=True,max_num_fields=8)
            mobile=(provider=="google" and (auth_query.get("mobile") or [""])[0]=="1")
            return_to=_account_return_target((auth_query.get("returnTo") or [""])[0])
            target=customer_oidc.begin(provider,_browser_origin(handler),browser_binding=binding,mobile=mobile,return_to=return_to)
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
                _send_cookie_redirect(handler,str(result.get("returnTo") or ACCOUNT_ROUTE),result["session"],provider,state)
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

    if path in {ME_ROUTE,PROFILE_ROUTE,LOGOUT_ROUTE,WALLET_MOBILE_CLAIM_ROUTE,PASSAGE_CONFIRM_ROUTE}:
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

        if path==PASSAGE_CONFIRM_ROUTE:
            try:
                payload=_json_body(handler)
                return_to=_passage_return_target(payload.pop("returnTo",""))
                if not return_to:
                    raise ValueError
                action=str(payload.get("action") or "")
                passage_token=str(payload.get("passageToken") or "")
                vehicle_mode=str(payload.get("vehicleMode") or "")
                common={"passageToken","action","vehicleMode"}
                contact={"phone","addressLine1","addressLine2","postalCode","city"}
                if action=="validated":
                    expected=set(common)
                elif action=="modified":
                    expected=set(common)|contact
                    customer_accounts.update_contact_details(
                        account["accountId"],
                        phone=payload.get("phone"),
                        address_line1=payload.get("addressLine1"),
                        address_line2=payload.get("addressLine2"),
                        postal_code=payload.get("postalCode"),
                        city=payload.get("city"),
                    )
                else:
                    raise ValueError
                if vehicle_mode=="existing":
                    expected.add("vehicleId")
                    if set(payload)!=expected:
                        raise ValueError
                    vehicle=customer_accounts.vehicle_summary(
                        account["accountId"],payload.get("vehicleId")
                    )
                elif vehicle_mode=="new":
                    expected|={"registrationSystem","registration","formulaNumber","cardIssueDate"}
                    if set(payload)!=expected:
                        raise ValueError
                    vehicle=customer_accounts.save_vehicle(
                        account["accountId"],
                        registration_system=payload.get("registrationSystem"),
                        registration=payload.get("registration"),
                        formula_number=payload.get("formulaNumber"),
                        card_issue_date=payload.get("cardIssueDate"),
                    )
                else:
                    raise ValueError
                confirmed=customer_accounts.confirm_passage_contact(
                    account["accountId"],passage_token,action=action,
                    vehicle_id=vehicle["vehicleId"],booking_target=return_to,
                )
                handler.send_json({
                    "ok":True,
                    "confirmed":bool(confirmed.get("confirmed")),
                    "vehicleId":vehicle["vehicleId"],
                    "continueUrl":return_to,
                })
            except customer_accounts.CustomerAccountError as exc:
                handler.send_json({"ok":False,"error":str(exc)},400)
            except PermissionError:
                handler.send_json({"ok":False,"error":"customer_passage_invalid"},403)
            except Exception:
                handler.send_json({"ok":False,"error":"customer_passage_confirmation_invalid"},400)
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
            if set(payload)!={"kind","displayName","companyName","siret","phone","addressLine1","addressLine2","postalCode","city"}:
                raise ValueError
            updated=customer_accounts.update_profile(
                account["accountId"],
                kind=payload.get("kind"),
                display_name=payload.get("displayName"),
                company_name=payload.get("companyName"),
                siret=payload.get("siret"),
                phone=payload.get("phone"),
                address_line1=payload.get("addressLine1"),
                address_line2=payload.get("addressLine2"),
                postal_code=payload.get("postalCode"),
                city=payload.get("city"),
            )
            handler.send_json(updated)
        except Exception:
            handler.send_json({"ok":False,"error":"customer_profile_invalid"},400)
        return True

    return False
