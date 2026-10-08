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

from customer_vehicle_inputs import VEHICLE_INPUT_CSS, vehicle_inputs_script

import in_site_booking_readiness as booking_readiness
import customer_booking_api
import customer_accounts
import customer_password_auth
import email_gateway
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
VEHICLES_ROUTE="/api/customer/vehicles"
VEHICLE_DELETE_ROUTE="/api/customer/vehicles/delete"
LOGOUT_ROUTE="/api/customer/logout"
LOGOUT_FORM_ROUTE="/compte/deconnexion"
REPORTS_ROUTE="/api/customer/reports"
REPORT_DELETE_ROUTE="/api/customer/reports/delete"
WALLET_MOBILE_CLAIM_ROUTE="/api/customer/wallet/mobile-claim"
MOBILE_APPLE_AUTH_ROUTE="/api/mobile/auth/apple"
MOBILE_AUTH_EXCHANGE_ROUTE="/api/mobile/auth/exchange"
PASSWORD_LOGIN_ROUTE="/compte/connexion"
PASSWORD_REGISTER_ROUTE="/compte/inscription"
PASSWORD_VERIFY_ROUTE="/compte/verifier-email"
PASSWORD_RESET_REQUEST_ROUTE="/compte/mot-de-passe-oublie"
PASSWORD_RESET_ROUTE="/compte/reinitialiser"
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


