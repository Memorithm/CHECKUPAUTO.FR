"""Server-rendered pages of the on-site booking journey.

Only reached when ``in_site_booking_routing.decide`` returned ``in_site``.
The summary embeds the exact delegated MercureWeb form (not auto-submitted) as
the graceful fallback, and records CGV acceptance through the existing
``/api/booking/accept-terms`` mechanism with the same wording.
"""
from __future__ import annotations

import html
import json
import re

import booking_bridge as booking
import mercure_public_client

ASSET_VERSION = "20261011-1"
CONFIRMATION_ROUTE = "/compte/reservation"


def _json_block(payload: dict, nonce: str) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    raw = raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return (f'<script id="bookingJourneyData" type="application/json" '
            f'nonce="{html.escape(nonce, quote=True)}">{raw}</script>')


def _head(title: str) -> str:
    return ('<!doctype html><html lang="fr"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<meta name="robots" content="noindex,nofollow,noarchive">'
            f'<title>{html.escape(title)} | Checkup Auto</title>'
            '<link rel="stylesheet" href="/assets/action-controls.css?v=20261008-1">'
            f'<link rel="stylesheet" href="/assets/booking-journey.css?v={ASSET_VERSION}"></head>')


def _vehicle_label(vehicle: dict) -> str:
    system = str(vehicle.get("registrationSystem") or "").strip().upper()
    registration = str(vehicle.get("registration") or "").strip()
    characteristics = vehicle.get("characteristics") if isinstance(vehicle.get("characteristics"), dict) else {}
    descriptors = " ".join(str(characteristics.get(k) or "").strip() for k in ("brand", "model", "energy")).strip()
    base = " · ".join(x for x in (system, registration) if x)
    return (base + (" — " + descriptors if descriptors else "")).strip()


def _tel(phone: str) -> str:
    return re.sub(r"[^+0-9]", "", str(phone or ""))


