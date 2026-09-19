from __future__ import annotations

import base64
import html
import io
import json
import os
import re
from urllib.parse import urlparse

import mobile_devices
import reminder_dispatch

BUNDLE_ID = "fr.checkupauto.reminder"
APP_ID_PREFIX_ENV = "CYBERCHECK_IOS_APP_IDENTIFIER_PREFIX"
CLAIM_PATH = "/app/claim"
DEFAULT_TTL_SECONDS = 1800
MIN_TTL_SECONDS = 300
MAX_TTL_SECONDS = 3600
_APP_ID_PREFIX_RE = re.compile(r"^[A-Za-z0-9]{10}$")


def _canonical_origin(config: dict) -> str:
    raw = str((config.get("seo") or {}).get("canonicalUrl") or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "www.checkupauto.fr":
        raise ValueError("URL canonique iOS invalide")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("URL canonique iOS invalide")
    return "https://www.checkupauto.fr"


def _app_identifier_prefix() -> str:
    raw = str(os.environ.get(APP_ID_PREFIX_ENV, "") or "").strip()
    return raw if _APP_ID_PREFIX_RE.fullmatch(raw) else ""


def status(config: dict) -> dict:
    try:
        origin = _canonical_origin(config)
        domain_ready = True
    except ValueError:
        origin = ""
        domain_ready = False
    app_identifier_prefix = _app_identifier_prefix()
    app_identifier = (
        f"{app_identifier_prefix}.{BUNDLE_ID}"
        if app_identifier_prefix
        else ""
    )
    ready = bool(domain_ready and app_identifier)
    return {
        "ready": ready,
        "state": "ready" if ready else "configuration_required",
        "domain": "www.checkupauto.fr" if domain_ready else None,
        "claimPath": CLAIM_PATH,
        "appIdentifier": app_identifier or None,
        "appIdentifierPrefixPresent": bool(app_identifier_prefix),
        "associatedDomain": "applinks:www.checkupauto.fr",
        "delivery": "local-svg-qr",
        "defaultTtlSeconds": DEFAULT_TTL_SECONDS,
        "maxTtlSeconds": MAX_TTL_SECONDS,
        "origin": origin or None,
    }


def association_document(config: dict) -> bytes:
    state = status(config)
    if not state["ready"]:
        raise RuntimeError("association iOS non configurée")
    document = {
        "applinks": {
            "details": [
                {
                    "appIDs": [state["appIdentifier"]],
                    "components": [
                        {
                            "/": CLAIM_PATH,
                            "comment": "Rattachement one-shot d un vehicule Checkup Auto",
                        }
                    ],
                }
            ]
        }
    }
    return json.dumps(document, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def claim_landing_html(config: dict) -> bytes:
    origin = _canonical_origin(config)
    app_url = f"{origin}/app?src=claim"
    document = f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<meta name="referrer" content="no-referrer">
<title>Rattacher votre véhicule — Checkup Auto</title>
<style>
body{{margin:0;background:#f6f7f2;color:#213b30;font-family:Arial,Helvetica,sans-serif}}
main{{min-height:100vh;display:grid;place-items:center;padding:24px}}
article{{max-width:680px;background:#fff;border:1px solid #d9dfd3;padding:clamp(28px,6vw,60px);box-shadow:0 24px 70px rgba(25,55,42,.09)}}
h1{{font:400 clamp(40px,7vw,64px)/1.04 Georgia,serif;letter-spacing:-.04em;margin:12px 0 20px}}
p{{line-height:1.7;color:#65736a}}a{{display:inline-block;margin-top:18px;background:#1f5443;color:#fff;text-decoration:none;padding:15px 20px}}
small{{display:block;margin-top:24px;line-height:1.6;color:#7b877f}}
</style>
</head>
<body><main><article>
<strong>checkupauto</strong>
<h1>Rattachez votre véhicule à l’application.</h1>
<p>Si Checkup Auto est installé sur cet iPhone, ce lien s’ouvre directement dans l’application. Sinon, installez l’application puis rescanez le QR remis par le centre.</p>
<a href="{html.escape(app_url, quote=True)}">Découvrir l’application</a>
<small>Le code de rattachement est à usage unique et expire rapidement. Cette page ne transmet pas ce code à un service tiers.</small>
</article></main></body></html>"""
    return document.encode("utf-8")


def _ttl(value: object) -> int:
    ttl = DEFAULT_TTL_SECONDS if value in (None, "") else int(value)
    if ttl < MIN_TTL_SECONDS or ttl > MAX_TTL_SECONDS:
        raise ValueError("ttlSeconds invalide")
    return ttl


def _qr_data_url(url: str) -> str:
    try:
        import qrcode
        import qrcode.image.svg
    except ImportError as exc:
        raise RuntimeError("générateur QR indisponible") from exc
    image = qrcode.make(
        url,
        image_factory=qrcode.image.svg.SvgPathImage,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    buffer = io.BytesIO()
    image.save(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return "data:image/svg+xml;base64," + encoded


def candidates(limit: int = 30) -> list[dict]:
    rows = reminder_dispatch.mobile_claim_candidates(limit)
    return [
        {
            "vehicleId": row["vehicle_id"],
            "dueDate": row["due_date"],
            "appointmentId": row["appointment_id"] or None,
            "lastSeenAt": row["last_seen_at"],
        }
        for row in rows
    ]


def issue_for_vehicle(config: dict, vehicle_id: object, ttl_seconds: object = None) -> dict:
    state = status(config)
    if not state["ready"]:
        raise RuntimeError("association iOS non configurée")
    target = reminder_dispatch.mobile_claim_target(vehicle_id)
    claim = mobile_devices.issue_vehicle_claim(
        target["vehicle_id"],
        target["client_kind"],
        target["client_id"],
        ttl_seconds=_ttl(ttl_seconds),
    )
    token = str(claim["claimToken"])
    origin = _canonical_origin(config)
    url = f"{origin}{CLAIM_PATH}#token={token}"
    return {
        "vehicleId": target["vehicle_id"],
        "dueDate": target["due_date"],
        "claimUrl": url,
        "expiresAt": claim["expiresAt"],
        "qrDataUrl": _qr_data_url(url),
    }