def _send_session_redirect(handler, location: str, session: dict):
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
    note=f'<p class="error" role="alert">{html.escape(message)}</p>' if message else ""
    info_note=f'<p class="info" role="status">{html.escape(info)}</p>' if info else ""
    providers=_providers_html(return_to)
    return_value=html.escape(return_to,quote=True)
    heading="Connectez-vous ou créez votre compte." if return_to else "Votre véhicule, dans la durée."
    intro=(
        "Votre créneau est conservé. Connectez-vous avec Google, Apple ou votre adresse e-mail. Vous pouvez aussi créer votre compte par e-mail et mot de passe."
        if return_to else
        "Retrouvez votre fidélité, vos véhicules et l’analyse de vos rapports de contrôle technique dans un seul espace."
    )
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>Mon compte | Checkup Auto</title>
<style>
:root{{--paper:#f6f7f2;--ink:#213b30;--muted:#6f7b72;--line:#d9dfd3;--green:#1f5443;--soft:#edf1eb}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(140deg,#fbfcf9,var(--paper));color:var(--ink);font-family:Arial,Helvetica,sans-serif}}
main{{width:min(980px,calc(100% - 32px));margin:auto;padding:38px 0 70px}}a{{color:inherit}}.top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:26px}}.brand{{font-weight:750;letter-spacing:-.03em;text-decoration:none}}
.card{{background:#fff;border:1px solid var(--line);padding:clamp(26px,5vw,54px);box-shadow:0 28px 80px rgba(31,84,67,.08)}}
.eyebrow{{font:10px Consolas,monospace;letter-spacing:.14em;color:var(--green)}}h1{{font:400 clamp(42px,7vw,70px)/.98 Georgia,serif;letter-spacing:-.05em;margin:16px 0 20px}}h2{{font:400 28px Georgia,serif;margin:0 0 14px}}
p{{line-height:1.65;color:var(--muted)}}.auth-grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:28px}}.auth-panel{{border:1px solid var(--line);padding:22px;background:#fbfcfa;min-width:0}}
form{{display:grid;gap:12px}}label{{display:grid;gap:6px;font-size:12px;font-weight:700}}input{{width:100%;min-width:0;border:1px solid var(--line);background:#fff;padding:13px;font:16px Arial,sans-serif}}button{{border:0;background:var(--green);color:#fff;padding:14px 17px;min-height:46px;font-weight:700;cursor:pointer}}
.providers{{display:grid;gap:10px}}.sso{{border:1px solid var(--line);padding:14px 16px;background:#fff;font-weight:700;text-align:center;text-decoration:none;min-height:46px;display:grid;place-items:center}}.sso:hover{{border-color:#9ab1a2}}.sso.disabled{{opacity:.48}}
details{{border-top:1px solid var(--line);margin-top:18px;padding-top:16px}}summary{{cursor:pointer;font-weight:700;color:var(--green)}}details form{{margin-top:15px}}.fine{{font-size:11px;color:var(--muted);line-height:1.55}}.trust{{margin-top:26px;padding-top:20px;border-top:1px solid var(--line);font-size:11px;color:var(--muted)}}.error{{color:#8c3a31}}.info{{padding:14px 16px;border-left:3px solid var(--green);background:var(--soft);color:var(--ink)}}
@media(max-width:760px){{.auth-grid{{grid-template-columns:1fr}}.top{{align-items:flex-start;gap:12px;flex-direction:column}}}}@media(max-width:520px){{main{{width:min(100% - 24px,980px);padding:24px 0 44px}}.card,.auth-panel{{padding:20px}}h1{{font-size:clamp(38px,13vw,52px)}}}}
{FORM_RESPONSIVE_CSS}
</style><link rel="stylesheet" href="/assets/action-controls.css?v=20261008-1"></head><body><main><div class="top"><a class="brand" href="/">✓ CHECKUP AUTO</a><a class="action-button" href="/">Retour au site</a></div>
<section class="card"><div class="eyebrow">ESPACE CLIENT</div><h1>{html.escape(heading)}</h1><p>{html.escape(intro)}</p>
{info_note}{note}<div class="auth-grid">
<section class="auth-panel"><div class="eyebrow">E-MAIL</div><h2>Se connecter</h2>
<form action="{PASSWORD_LOGIN_ROUTE}" method="post" accept-charset="utf-8">
<input type="hidden" name="returnTo" value="{return_value}">
<label>Adresse e-mail<input name="email" type="email" autocomplete="username" maxlength="254" required></label>
<label>Mot de passe<input name="password" type="password" autocomplete="current-password" maxlength="128" required></label>
<button type="submit">Se connecter par e-mail</button></form>
<details><summary>Créer un compte par e-mail</summary><form action="{PASSWORD_REGISTER_ROUTE}" method="post" accept-charset="utf-8">
<input type="hidden" name="returnTo" value="{return_value}">
<label>Adresse e-mail<input name="email" type="email" autocomplete="email" maxlength="254" required></label>
<label>Mot de passe<input name="password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required><span class="fine">12 caractères minimum.</span></label>
<label>Confirmer le mot de passe<input name="passwordConfirm" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></label>
<button type="submit">Créer mon compte</button><p class="fine">Un lien de confirmation sera envoyé à cette adresse. En créant le compte, vous acceptez le traitement nécessaire à sa gestion ; consultez notre <a href="/confidentialite">politique de confidentialité</a>.</p></form></details>
<details><summary>Mot de passe oublié</summary><form action="{PASSWORD_RESET_REQUEST_ROUTE}" method="post" accept-charset="utf-8">
<input type="hidden" name="returnTo" value="{return_value}"><label>Adresse e-mail<input name="email" type="email" autocomplete="email" maxlength="254" required></label><button type="submit">Recevoir un lien de réinitialisation</button></form></details>
</section>
<section class="auth-panel"><div class="eyebrow">CONNEXION RAPIDE</div><h2>Google ou Apple</h2><div class="providers">{providers}</div><p class="fine">Ces connexions restent disponibles. Elles ne sont pas obligatoires : vous pouvez utiliser uniquement votre e-mail et votre mot de passe.</p></section>
</div><div class="trust">Session sécurisée et limitée dans le temps · mot de passe jamais stocké en clair · liens de confirmation et de réinitialisation à usage unique.</div>
</section></main></body></html>""".encode("utf-8")


def _reset_password_page(token: str, return_to: str="", message: str="") -> bytes:
    note=f'<p class="error" role="alert">{html.escape(message)}</p>' if message else ""
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow,noarchive"><title>Nouveau mot de passe | Checkup Auto</title><style>:root{{--paper:#f6f7f2;--ink:#213b30;--muted:#6f7b72;--line:#d9dfd3;--green:#1f5443}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:Arial,sans-serif}}main{{width:min(620px,calc(100% - 24px));margin:auto;padding:32px 0 60px}}.card{{background:#fff;border:1px solid var(--line);padding:clamp(22px,6vw,46px)}}h1{{font:400 clamp(38px,8vw,56px)/1 Georgia,serif}}form,label{{display:grid;gap:10px}}form{{gap:14px}}input{{padding:13px;border:1px solid var(--line);font:16px Arial}}button{{min-height:46px;border:0;background:var(--green);color:#fff;font-weight:700}}p{{color:var(--muted);line-height:1.6}}.error{{color:#8c3a31}}</style><link rel="stylesheet" href="/assets/action-controls.css?v=20261008-1"></head><body><main><section class="card"><a class="action-button" href="/compte">← Espace client</a><h1>Choisissez un nouveau mot de passe.</h1>{note}<form action="{PASSWORD_RESET_ROUTE}" method="post"><input type="hidden" name="token" value="{html.escape(token,quote=True)}"><input type="hidden" name="returnTo" value="{html.escape(return_to,quote=True)}"><label>Nouveau mot de passe<input name="password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></label><label>Confirmer le mot de passe<input name="passwordConfirm" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></label><button type="submit">Enregistrer et me connecter</button></form></section></main></body></html>""".encode("utf-8")


def _customer_form(handler, expected: set[str], optional: frozenset[str] = frozenset()) -> dict:
    content_type=str(handler.headers.get("Content-Type") or "").split(";",1)[0].strip().lower()
    if content_type!="application/x-www-form-urlencoded":
        raise ValueError("customer_form_content_type_invalid")
    try:
        length=int(handler.headers.get("Content-Length") or "0")
    except (TypeError,ValueError):
        length=0
    if not 1<=length<=16384:
        raise ValueError("customer_form_size_invalid")
    payload=handler._read_form()
    if not isinstance(payload,dict) or not expected <= set(payload) or not set(payload) <= expected | optional:
        raise ValueError("customer_form_invalid")
    return payload


def _password_mail(handler, result: dict, return_to: str) -> None:
    purpose=str(result.get("purpose") or "")
    token=str(result.get("token") or "")
    email=str(result.get("email") or "")
    if purpose=="verify":
        path=PASSWORD_VERIFY_ROUTE+"?"+urlencode({"token":token,"returnTo":return_to})
        subject="Confirmez votre compte Checkup Auto"
        action="Confirmer mon compte"
        text="Confirmez votre compte Checkup Auto en ouvrant ce lien :\n"
    elif purpose=="reset":
        path=PASSWORD_RESET_ROUTE+"?"+urlencode({"token":token,"returnTo":return_to})
        subject="Réinitialisez votre mot de passe Checkup Auto"
        action="Choisir un nouveau mot de passe"
        text="Choisissez un nouveau mot de passe Checkup Auto en ouvrant ce lien :\n"
    else:
        raise ValueError("customer_password_mail_purpose_invalid")
    link=_browser_origin(handler)+path
    safe_link=html.escape(link,quote=True)
    email_gateway.send_email(
        email,subject,text+link+"\n\nCe lien expire dans 30 minutes et ne peut être utilisé qu’une fois.",
        f'<p>{html.escape(text.strip())}</p><p><a href="{safe_link}">{html.escape(action)}</a></p><p>Ce lien expire dans 30 minutes et ne peut être utilisé qu’une fois.</p>',
    )


def _reset_mail(handler, result: dict, return_to: str) -> None:
    if not result.get("deliver"):
        return
    payload={"purpose":"reset","token":result["token"],"email":result["email"]}
    _password_mail(handler,payload,return_to)


VEHICLE_DOCUMENT_GUIDES_CSS = """
.carte-grise-photo{margin:14px 0;max-width:800px}
.carte-grise-photo img{display:block;width:100%;height:auto;object-fit:contain;border:1px solid #cdd9ce;border-radius:8px}
.carte-grise-photo figcaption{font-size:10px;color:#586c60;margin-top:6px}
.document-guides{grid-column:1/-1;min-width:0}
.document-guide{margin:0 0 9px;border:1px solid #cad6cb;border-radius:9px;padding:12px;background:#f4f8f3;overflow-wrap:anywhere}
.document-guide summary{color:#1f5443;cursor:pointer;font-size:13px;font-weight:700;line-height:1.5;min-height:44px;display:flex;align-items:center}
.document-guide summary:focus-visible{outline:2px solid #1f5443;outline-offset:4px}
.document-guide p{font-size:12px;line-height:1.6;margin:8px 0}
.document-footnote{font-size:11px!important;color:#596a5d}
"""


def _vehicle_document_guides() -> str:
    """Render the same approved photographs in vehicle management and booking."""
    return """<div class="document-guides" aria-label="Aide pour lire la carte grise">
<details id="vehicleFormulaGuide" class="document-guide">
<summary id="vehicleFormulaGuideSummary">ⓘ Où trouver le numéro de formule ?</summary>
<p>Sur une carte grise SIV, ce numéro de <strong>11 caractères</strong> identifie le certificat, et non le véhicule. Il apparaît notamment sur le recto sous « Certificat d’immatriculation », sur le coupon détachable sous l’immatriculation ou dans la zone de lecture automatique en bas du certificat.</p>
<figure class="carte-grise-photo"><img loading="lazy" src="/assets/guides/carte-grise-formule-photo.webp" width="800" height="252" alt="Photographie de carte grise SIV avec trois exemples de position du numéro de formule encadrés en rouge."><figcaption>Extrait officiel : © Direction de l’information légale et administrative, Service-Public.</figcaption></figure>
<p class="document-footnote">Photographie indicative : la présentation peut varier selon le modèle de certificat. Ne communiquez pas votre carte grise dans ce formulaire.</p>
</details>
<details id="vehicleDateGuide" class="document-guide" hidden>
<summary id="vehicleDateGuideSummary">ⓘ Où trouver la date d’établissement de ma carte grise ?</summary>
<p>Pour une ancienne carte grise FNI, recherchez la <strong>date d’établissement ou de délivrance du certificat</strong>, et non la date de première mise en circulation du véhicule. Sur les certificats portant des rubriques européennes, la référence <strong>I</strong> correspond à la date de l’immatriculation visée par le certificat ; la rubrique <strong>B</strong> indique la première immatriculation.</p>
<figure class="carte-grise-photo"><img loading="lazy" src="/assets/guides/carte-grise-date-photo.webp" width="400" height="222" alt="Photographie d’ancienne carte grise FNI avec la date d’établissement du certificat encadrée en rouge à la rubrique I."><figcaption>Extrait photographique indicatif : date du certificat (I) et non première immatriculation (B).</figcaption></figure>
<p class="document-footnote">La disposition et les intitulés varient sur les anciennes cartes grises : reportez la date imprimée relative à l’établissement du document.</p>
</details>
</div>"""


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
    login_methods=[html.escape(customer_oidc.PROVIDERS.get(str(p),{}).get("label",str(p).title())) for p in account["providers"]]
    if account.get("passwordConfigured"):
        login_methods.append("E-mail")
    providers=" · ".join(login_methods) or "—"
    balance=f'{int(loyalty["balanceCents"])/100:.2f} €'
    pending=f'{int(loyalty["pendingCents"])/100:.2f} €'
    google_review_url=html.escape(_google_review_url(),quote=True)
    vehicle_rows=account.get("vehicles") if isinstance(account.get("vehicles"),list) else []
    vehicles_json=json.dumps(vehicle_rows,ensure_ascii=True,separators=(",",":"),sort_keys=True).replace("<","\u003c")
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow,noarchive">
<title>Tableau de bord | Checkup Auto</title>
<style>
:root{{--paper:#f6f7f2;--ink:#213b30;--muted:#6d796f;--line:#d9dfd3;--green:#1f5443;--soft:#edf1eb}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font-family:Arial,Helvetica,sans-serif}}a{{color:inherit;text-decoration:none}}
.shell{{width:min(1240px,calc(100% - 32px));margin:auto;padding:28px 0 64px}}.top{{display:flex;justify-content:space-between;align-items:center;padding:10px 0 24px}}
.brand{{font-weight:750;letter-spacing:-.04em}}.top-actions{{display:flex;gap:16px;align-items:center}}.contact-link{{color:var(--green);font-weight:700}}
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

.vehicles-section{{margin-top:14px;background:#fff;border:1px solid var(--line);padding:24px}}.vehicles-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:20px}}.vehicles-head h2{{font:400 32px Georgia,serif;margin:8px 0 8px}}.vehicles-head p{{max-width:720px;margin:0}}.vehicles-head .cta{{border:1px solid var(--green);padding:12px 15px;font-weight:700;color:var(--green);white-space:nowrap}}
.vehicle-list{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin-top:20px}}.vehicle-card{{border:1px solid var(--line);background:#fafbf8;padding:18px;display:grid;gap:14px;min-width:0}}.vehicle-card-head{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}}.vehicle-card h3{{font:400 26px Georgia,serif;margin:5px 0 0;overflow-wrap:anywhere}}.vehicle-kind{{font:700 8px Consolas,monospace;letter-spacing:.1em;color:var(--green);border:1px solid #b5c3b8;padding:6px 8px}}.vehicle-detail{{font-size:11px;color:var(--muted)}}.vehicle-actions{{display:flex;gap:8px;flex-wrap:wrap}}.vehicle-actions a,.vehicle-actions button{{border:1px solid var(--line);background:#fff;color:var(--ink);padding:9px 11px;min-height:40px;cursor:pointer;font:700 10px Arial,sans-serif}}.vehicle-actions .danger{{color:#8c3a31}}.vehicle-empty{{grid-column:1/-1;border:1px dashed #aebbb2;padding:18px;background:#fafbf8}}
.vehicle-editor{{margin-top:18px;border-top:1px solid var(--line);padding-top:16px}}.vehicle-editor summary{{cursor:pointer;font-weight:700;color:var(--green);min-height:44px;display:flex;align-items:center}}.vehicle-editor form{{margin-top:16px}}.vehicle-editor .hint{{font-size:10px;color:var(--muted);font-weight:400}}.vehicle-editor [hidden]{{display:none!important}}.vehicle-editor .secondary{{border:1px solid var(--line);background:#fff;color:var(--ink);padding:12px 16px;cursor:pointer}}
{VEHICLE_DOCUMENT_GUIDES_CSS}
{VEHICLE_INPUT_CSS}
.vehicle-status{{font-size:11px;color:var(--muted)}}
.feedback{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}}.feedback-card{{background:#fff;border:1px solid var(--line);padding:24px}}.feedback-card h2{{font:400 28px Georgia,serif;margin:8px 0 12px}}.feedback-card .cta{{display:inline-block;margin-top:8px;border:1px solid var(--green);padding:12px 15px;font-weight:700;color:var(--green)}}.feedback-card .cta.primary{{background:var(--green);color:#fff}}.feedback-note{{font-size:11px;color:var(--muted)}}.review-rating{{display:flex;gap:4px;margin:14px 0 6px}}.review-star{{border:0;background:transparent;color:#a7ada8;font-size:34px;line-height:1;padding:2px;cursor:pointer}}.review-star.selected{{color:#c78b16}}.review-star:focus-visible{{outline:2px solid var(--green);outline-offset:3px}}
@media(max-width:900px){{.grid,.feedback{{grid-template-columns:1fr}}.hero{{grid-template-columns:1fr}}}}@media(max-width:700px){{.shell{{width:min(100% - 24px,1240px);padding:18px 0 48px}}.top{{align-items:flex-start;gap:14px;flex-direction:column}}.top-actions{{width:100%;gap:12px;flex-wrap:wrap;justify-content:space-between}}.hero,.panel,.profile,.feedback-card,.vehicles-section{{padding:20px}}.vehicles-head{{flex-direction:column}}.vehicles-head .cta{{width:100%;text-align:center}}.report-item{{align-items:stretch;flex-direction:column}}.report-item button{{min-height:44px;width:100%}}.report-controls>*{{max-width:100%}}}}@media(max-width:640px){{form{{grid-template-columns:1fr}}.actions{{grid-column:1}}}}@media(max-width:480px){{h1{{font-size:clamp(38px,13vw,52px)}}.actions,.report-actions,.vehicle-actions{{align-items:stretch;flex-direction:column}}.actions button,.report-actions button,.report-actions a,.report-controls button,.vehicle-actions button,.vehicle-actions a{{width:100%;min-height:44px;text-align:center}}.metric{{font-size:38px}}.review-rating{{justify-content:space-between;max-width:260px}}}}
{FORM_RESPONSIVE_CSS}
</style><link rel="stylesheet" href="/assets/action-controls.css?v=20261008-1"></head><body><main class="shell">
<div class="top"><a class="brand" href="/">✓ CHECKUP AUTO</a>
<nav class="top-actions customer-nav" aria-label="Actions de votre espace client">
<a class="action-button action-button--primary" href="#mes-vehicules"><svg class="action-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m5 6 2-3h10l2 3 2 5v7H3v-7l2-5Z M3 11h18 M6 18v3 M18 18v3 M6 14h2 M16 14h2"/></svg>Mes véhicules</a>
<a class="action-button action-button--soft" href="{CONTACT_ROUTE}"><svg class="action-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 4h16v13H9l-5 4V4Z M8 8h8 M8 12h5"/></svg>Nous contacter</a>
<form class="customer-logout" action="{LOGOUT_FORM_ROUTE}" method="post" accept-charset="utf-8">
<input type="hidden" name="csrf" value="{html.escape(csrf,quote=True)}">
<button id="logout" class="action-button action-button--logout" type="submit"><svg class="action-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M10 4H4v16h6 M10 12h11 M17 8l4 4-4 4"/></svg>Se déconnecter</button>
</form></nav></div>
<section class="hero"><div><div class="eyebrow">TABLEAU DE BORD CLIENT</div><h1>Bonjour, {display}.</h1><p>{email} · Connexion : {providers}</p></div><span class="badge">{"PROFESSIONNEL" if pro else "PARTICULIER"}</span></section>
<div class="grid">
<section class="panel"><div class="eyebrow">MES CONTRÔLES</div><h2>Rapports et rendez-vous</h2><div class="report-links"><a class="action-button action-button--primary" href="/#reservation">Réserver un contrôle →</a><a class="action-button" href="https://rdv.checkupauto.fr/" rel="noreferrer">Consulter mes rendez-vous Mercure →</a></div><p class="sub">Le planning utilise son propre compte client. Le rattachement de cet historique nécessite une vérification dédiée.</p><div class="report" id="ct-report"><strong>Rapport de contrôle technique</strong><p>Scannez ou importez votre procès-verbal. L’original est traité puis supprimé; le compte conserve uniquement une version structurée et chiffrée en Markdown.</p><div class="report-controls"><input id="ctReportFile" type="file" accept="application/pdf,image/jpeg,image/png" capture="environment"><button id="ctReportUpload" class="primary" type="button">Analyser le rapport</button></div><div id="ctReportStatus" class="report-status" role="status" aria-live="polite"></div><div id="ctReportList" class="report-list"></div><div id="ctReportAnalysis" class="report-analysis" hidden></div></div></section>
<section class="panel"><div class="eyebrow">FIDÉLITÉ</div><h2>Votre cagnotte</h2><div class="metric">{balance}</div><p class="sub">En attente : {pending} · Code {html.escape(str(loyalty["referralCode"]))}</p><div class="report-actions"><button id="walletToApp" class="primary" type="button">Rattacher à l’app iOS</button></div><div id="walletToAppStatus" class="report-status" role="status" aria-live="polite"></div></section>
<section class="panel"><div class="eyebrow">PARRAINAGE</div><h2>Activité</h2><div class="metric">{int(loyalty["earnedReferrals"])}</div><p class="sub">parrainage(s) acquis · {int(loyalty["pendingReferrals"])} en attente</p></section>
</div>

<section class="vehicles-section" id="mes-vehicules" aria-labelledby="vehiclesTitle">
<div class="vehicles-head"><div><div class="eyebrow">MES VÉHICULES</div><h2 id="vehiclesTitle">Vos véhicules enregistrés</h2><p>Ajoutez ici les véhicules associés à votre compte. Ils seront proposés automatiquement après le choix d’un créneau de réservation.</p></div><a class="cta" href="/#reservation">Réserver un contrôle →</a></div>
<div id="vehicleList" class="vehicle-list" aria-live="polite"><p class="vehicle-empty">Chargement de vos véhicules…</p></div>
<details id="vehicleEditor" class="vehicle-editor"><summary id="vehicleEditorSummary">Ajouter un véhicule</summary>
<form id="vehicleForm">
<input id="vehicleId" type="hidden" value="">
<label>Type d’immatriculation<select id="vehicleRegistrationSystem"><option value="siv">SIV · format AA-123-AA</option><option value="fni">Ancien format FNI</option></select></label>
<label>Immatriculation<input id="vehicleRegistration" maxlength="32" autocomplete="off" placeholder="AA-123-AA" aria-describedby="vehicleRegistrationFeedback" required><span id="vehicleRegistrationFeedback" class="vehicle-input-feedback" aria-live="polite"></span></label>
<label id="vehicleFormulaLabel">Numéro de formule<input id="vehicleFormulaNumber" maxlength="11" autocomplete="off" placeholder="2020AB12345" aria-describedby="vehicleFormulaFeedback vehicleFormulaGuideSummary"><span id="vehicleFormulaFeedback" class="vehicle-input-feedback" aria-live="polite"></span><span class="hint">Champ obligatoire pour une carte grise SIV. Le numéro complet n’est jamais réaffiché.</span></label>
<label id="vehicleCardIssueLabel" hidden>Date d’établissement de la carte grise<input id="vehicleCardIssueDate" aria-describedby="vehicleDateGuideSummary" type="date"></label>
<fieldset class="vehicle-essentials"><legend>Caractéristiques du véhicule</legend>
<label>Marque<input id="vehicleBrand" maxlength="120" autocomplete="off" required placeholder="Ex. Peugeot"></label>
<label>Modèle<input id="vehicleModel" maxlength="120" autocomplete="off" required placeholder="Ex. 208"></label>
<label>Énergie<input id="vehicleEnergy" maxlength="120" autocomplete="off" required placeholder="Ex. Essence"></label>
</fieldset>
<details class="vehicle-optional"><summary>Informations complémentaires (facultatives)</summary>
<label>Type de véhicule<input id="vehicleType" maxlength="120"></label>
<label>Date de première immatriculation<input id="vehicleFirstRegistrationDate" type="date"></label>
<label>VIN<input id="vehicleVin" maxlength="17" autocapitalize="characters"></label>
<label>Dénomination commerciale<input id="vehicleCommercialName" maxlength="120"></label>
<label>Carrosserie<input id="vehicleBodyStyle" maxlength="120"></label>
<label>Catégorie<input id="vehicleCategory" maxlength="120"></label>
<label>Poids total autorisé (kg)<input id="vehicleGrossWeightKg" inputmode="numeric"></label>
</details>
{_vehicle_document_guides()}
<div class="actions"><button id="vehicleSave" class="primary" type="submit">Ajouter le véhicule</button><button id="vehicleCancel" class="secondary" type="button" hidden>Annuler la modification</button><span id="vehicleStatus" class="vehicle-status" role="status" aria-live="polite"></span></div>
</form></details>
</section>
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
{vehicle_inputs_script()}
(()=>{{'use strict';const csrf={json.dumps(csrf)},status=document.getElementById('profileStatus'),kind=document.getElementById('kind'),company=document.getElementById('companyName'),siret=document.getElementById('siret'),reportInput=document.getElementById('ctReportFile'),reportUpload=document.getElementById('ctReportUpload'),reportStatus=document.getElementById('ctReportStatus'),reportList=document.getElementById('ctReportList'),reportAnalysis=document.getElementById('ctReportAnalysis'),walletToApp=document.getElementById('walletToApp'),walletToAppStatus=document.getElementById('walletToAppStatus'),reviewStars=[...document.querySelectorAll('.review-star')],reviewRatingText=document.getElementById('reviewRatingText');
let vehicleRows={vehicles_json};
const vehicleList=document.getElementById('vehicleList'),vehicleEditor=document.getElementById('vehicleEditor'),vehicleEditorSummary=document.getElementById('vehicleEditorSummary'),vehicleForm=document.getElementById('vehicleForm'),vehicleId=document.getElementById('vehicleId'),vehicleSystem=document.getElementById('vehicleRegistrationSystem'),vehicleRegistration=document.getElementById('vehicleRegistration'),vehicleFormula=document.getElementById('vehicleFormulaNumber'),vehicleFormulaLabel=document.getElementById('vehicleFormulaLabel'),vehicleCardIssueDate=document.getElementById('vehicleCardIssueDate'),vehicleCardIssueLabel=document.getElementById('vehicleCardIssueLabel'),vehicleSave=document.getElementById('vehicleSave'),vehicleCancel=document.getElementById('vehicleCancel'),vehicleStatus=document.getElementById('vehicleStatus');
const sync=()=>{{const pro=kind.value==='professional';company.disabled=!pro;siret.disabled=!pro;if(!pro){{company.value='';siret.value='';}}}};kind.addEventListener('change',sync);sync();
const setReviewRating=rating=>{{reviewStars.forEach(star=>{{const value=Number(star.dataset.rating);star.classList.toggle('selected',value<=rating);star.setAttribute('aria-checked',String(value===rating));}});reviewRatingText.textContent=rating+' étoile'+(rating>1?'s':'')+' sélectionnée'+(rating>1?'s':'')+'.';}};
reviewStars.forEach(star=>star.addEventListener('click',()=>setReviewRating(Number(star.dataset.rating))));
document.getElementById('profileForm').addEventListener('submit',async e=>{{e.preventDefault();status.textContent='Enregistrement…';const payload={{kind:kind.value,displayName:document.getElementById('displayName').value,companyName:company.value,siret:siret.value,phone:document.getElementById('phone').value,addressLine1:document.getElementById('addressLine1').value,addressLine2:document.getElementById('addressLine2').value,postalCode:document.getElementById('postalCode').value,city:document.getElementById('city').value}};try{{const r=await fetch('{PROFILE_ROUTE}',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CheckupAuto-Customer-CSRF':csrf}},body:JSON.stringify(payload)}});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'profile_failed');status.textContent='Profil enregistré.';}}catch(e){{status.textContent='Enregistrement impossible.';}}}});
const el=(tag,text='')=>{{const node=document.createElement(tag);if(text)node.textContent=text;return node;}};

const vehicleMessage=code=>({{
 customer_vehicle_registration_invalid:'Vérifiez le format de l’immatriculation.',
 customer_vehicle_formula_number_invalid:'Le numéro de formule SIV doit contenir exactement 11 caractères.',
 customer_vehicle_card_issue_date_invalid:'Indiquez une date valide figurant sur la carte grise.',
 customer_vehicle_formula_number_not_allowed:'Le numéro de formule ne doit pas être renseigné pour une ancienne immatriculation FNI.',
 customer_vehicle_duplicate:'Ce véhicule est déjà enregistré dans votre compte.',
 customer_vehicle_limit_reached:'La limite de 12 véhicules enregistrés est atteinte.',
 customer_vehicle_in_use:'Ce véhicule est lié à une réservation en cours et ne peut pas encore être supprimé.',
 customer_vehicle_not_found:'Ce véhicule n’existe plus dans votre compte.'
}})[code]||'L’opération sur le véhicule n’a pas pu être effectuée.';
const vehicleDateLabel=value=>{{const parts=String(value||'').split('-');return parts.length===3?parts.reverse().join('/'):'date inconnue';}};
const vehicleInputs=CheckupAutoVehicleInputs.bind({{system:vehicleSystem,registration:vehicleRegistration,formula:vehicleFormula,issueDate:vehicleCardIssueDate,registrationFeedback:document.getElementById('vehicleRegistrationFeedback'),formulaFeedback:document.getElementById('vehicleFormulaFeedback')}});
const vehicleCharacteristicFields=['brand','model','energy','vehicleType','firstRegistrationDate','vin','commercialName','bodyStyle','category','grossWeightKg'];
const vehicleCharacteristicInputs=Object.fromEntries(vehicleCharacteristicFields.map(field=>[field,document.getElementById('vehicle'+field[0].toUpperCase()+field.slice(1))]));
const getVehicleCharacteristics=()=>Object.fromEntries(vehicleCharacteristicFields.map(field=>[field,vehicleCharacteristicInputs[field].value.trim()]));
const fillVehicleCharacteristics=data=>{{for(const field of vehicleCharacteristicFields)vehicleCharacteristicInputs[field].value=(data||{{}})[field]||'';}};
const syncVehicleFields=()=>{{const siv=vehicleSystem.value==='siv';vehicleFormulaLabel.hidden=!siv;vehicleCardIssueLabel.hidden=siv;document.getElementById('vehicleFormulaGuide').hidden=!siv;document.getElementById('vehicleDateGuide').hidden=siv;vehicleFormula.required=siv;vehicleCardIssueDate.required=!siv;vehicleRegistration.placeholder=siv?'AA-123-AA':'1234 AB 78';if(siv)vehicleCardIssueDate.value='';else vehicleFormula.value='';vehicleInputs.refresh();}};
const resetVehicleForm=()=>{{vehicleForm.reset();fillVehicleCharacteristics({{}});vehicleId.value='';vehicleSystem.value='siv';vehicleEditorSummary.textContent='Ajouter un véhicule';vehicleSave.textContent='Ajouter le véhicule';vehicleCancel.hidden=true;vehicleStatus.textContent='';syncVehicleFields();}};
const editVehicle=row=>{{fillVehicleCharacteristics(row.characteristics);vehicleId.value=row.vehicleId;vehicleSystem.value=row.registrationSystem;vehicleRegistration.value=row.registration;vehicleFormula.value='';vehicleCardIssueDate.value=row.cardIssueDate||'';vehicleEditorSummary.textContent='Modifier '+row.registration;vehicleSave.textContent='Enregistrer les modifications';vehicleCancel.hidden=false;vehicleEditor.open=true;syncVehicleFields();if(row.registrationSystem==='siv')vehicleStatus.textContent='Pour confirmer une modification SIV, retapez le numéro de formule à 11 caractères.';else vehicleStatus.textContent='';vehicleRegistration.focus();vehicleEditor.scrollIntoView({{behavior:'smooth',block:'nearest'}});}};
const removeVehicle=async row=>{{if(!confirm('Supprimer '+row.registration+' de votre espace client ?'))return;vehicleStatus.textContent='Suppression…';try{{const r=await fetch('{VEHICLE_DELETE_ROUTE}',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CheckupAuto-Customer-CSRF':csrf}},body:JSON.stringify({{vehicleId:row.vehicleId}})}});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'vehicle_delete_failed');vehicleRows=d.vehicles||vehicleRows.filter(item=>item.vehicleId!==row.vehicleId);renderVehicles();if(vehicleId.value===row.vehicleId)resetVehicleForm();vehicleStatus.textContent='Véhicule supprimé.';}}catch(error){{vehicleStatus.textContent=vehicleMessage(error.message);}}}};
const renderVehicles=()=>{{vehicleList.replaceChildren();if(!vehicleRows.length){{const empty=el('p','Aucun véhicule enregistré. Ajoutez votre premier véhicule pour le retrouver automatiquement lors de la réservation.');empty.className='vehicle-empty';vehicleList.append(empty);return;}}for(const row of vehicleRows){{const card=el('article');card.className='vehicle-card';const head=el('div');head.className='vehicle-card-head';const copy=el('div');copy.append(el('div',row.registrationSystem==='siv'?'IMMATRICULATION SIV':'IMMATRICULATION FNI'));copy.append(el('h3',row.registration));const kind=el('span',row.registrationSystem.toUpperCase());kind.className='vehicle-kind';head.append(copy,kind);const detail=el('p',row.registrationSystem==='siv'?(row.formulaNumberPresent?'Numéro de formule enregistré et chiffré.':'Numéro de formule à compléter.'):'Carte grise établie le '+vehicleDateLabel(row.cardIssueDate)+'.');detail.className='vehicle-detail';const actions=el('div');actions.className='vehicle-actions';const reserve=el('a','Réserver un contrôle');reserve.href='/#reservation';const edit=el('button','Modifier');edit.type='button';edit.addEventListener('click',()=>editVehicle(row));const remove=el('button','Supprimer');remove.type='button';remove.className='danger';remove.addEventListener('click',()=>removeVehicle(row));actions.append(reserve,edit,remove);card.append(head,detail,actions);vehicleList.append(card);}}}};
vehicleSystem.addEventListener('change',()=>{{vehicleRegistration.value=CheckupAutoVehicleInputs.formatRegistration(vehicleRegistration.value,vehicleSystem.value,false);syncVehicleFields();}});vehicleCancel.addEventListener('click',resetVehicleForm);
vehicleForm.addEventListener('submit',async event=>{{event.preventDefault();if(!vehicleInputs.validate())return;vehicleSave.disabled=true;vehicleStatus.textContent=vehicleId.value?'Enregistrement des modifications…':'Ajout du véhicule…';const payload={{vehicleId:vehicleId.value,registrationSystem:vehicleSystem.value,registration:vehicleRegistration.value,formulaNumber:vehicleFormula.value,cardIssueDate:vehicleCardIssueDate.value,characteristics:getVehicleCharacteristics()}};try{{const r=await fetch('{VEHICLES_ROUTE}',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CheckupAuto-Customer-CSRF':csrf}},body:JSON.stringify(payload)}});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'vehicle_save_failed');vehicleRows=d.vehicles||vehicleRows;renderVehicles();resetVehicleForm();vehicleStatus.textContent='Véhicule enregistré.';}}catch(error){{vehicleStatus.textContent=vehicleMessage(error.message);}}finally{{vehicleSave.disabled=false;}}}});
renderVehicles();syncVehicleFields();
const renderReports=rows=>{{reportList.replaceChildren();for(const row of rows){{const item=el('div');item.className='report-item';const copy=el('div');copy.append(el('strong',row.controlDate||'Rapport CT'));copy.append(el('div',(row.registration||'Véhicule non identifié')+' · '+String(row.defectCount||0)+' défaut(s)'));const open=el('button','Ouvrir');open.type='button';open.addEventListener('click',()=>showReport(row.reportId));item.append(copy,open);reportList.append(item);}}if(!rows.length)reportList.append(el('div','Aucun rapport analysé.'));}};
const loadReports=async()=>{{try{{const r=await fetch('{REPORTS_ROUTE}',{{cache:'no-store',credentials:'same-origin'}});const d=await r.json();if(!r.ok||!d.ok)throw new Error();renderReports(d.reports||[]);}}catch(_e){{reportStatus.textContent='Historique des rapports indisponible.';}}}};
const showReport=async id=>{{reportStatus.textContent='Lecture du rapport…';try{{const r=await fetch('{REPORTS_ROUTE}/'+encodeURIComponent(id),{{cache:'no-store',credentials:'same-origin'}});const d=await r.json();if(!r.ok||!d.reportId)throw new Error();reportAnalysis.replaceChildren();reportAnalysis.hidden=false;reportAnalysis.append(el('h3','Analyse du contrôle technique'));reportAnalysis.append(el('p',(d.result||'Résultat non détecté')+' · '+String(d.defectCount||0)+' défaut(s) structuré(s)'));const list=el('ul');for(const finding of (d.advice||[])){{const li=el('li');const title=el('strong',finding.title||'Point à surveiller');li.append(title,document.createTextNode(' — '+(finding.prevention||'')));list.append(li);}}reportAnalysis.append(list);const actions=el('div');actions.className='report-actions';const download=el('a','Télécharger le Markdown');download.href='{REPORTS_ROUTE}/'+encodeURIComponent(id)+'?format=md';download.className='primary';const remove=el('button','Supprimer');remove.type='button';remove.className='danger';remove.addEventListener('click',async()=>{{if(!confirm('Supprimer ce rapport de votre espace client ?'))return;const rr=await fetch('{REPORT_DELETE_ROUTE}',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CheckupAuto-Customer-CSRF':csrf}},body:JSON.stringify({{reportId:id}})}});if(rr.ok){{reportAnalysis.hidden=true;await loadReports();}}}});actions.append(download,remove);reportAnalysis.append(actions);reportStatus.textContent='Analyse prête.';}}catch(_e){{reportStatus.textContent='Lecture du rapport impossible.';}}}};
reportUpload.addEventListener('click',async()=>{{const file=reportInput.files[0];if(!file){{reportStatus.textContent='Sélectionnez une photo ou un PDF.';return;}}const type=file.type||({{pdf:'application/pdf',jpg:'image/jpeg',jpeg:'image/jpeg',png:'image/png'}}[file.name.split('.').pop().toLowerCase()]||'');if(!['application/pdf','image/jpeg','image/png'].includes(type)){{reportStatus.textContent='Format accepté : PDF, JPEG ou PNG.';return;}}reportUpload.disabled=true;reportStatus.textContent='Extraction et analyse du rapport…';try{{const r=await fetch('{REPORTS_ROUTE}',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':type,'X-CheckupAuto-Customer-CSRF':csrf,'X-CheckupAuto-Filename':encodeURIComponent(file.name)}},body:file}});const d=await r.json();if(!r.ok||!d.reportId)throw new Error(d.error||'upload_failed');reportInput.value='';await loadReports();await showReport(d.reportId);}}catch(_e){{reportStatus.textContent='Analyse impossible. Vérifiez la lisibilité du document.';}}finally{{reportUpload.disabled=false;}}}});
walletToApp.addEventListener('click',async()=>{{walletToApp.disabled=true;walletToAppStatus.textContent='Création du rattachement sécurisé…';try{{const r=await fetch('{WALLET_MOBILE_CLAIM_ROUTE}',{{method:'POST',credentials:'same-origin',headers:{{'Content-Type':'application/json','X-CheckupAuto-Customer-CSRF':csrf}},body:'{{}}'}});const d=await r.json();if(!r.ok||!d.ok||!d.claimUrl)throw new Error(d.error||'claim_failed');walletToAppStatus.textContent='Ouverture de Checkup Auto…';location.assign(d.claimUrl);}}catch(_e){{walletToAppStatus.textContent='Rattachement indisponible. Réessayez.';walletToApp.disabled=false;}}}});
loadReports();
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
{VEHICLE_DOCUMENT_GUIDES_CSS}
{FORM_RESPONSIVE_CSS}
</style><link rel="stylesheet" href="/assets/action-controls.css?v=20261008-1"></head><body><main><section class="card"><div class="eyebrow">RÉSERVATION · ÉTAPE CLIENT</div>
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
<label>Immatriculation<input id="registration" autocomplete="off" autocapitalize="characters" maxlength="32" placeholder="AA-123-AA" aria-describedby="registrationFeedback" required><span id="registrationFeedback" class="vehicle-input-feedback" aria-live="polite"></span><small>SIV : AA-123-AA. FNI : par exemple 1234 AB 78.</small></label>
<label id="formulaField" class="full">Numéro de formule<input id="formulaNumber" autocomplete="off" autocapitalize="characters" maxlength="11" minlength="11" pattern="[0-9]{{4}}[A-Za-z]{{2}}[0-9]{{5}}" placeholder="2020AB12345" aria-describedby="formulaFeedback vehicleFormulaGuideSummary" required><span id="formulaFeedback" class="vehicle-input-feedback" aria-live="polite"></span><small>Pour une carte grise SIV, saisissez les 11 caractères du numéro de formule.</small></label>
<label id="issueDateField" class="full" hidden>Date d’établissement de la carte grise<input id="cardIssueDate" aria-describedby="vehicleDateGuideSummary" type="date"><small>Demandée pour une immatriculation dans l’ancien système FNI.</small></label>
{_vehicle_document_guides()}
</div>
<div class="actions"><button class="primary" id="continueBooking" type="submit">Réserver avec ce véhicule →</button><span id="passageStatus" role="status" aria-live="polite"></span></div>
</section>
</form>
<p><a href="/#reservation">← Modifier le type de contrôle ou le créneau</a></p></section></main>
<script nonce="{html.escape(nonce,quote=True)}">
{vehicle_inputs_script()}
(()=>{{'use strict';
const csrf={json.dumps(csrf)},passageToken={json.dumps(passage_token)},returnTo={json.dumps(return_to)},complete={str(complete).lower()};
const form=document.getElementById('bookingClientForm'),status=document.getElementById('passageStatus'),contactFields=document.getElementById('contactFields'),vehicleChoice=document.getElementById('vehicleChoice'),newFields=document.getElementById('newVehicleFields'),system=document.getElementById('registrationSystem'),formulaField=document.getElementById('formulaField'),issueDateField=document.getElementById('issueDateField'),formula=document.getElementById('formulaNumber'),issueDate=document.getElementById('cardIssueDate'),registration=document.getElementById('registration');
let contactEditing=!complete;
document.getElementById('showEdit').addEventListener('click',()=>{{contactEditing=true;contactFields.hidden=false;}});
const bookingVehicleInputs=CheckupAutoVehicleInputs.bind({{system,registration,formula,issueDate,registrationFeedback:document.getElementById('registrationFeedback'),formulaFeedback:document.getElementById('formulaFeedback')}});
const syncVehicle=()=>{{const existing=!!vehicleChoice.value;newFields.hidden=existing;registration.required=!existing;system.required=!existing;const fni=system.value==='fni';formulaField.hidden=existing||fni;issueDateField.hidden=existing||!fni;document.getElementById('vehicleFormulaGuide').hidden=existing||fni;document.getElementById('vehicleDateGuide').hidden=existing||!fni;formula.required=!existing&&!fni;issueDate.required=!existing&&fni;registration.placeholder=fni?'1234 AB 78':'AA-123-AA';formula.disabled=existing||fni;issueDate.disabled=existing||!fni;bookingVehicleInputs.refresh();}};
vehicleChoice.addEventListener('change',syncVehicle);system.addEventListener('change',()=>{{registration.value=CheckupAutoVehicleInputs.formatRegistration(registration.value,system.value,false);syncVehicle();}});syncVehicle();
form.addEventListener('submit',async e=>{{e.preventDefault();if(!vehicleChoice.value&&!bookingVehicleInputs.validate())return;status.textContent='Vérification du véhicule…';const payload={{passageToken,returnTo,action:contactEditing?'modified':'validated',vehicleMode:vehicleChoice.value?'existing':'new'}};
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


def _logout_error(handler, message: str, status: int) -> None:
    """Show a recoverable HTML error; never claim a failed revocation succeeded."""
    page=f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive"><title>Déconnexion | Checkup Auto</title>
<link rel="stylesheet" href="/assets/action-controls.css?v=20261008-1">
<style>body{{margin:0;background:#f6f7f2;color:#213b30;font:16px Arial,sans-serif}}main{{max-width:680px;margin:auto;padding:40px 24px}}p{{line-height:1.6}}</style>
</head><body><main><h1>Déconnexion impossible</h1><p role="alert">{html.escape(message)}</p>
<a class="action-button" href="/compte">Revenir à mon espace client pour réessayer</a></main></body></html>""".encode("utf-8")
    handler.send_bytes(page,"text/html; charset=utf-8",status,"no-store")


def _handle_logout_form(handler) -> bool:
    # A browser-native form must remain usable when any dashboard widget fails,
    # with the same origin and session-bound CSRF requirements as the JSON API.
    if getattr(handler,"command","")!="POST":
        _logout_error(handler,"Utilisez le bouton Se déconnecter de votre espace client.",405)
        return True
    if not _same_origin(handler):
        _logout_error(handler,"Cette demande a été refusée. Revenez à votre espace client.",403)
        return True
    try:
        payload=_customer_form(handler,{"csrf"})
    except (ValueError,TypeError,UnicodeError):
        _logout_error(handler,"Cette demande est invalide. Revenez à votre espace client.",400)
        return True
    token=_cookie(handler)
    if not token:
        _clear_cookie(handler)
        return True
    try:
        customer_accounts.authenticate_session(token)
    except PermissionError:
        # An expired/already-closed session should not trap the customer.
        _clear_cookie(handler)
        return True
    except Exception:
        _logout_error(handler,"La session ne peut pas être vérifiée pour le moment. Réessayez.",503)
        return True
    if not customer_accounts.verify_csrf(token,payload.get("csrf")):
        _logout_error(handler,"Cette page a expiré. Revenez à votre espace client puis réessayez.",403)
        return True
    try:
        customer_accounts.close_session(token)
    except Exception:
        _logout_error(handler,"Votre session n’a pas été fermée. Réessayez dans un instant.",503)
        return True
    _clear_cookie(handler)
    return True


def handle(handler) -> bool:
    parsed=urlsplit(handler.path)
    path=parsed.path
    command=getattr(handler,"command","")

    if path=="/api/customer/booking/preflight":
        if command!="POST":
            handler.send_json({"ok":False,"error":"customer_method_not_allowed"},405)
            return True
        token,account=_account(handler)
        if not token or not account:
            handler.send_json({"ok":False,"error":"customer_auth_required"},401)
            return True
        if not _same_origin(handler):
            handler.send_json({"ok":False,"error":"customer_origin_not_allowed"},403)
            return True
        if not customer_accounts.verify_csrf(token,handler.headers.get("X-CheckupAuto-Customer-CSRF")):
            handler.send_json({"ok":False,"error":"customer_csrf_invalid"},403)
            return True
        try:
            verified_account={**account,"vehicles":customer_accounts.list_vehicles(account["accountId"])}
            result=customer_booking_api.preflight(_json_body(handler),account=verified_account)
            handler.send_json(result,200)
        except customer_booking_api.BookingPreflightError as exc:
            handler.send_json({"ok":False,"error":str(exc)},422)
        except Exception:
            handler.send_json({"ok":False,"error":"booking_provider_unavailable"},503)
        return True

    if path==LOGOUT_FORM_ROUTE:
        return _handle_logout_form(handler)

    if path=="/api/customer/booking/readiness":
        if command!="GET":
            handler.send_json({"ok":False,"error":"customer_method_not_allowed"},405)
            return True
        token,account=_account(handler)
        if not token or not account:
            handler.send_json({"ok":False,"error":"customer_auth_required"},401)
            return True
        handler.send_json(booking_readiness.public_status(),200)
        return True

    if command=="GET" and path==PASSWORD_VERIFY_ROUTE:
        query=parse_qs(parsed.query,keep_blank_values=True,max_num_fields=4)
        token=(query.get("token") or [""])[0]
        return_to=_account_return_target((query.get("returnTo") or [""])[0])
        try:
            account=customer_password_auth.verify_registration(token)
            session=customer_accounts.issue_session(account["accountId"])
            _send_session_redirect(handler,return_to or ACCOUNT_ROUTE,session)
        except Exception:
            handler.send_bytes(
                _login_page("Ce lien de confirmation est invalide ou expiré.",return_to=return_to),
                "text/html; charset=utf-8",400,"no-store",{"X-Robots-Tag":"noindex, nofollow, noarchive"},
            )
        return True

    if command=="GET" and path==PASSWORD_RESET_ROUTE:
        query=parse_qs(parsed.query,keep_blank_values=True,max_num_fields=4)
        token=(query.get("token") or [""])[0]
        return_to=_account_return_target((query.get("returnTo") or [""])[0])
        handler.send_bytes(
            _reset_password_page(token,return_to),"text/html; charset=utf-8",200,"no-store",
            {"X-Robots-Tag":"noindex, nofollow, noarchive"},
        )
        return True

    if command=="POST" and path in {PASSWORD_LOGIN_ROUTE,PASSWORD_REGISTER_ROUTE,PASSWORD_RESET_REQUEST_ROUTE,PASSWORD_RESET_ROUTE}:
        if not _same_origin(handler):
            handler.send_bytes(_login_page("Requête refusée."),"text/html; charset=utf-8",403,"no-store")
            return True
        if path==PASSWORD_LOGIN_ROUTE:
            try:
                payload=_customer_form(handler,{"email","password","returnTo"})
                return_to=_account_return_target(payload.get("returnTo"))
                account=customer_password_auth.authenticate(payload.get("email"),payload.get("password"))
                session=customer_accounts.issue_session(account["accountId"])
                _send_session_redirect(handler,return_to or ACCOUNT_ROUTE,session)
            except customer_accounts.CustomerAccountError as exc:
                message=("Confirmez d’abord votre adresse e-mail en utilisant le lien reçu." if str(exc)=="customer_email_not_verified" else "Connexion impossible.")
                handler.send_bytes(_login_page(message,return_to=locals().get("return_to", "")),"text/html; charset=utf-8",401,"no-store")
            except Exception:
                handler.send_bytes(_login_page("Adresse e-mail ou mot de passe incorrect.",return_to=locals().get("return_to", "")),"text/html; charset=utf-8",401,"no-store")
            return True

        if path==PASSWORD_REGISTER_ROUTE:
            try:
                # Accept the former name field only for already-open registration pages.
                payload=_customer_form(handler,{"email","password","passwordConfirm","returnTo"},frozenset({"displayName"}))
                return_to=_account_return_target(payload.get("returnTo"))
                if not hmac.compare_digest(str(payload.get("password") or ""),str(payload.get("passwordConfirm") or "")):
                    raise customer_accounts.CustomerAccountError("customer_password_confirmation_mismatch")
                if not email_gateway.configured():
                    handler.send_bytes(_login_page("La création de compte par e-mail est momentanément indisponible.",return_to=return_to),"text/html; charset=utf-8",503,"no-store")
                    return True
                result=customer_password_auth.begin_registration(payload.get("email"),payload.get("displayName"),payload.get("password"))
                _password_mail(handler,result,return_to)
                handler.send_bytes(_login_page(info="Consultez votre boîte e-mail pour confirmer le compte ou choisir un nouveau mot de passe.",return_to=return_to),"text/html; charset=utf-8",200,"no-store")
            except customer_accounts.CustomerAccountError as exc:
                messages={
                    "customer_password_policy_invalid":"Le mot de passe doit contenir au moins 12 caractères.",
                    "customer_password_confirmation_mismatch":"Les deux mots de passe ne correspondent pas.",
                    "customer_email_invalid":"L’adresse e-mail est invalide.",
                    "customer_display_name_invalid":"Le nom est invalide.",
                }
                handler.send_bytes(_login_page(messages.get(str(exc),"Création du compte impossible."),return_to=locals().get("return_to", "")),"text/html; charset=utf-8",400,"no-store")
            except email_gateway.EmailDeliveryError:
                handler.send_bytes(_login_page("L’e-mail de confirmation n’a pas pu être envoyé. Réessayez dans quelques instants.",return_to=locals().get("return_to", "")),"text/html; charset=utf-8",503,"no-store")
            except Exception:
                handler.send_bytes(_login_page("Création du compte impossible.",return_to=locals().get("return_to", "")),"text/html; charset=utf-8",400,"no-store")
            return True

        if path==PASSWORD_RESET_REQUEST_ROUTE:
            try:
                payload=_customer_form(handler,{"email","returnTo"})
                return_to=_account_return_target(payload.get("returnTo"))
                if email_gateway.configured():
                    result=customer_password_auth.begin_reset(payload.get("email"))
                    try:
                        _reset_mail(handler,result,return_to)
                    except email_gateway.EmailDeliveryError:
                        pass
                handler.send_bytes(_login_page(info="Si un compte par e-mail correspond à cette adresse, un lien de réinitialisation vient d’être envoyé.",return_to=return_to),"text/html; charset=utf-8",200,"no-store")
            except Exception:
                handler.send_bytes(_login_page(info="Si un compte par e-mail correspond à cette adresse, un lien de réinitialisation vient d’être envoyé.",return_to=locals().get("return_to", "")),"text/html; charset=utf-8",200,"no-store")
            return True

        try:
            payload=_customer_form(handler,{"token","password","passwordConfirm","returnTo"})
            return_to=_account_return_target(payload.get("returnTo"))
            if not hmac.compare_digest(str(payload.get("password") or ""),str(payload.get("passwordConfirm") or "")):
                raise customer_accounts.CustomerAccountError("customer_password_confirmation_mismatch")
            account=customer_password_auth.reset_password(payload.get("token"),payload.get("password"))
            session=customer_accounts.issue_session(account["accountId"])
            _send_session_redirect(handler,return_to or ACCOUNT_ROUTE,session)
        except customer_accounts.CustomerAccountError:
            handler.send_bytes(_reset_password_page(str(locals().get("payload",{}).get("token") or ""),locals().get("return_to", ""),"Le mot de passe doit contenir au moins 12 caractères et les deux saisies doivent correspondre."),"text/html; charset=utf-8",400,"no-store")
        except Exception:
            handler.send_bytes(_reset_password_page(str(locals().get("payload",{}).get("token") or ""),locals().get("return_to", ""),"Ce lien est invalide ou expiré."),"text/html; charset=utf-8",400,"no-store")
        return True

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
                "Pour nous contacter, connectez-vous ou créez votre compte client par e-mail, Google ou Apple. "
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


    if path in {VEHICLES_ROUTE,VEHICLE_DELETE_ROUTE}:
        token,account=_account(handler)
        if not token or not account:
            handler.send_json({"ok":False,"error":"customer_auth_required"},401)
            return True
        account_id=account["accountId"]
        if command=="GET" and path==VEHICLES_ROUTE:
            handler.send_json({"ok":True,"vehicles":customer_accounts.list_vehicles(account_id)})
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
        try:
            payload=_json_body(handler)
            if path==VEHICLE_DELETE_ROUTE:
                if set(payload)!={"vehicleId"}:
                    raise ValueError
                removed=customer_accounts.delete_vehicle(account_id,payload.get("vehicleId"))
                handler.send_json({"ok":True,"removed":removed,"vehicles":customer_accounts.list_vehicles(account_id)})
            else:
                if not {"vehicleId","registrationSystem","registration","formulaNumber","cardIssueDate"} <= set(payload) or set(payload)-{"vehicleId","registrationSystem","registration","formulaNumber","cardIssueDate","characteristics"}:
                    raise ValueError
                vehicle=customer_accounts.save_vehicle(
                    account_id,
                    vehicle_id=payload.get("vehicleId"),
                    registration_system=payload.get("registrationSystem"),
                    registration=payload.get("registration"),
                    formula_number=payload.get("formulaNumber"),
                    card_issue_date=payload.get("cardIssueDate"),
                    **({"characteristics":payload["characteristics"]} if "characteristics" in payload else {}),
                )
                handler.send_json({"ok":True,"vehicle":vehicle,"vehicles":customer_accounts.list_vehicles(account_id)},201)
        except customer_accounts.CustomerAccountError as exc:
            handler.send_json({"ok":False,"error":str(exc)},400)
        except Exception:
            handler.send_json({"ok":False,"error":"customer_vehicle_payload_invalid"},400)
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
