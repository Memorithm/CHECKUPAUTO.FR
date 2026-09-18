from __future__ import annotations

import html
import json
import os
from urllib.parse import urlparse

APP_STORE_ENV = "CYBERCHECK_IOS_APP_URL"
_CAMPAIGN = "ios-reminder-app"
_ALLOWED_SOURCES = {
    "direct",
    "site",
    "qr-site",
    "qr-centre",
    "centre",
    "email",
    "admin-test",
}


def normalize_source(value: object) -> str:
    source = str(value or "").strip().lower()
    return source if source in _ALLOWED_SOURCES else "direct"


def ios_app_store_url() -> str:
    raw = os.environ.get(APP_STORE_ENV, "").strip()
    if not raw or any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        return ""
    try:
        parsed = urlparse(raw)
    except Exception:
        return ""
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "apps.apple.com":
        return ""
    if parsed.username or parsed.password:
        return ""
    return raw


def canonical_origin(config: dict) -> str:
    raw = str((config.get("seo") or {}).get("canonicalUrl") or "https://checkupauto.fr/")
    try:
        parsed = urlparse(raw)
    except Exception:
        return "https://checkupauto.fr"
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "https://checkupauto.fr"
    return f"{parsed.scheme}://{parsed.netloc}"


def status(config: dict) -> dict:
    origin = canonical_origin(config)
    store_url = ios_app_store_url()
    return {
        "landingUrl": f"{origin}/app",
        "campaign": _CAMPAIGN,
        "ios": {
            "available": bool(store_url),
            "downloadPath": "/go/app",
            "appStoreUrl": store_url or None,
        },
        "sources": sorted(_ALLOWED_SOURCES),
    }


def landing_html(config: dict, source: object, nonce: str) -> bytes:
    source = normalize_source(source)
    app = status(config)
    available = bool(app["ios"]["available"])
    origin = canonical_origin(config)
    canonical = f"{origin}/app"
    robots = "index,follow" if available else "noindex,follow"
    nonce_attr = html.escape(str(nonce), quote=True)
    source_js = json.dumps(source, ensure_ascii=False)
    if available:
        cta = (
            f'<a class="download" href="/go/app?src={html.escape(source, quote=True)}">'
            "Télécharger sur l’App Store →</a>"
        )
        state = "Disponible sur iPhone"
        note = "Téléchargez l’application Checkup Auto et activez les notifications."
    else:
        cta = '<span class="download disabled" aria-disabled="true">Bientôt sur l’App Store</span>'
        state = "Application iPhone en préparation"
        note = (
            "Cette adresse restera la même. Le téléchargement sera activé ici "
            "dès la publication de l’application."
        )
    document = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#f6f7f2">
<meta name="robots" content="{robots}">
<link rel="canonical" href="{html.escape(canonical, quote=True)}">
<title>Rappels contrôle technique — Checkup Auto</title>
<meta name="description" content="Application iPhone Checkup Auto pour les rappels de contrôle technique et la réservation.">
<style>
:root{{--paper:#f6f7f2;--ink:#213b30;--green:#1f5443;--line:#d9dfd3;--muted:#6d786e}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font-family:Arial,Helvetica,sans-serif}}
main{{min-height:100vh;display:grid;place-items:center;padding:32px 20px}}
.card{{width:min(760px,100%);background:#fff;border:1px solid var(--line);padding:clamp(28px,6vw,64px);box-shadow:0 24px 70px rgba(25,55,42,.09)}}
.brand{{font-size:26px;font-weight:700;letter-spacing:-.04em}} .brand b{{font-weight:400;color:#7f8d82}}
.kicker{{margin-top:44px;font:10px Consolas,monospace;letter-spacing:.12em;color:var(--green)}}
h1{{font:400 clamp(44px,8vw,74px)/1.02 Georgia,serif;letter-spacing:-.05em;margin:16px 0 22px}}
.lead{{font-size:16px;line-height:1.7;color:var(--muted);max-width:610px}}
.features{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:30px 0}}
.feature{{border:1px solid var(--line);padding:18px;min-height:120px}} .feature strong{{display:block;margin-bottom:8px}}
.feature span{{font-size:12px;line-height:1.55;color:var(--muted)}}
.state{{margin:28px 0 10px;font:10px Consolas,monospace;letter-spacing:.08em;color:var(--green)}}
.download{{display:inline-flex;background:var(--green);color:#fff;padding:16px 22px;text-decoration:none;font-size:13px}}
.download.disabled{{opacity:.58;cursor:not-allowed}} .note{{margin-top:14px;font-size:12px;line-height:1.6;color:var(--muted)}}
.back{{display:inline-block;margin-top:34px;color:var(--ink);font-size:12px;text-underline-offset:4px;text-decoration:underline}}
@media(max-width:640px){{.features{{grid-template-columns:1fr}} .feature{{min-height:0}}}}
</style>
</head>
<body>
<main><article class="card">
<div class="brand">checkup<b>auto</b></div>
<p class="kicker">RAPPELS · CONTRÔLE TECHNIQUE</p>
<h1>Votre échéance,<br>au bon moment.</h1>
<p class="lead">L’application Checkup Auto est conçue pour vous rappeler vos échéances de contrôle technique et faciliter la réservation auprès du centre.</p>
<div class="features">
<div class="feature"><strong>Rappels iPhone</strong><span>Notifications programmées avant l’échéance.</span></div>
<div class="feature"><strong>Plusieurs véhicules</strong><span>Suivi des échéances utiles depuis un même espace.</span></div>
<div class="feature"><strong>Réservation directe</strong><span>Accès rapide aux disponibilités Checkup Auto.</span></div>
</div>
<p class="state">{html.escape(state)}</p>
{cta}
<p class="note">{html.escape(note)}</p>
<a class="back" href="/">← Retour à Checkup Auto</a>
</article></main>
<script nonce="{nonce_attr}">
const source={source_js};
const width=window.innerWidth;
const device=width<700?'mobile':width<1100?'tablet':'desktop';
let referrer='';try{{referrer=document.referrer?new URL(document.referrer).origin:''}}catch{{}}
fetch('/api/events',{{method:'POST',headers:{{'Content-Type':'application/json'}},
body:JSON.stringify({{event:'app_landing_view',path:'/app',device,referrer,
utmSource:'app:'+source,utmCampaign:'{_CAMPAIGN}'}}),keepalive:true}}).catch(()=>{{}});
</script>
</body>
</html>"""
    return document.encode("utf-8")