def render_summary(*, token: str, service_label: str, service_key: str, nonce: str,
                   vehicle: dict, account: dict, csrf: str, business: dict) -> bytes:
    prestation = booking.mercure_prestation(service_label)
    if not prestation or service_key not in mercure_public_client.SERVICES:
        raise ValueError("booking_service_invalid")
    terms = booking.require_published_terms()
    cct = booking.browser_token(token)
    action = "https://rdv.checkupauto.fr/prendre_rdv?ccid=" + token + "&cct=" + cct
    requirements = booking._checkout_requirements(token)
    date, time = requirements["preferredDate"], requirements["preferredTime"]
    quote = booking.preferred_mercure_quote(service_label, date, time)
    quote_cents = int(round(float(quote["price"]) * 100)) if quote else None
    immediate_required = bool(requirements["requiresImmediatePerformance"])
    phone = str(business.get("phone") or "")
    name = " ".join(x for x in (str(account.get("givenName") or ""), str(account.get("surname") or "")) if x.strip()) \
        or str(account.get("displayName") or "")
    billing_complete = account.get("billingContactComplete") is True
    vehicle_label = _vehicle_label(vehicle)
    data = {
        "mode": "summary", "ccid": token, "cct": cct,
        "termsVersion": terms["version"], "termsContentHash": terms["contentHash"],
        "requiresImmediatePerformance": immediate_required,
        "service": service_key, "serviceLabel": service_label, "date": date, "time": time,
        "vehicleId": str(vehicle.get("vehicleId") or ""), "vehicleLabel": vehicle_label,
        "quoteCents": quote_cents, "csrf": csrf, "billingComplete": billing_complete,
        "confirmationUrl": CONFIRMATION_ROUTE,
    }
    esc = html.escape
    immediate_markup = (
        '<label class="bj-consent"><input id="bjImmediate" type="checkbox"> '
        '<span>Je demande expressément que la prestation puisse commencer avant la fin du délai '
        'de rétractation et je reconnais qu’après exécution complète de la prestation, '
        'je perdrai mon droit de rétractation.</span></label>'
        if immediate_required else '<input id="bjImmediate" type="hidden" value="">'
    )
    billing_markup = "" if billing_complete else (
        '<p class="bj-warning" role="note">Vos informations de facturation sont incomplètes. '
        '<a href="/compte">Compléter mes informations</a> puis revenez à cette page, '
        'ou poursuivez sur la plateforme Mercure ci-dessous.</p>')
    price_text = "Tarif confirmé lors de la vérification du créneau"
    page = f'''{_head("Confirmer votre rendez-vous")}<body class="bj"><main><section class="bj-card" aria-labelledby="bjTitle">
<div class="bj-eyebrow">Réservation · récapitulatif</div>
<h1 id="bjTitle">Vérifiez et confirmez votre rendez-vous.</h1>
<p>Le rendez-vous est réservé directement auprès du centre depuis cette page. Le créneau n’est bloqué qu’après confirmation.</p>
<div class="bj-highlight"><strong>{esc(service_label)}</strong><span id="bjSlot">{esc(date)} · {esc(time)}</span></div>
<dl class="bj-summary">
<dt>Prestation</dt><dd>{esc(service_label)}</dd>
<dt>Créneau</dt><dd>{esc(date)} à {esc(time)}</dd>
<dt>Tarif</dt><dd id="bjPrice">{esc(price_text)}</dd>
<dt>Paiement</dt><dd>Aucun paiement n’est demandé sur cette page.</dd>
</dl>
<section class="bj-section" aria-labelledby="bjCustomerTitle"><div class="bj-eyebrow">1 / Coordonnées</div>
<h2 id="bjCustomerTitle">Vos informations</h2>
<dl class="bj-summary"><dt>Nom</dt><dd>{esc(name) or "Non renseigné"}</dd><dt>E-mail</dt><dd>{esc(str(account.get("email") or ""))}</dd>
<dt>Téléphone</dt><dd>{esc(str(account.get("phone") or "")) or "Non renseigné"}</dd></dl>
{billing_markup}
<p><a href="/compte">Modifier mes informations</a></p></section>
<section class="bj-section" aria-labelledby="bjVehicleTitle"><div class="bj-eyebrow">2 / Véhicule</div>
<h2 id="bjVehicleTitle">Votre véhicule</h2>
<p><strong>{esc(vehicle_label)}</strong></p>
<p id="bjVehicleStatus" class="bj-status" role="status" aria-live="polite"></p>
<div id="bjVehiclePicker" hidden><p>Choisissez votre véhicule dans la liste du centre :</p>
<div class="bj-fields"><label for="bjBrand">Marque<select id="bjBrand"></select></label>
<label for="bjModel">Modèle<select id="bjModel"></select></label>
<label for="bjEnergy">Énergie<select id="bjEnergy"></select></label></div>
<div class="bj-actions"><button id="bjVehicleApply" class="primary" type="button" disabled>Utiliser ce véhicule</button></div></div></section>
<form id="bjForm" class="bj-section" novalidate aria-labelledby="bjConfirmTitle"><div class="bj-eyebrow">3 / Confirmation</div>
<h2 id="bjConfirmTitle">Conditions et confirmation</h2>
<label class="bj-consent"><input id="bjTerms" type="checkbox"> <span>J’ai lu et j’accepte les <a href="/cgv">conditions générales de vente</a> applicables à cette réservation.</span></label>
{immediate_markup}
<div class="bj-actions"><button id="bjConfirm" class="primary" type="submit" disabled>Confirmer le rendez-vous</button>
<a class="action-button" href="/#reservation">Modifier mon choix</a></div>
<p id="bjStatus" class="bj-status" role="status" aria-live="polite"></p></form>
<section id="bjSlotLost" class="bj-panel bj-panel--warn" hidden aria-labelledby="bjSlotLostTitle"><h2 id="bjSlotLostTitle">Ce créneau n’est plus disponible.</h2>
<p>Il vient d’être réservé ou modifié. Aucun rendez-vous n’a été créé pour vous.</p>
<p><a class="action-button action-button--primary" href="/#reservation">Choisir un autre créneau</a></p></section>
<section id="bjAuth" class="bj-panel bj-panel--warn" hidden aria-labelledby="bjAuthTitle"><h2 id="bjAuthTitle">Votre session a expiré.</h2>
<p>Aucun rendez-vous n’a été créé. Reconnectez-vous puis choisissez à nouveau votre créneau.</p>
<p><a class="action-button action-button--primary" href="/compte">Me reconnecter</a></p></section>
<section id="bjFailure" class="bj-panel bj-panel--error" hidden aria-labelledby="bjFailureTitle"><h2 id="bjFailureTitle">La réservation sur ce site est momentanément indisponible.</h2>
<p>Aucun rendez-vous n’a été créé. Vous pouvez finaliser votre réservation sur la plateforme de réservation du centre, ou appeler le centre.</p>
<p id="bjFailureReason" class="bj-status"></p>
<div class="bj-actions"><button id="bjFallback" class="primary" type="button">Continuer sur la plateforme de réservation</button>
<a class="action-button" href="tel:{esc(_tel(phone), quote=True)}">Appeler le centre · {esc(phone)}</a></div>
<p id="bjFallbackError" class="bj-error" role="alert"></p></section>
<form id="bjFallbackForm" method="post" action="{esc(action, quote=True)}"><input type="hidden" name="id" value="240"><input type="hidden" name="prestation" value="{esc(prestation, quote=True)}"></form>
<noscript><p class="bj-warning">JavaScript est nécessaire pour réserver sur ce site et enregistrer l’acceptation des CGV. Appelez le centre au {esc(phone)}.</p></noscript>
</section></main>{_json_block(data, nonce)}<script src="/assets/booking-journey.js?v={ASSET_VERSION}"></script></body></html>'''
    return page.encode("utf-8")


def render_status(*, request_key: str, nonce: str, business: dict) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", str(request_key or "")):
        raise ValueError("booking_key_invalid")
    phone = str(business.get("phone") or "")
    esc = html.escape
    data = {"mode": "status", "requestKey": request_key, "pollMs": 5000, "maxPolls": 24}
    page = f'''{_head("Votre rendez-vous")}<body class="bj"><main><section class="bj-card" aria-labelledby="bjStatusTitle">
<div class="bj-eyebrow">Réservation · confirmation</div>
<h1 id="bjStatusTitle">Vérification de votre rendez-vous…</h1>
<p id="bjStatusText" role="status" aria-live="polite">Nous interrogeons le centre.</p>
<dl id="bjStatusDetails" class="bj-summary" hidden></dl>
<p id="bjStatusPayment" hidden></p>
<p id="bjStatusRestart" hidden><a class="action-button action-button--primary" href="/#reservation">Choisir un créneau</a></p>
<p id="bjStatusLogin" hidden><a class="action-button action-button--primary" href="/compte">Me connecter</a></p>
<p id="bjStatusCall" hidden><a class="action-button" href="tel:{esc(_tel(phone), quote=True)}">Appeler le centre · {esc(phone)}</a></p>
<p><a href="/compte">Mon espace client</a></p>
</section></main>{_json_block(data, nonce)}<script src="/assets/booking-journey.js?v={ASSET_VERSION}"></script></body></html>'''
    return page.encode("utf-8")
