from __future__ import annotations

from urllib.parse import urlparse

import analytics_store
import app_download
import gsc_client
import integration_hub
import mobile_claim_delivery
import notification_broker
import referral_engine
import reminder_dispatch
import review_followup
import security_alerts
import security_integrity


_STATE_RANK = {
    "ready": 0,
    "configuration_required": 1,
    "blocked_external": 2,
    "degraded": 3,
}


def _component(key: str, label: str, state: str, detail: str, *, critical: bool, metrics: dict | None = None) -> dict:
    if state not in _STATE_RANK:
        raise ValueError(f"état readiness invalide: {state}")
    return {
        "id": key,
        "label": label,
        "state": state,
        "critical": bool(critical),
        "detail": str(detail),
        "metrics": metrics or {},
    }


def _safe(label: str, fn):
    try:
        return fn(), None
    except Exception as exc:
        return None, f"{label}: {type(exc).__name__}"


def _public_site(config: dict) -> dict:
    raw = str((config.get("seo") or {}).get("canonicalUrl") or "").strip()
    parsed = urlparse(raw)
    valid = parsed.scheme == "https" and (parsed.hostname or "").lower() == "www.checkupauto.fr"
    state = "ready" if valid else "degraded"
    detail = "HTTPS canonique CheckupAuto actif" if valid else "URL canonique publique invalide"
    return _component("public_site", "Site public", state, detail, critical=True)


def _failed(key: str, label: str, critical: bool, error: str) -> dict:
    return _component(key, label, "degraded", error, critical=critical)


def status(config: dict, seo_health: dict | None = None) -> dict:
    components: list[dict] = [_public_site(config)]

    reminder, error = _safe("reminder", reminder_dispatch.status)
    if error:
        components.extend([
            _failed("mercure", "Mercure", True, error),
            _failed("reminder_engine", "ReminderEngine", True, error),
        ])
    else:
        session = bool(reminder.get("sessionConnected"))
        components.append(_component(
            "mercure", "Mercure", "ready" if session else "blocked_external",
            "Session Mercure connectée" if session else "Session Mercure indisponible",
            critical=True,
            metrics={"inventory": int(reminder.get("inventory") or 0)},
        ))
        complete = bool(reminder.get("ok")) and bool(reminder.get("backfillComplete"))
        components.append(_component(
            "reminder_engine", "ReminderEngine", "ready" if complete else "degraded",
            "Inventaire autoritaire synchronisé" if complete else "Synchronisation des échéances incomplète",
            critical=True,
            metrics={
                "inventory": int(reminder.get("inventory") or 0),
                "futureDueDates": int(reminder.get("futureDueDates") or 0),
                "eligibleNow": int(reminder.get("eligibleNow") or 0),
                "backfillComplete": bool(reminder.get("backfillComplete")),
            },
        ))

    broker, error = _safe("notification broker", lambda: notification_broker.status(10))
    if error:
        components.extend([
            _failed("notification_broker", "NotificationBroker", True, error),
            _failed("email_delivery", "Livraison e-mail", True, error),
            _failed("apns", "Push APNs", False, error),
        ])
    else:
        resilience = broker.get("resilience") or {}
        circuits = int(resilience.get("circuitsOpen") or 0)
        components.append(_component(
            "notification_broker", "NotificationBroker", "degraded" if circuits else "ready",
            f"{circuits} circuit(s) ouvert(s)" if circuits else "Broker et ledger opérationnels",
            critical=True,
            metrics={"circuitsOpen": circuits, "permanentFailures": int(resilience.get("permanentFailures") or 0)},
        ))
        channels = broker.get("channels") or {}
        email = channels.get("email") or {}
        email_ready = bool(email.get("configured"))
        components.append(_component(
            "email_delivery", "Livraison e-mail", "ready" if email_ready else "configuration_required",
            f"Transport {email.get("transport")} prêt" if email_ready else "SMTP ou Gmail OAuth requis",
            critical=True,
            metrics={"transport": email.get("transport") or "none"},
        ))
        push = channels.get("push") or {}
        push_ready = bool(push.get("configured"))
        components.append(_component(
            "apns", "Push APNs", "ready" if push_ready else "configuration_required",
            "Identifiants APNs présents" if push_ready else "Clé APNs, Key ID et Team ID requis",
            critical=False,
        ))

    distribution, error = _safe("distribution iOS", lambda: app_download.status(config))
    if error:
        components.append(_failed("ios_distribution", "Distribution iOS", False, error))
    else:
        ios = distribution.get("ios") or {}
        available = bool(ios.get("available")) and bool(ios.get("targetUrl"))
        components.append(_component(
            "ios_distribution", "Distribution iOS", "ready" if available else "blocked_external",
            f"Canal {ios.get("channel")} actif" if available else "Publication TestFlight ou App Store requise",
            critical=False,
            metrics={"channel": ios.get("channel") or "pending"},
        ))

    claim, error = _safe("claim iOS", lambda: mobile_claim_delivery.status(config))
    if error:
        components.append(_failed("ios_claim", "QR véhicule iOS", False, error))
    else:
        claim_ready = bool(claim.get("ready"))
        components.append(_component(
            "ios_claim", "QR véhicule iOS", "ready" if claim_ready else "configuration_required",
            "Associated Domains prêt" if claim_ready else "Préfixe d’identifiant Apple requis",
            critical=False,
            metrics={"domain": claim.get("domain"), "claimPath": claim.get("claimPath")},
        ))

    integrations, error = _safe("IntegrationHub", lambda: integration_hub.status(gsc_client.credential_info()))
    if error:
        components.append(_failed("google_integration", "IntegrationHub Google", False, error))
    else:
        oauth = bool(integrations.get("oauthAuthorized"))
        connected = sum(1 for item in integrations.get("connectors") or [] if item.get("connected"))
        components.append(_component(
            "google_integration", "IntegrationHub Google", "ready" if oauth or connected else "configuration_required",
            f"{connected} connecteur(s) connecté(s)" if oauth or connected else "OAuth Google non configuré",
            critical=False,
            metrics={"oauthAuthorized": oauth, "connectedConnectors": connected},
        ))

    analytics, error = _safe("acquisition", lambda: analytics_store.summary(30))
    if error:
        components.append(_failed("acquisition", "Acquisition first-party", False, error))
    else:
        components.append(_component(
            "acquisition", "Acquisition first-party", "ready", "Mesure first-party opérationnelle",
            critical=False,
            metrics={
                "pageViews30d": int(analytics.get("pageViews") or 0),
                "bookingClicks30d": int(analytics.get("bookingClicks") or 0),
            },
        ))

    accounts, error = _safe("parrainage", lambda: referral_engine.list_accounts(100))
    if error:
        components.append(_failed("referrals", "Parrainage / cagnotte", False, error))
    else:
        components.append(_component(
            "referrals", "Parrainage / cagnotte", "ready", "Ledger de parrainage opérationnel",
            critical=False,
            metrics={"accounts": len(accounts), "rewardCents": referral_engine.configured_reward_cents()},
        ))

    reviews, error = _safe("avis Google", review_followup.status)
    if error:
        components.append(_failed("review_followup", "Relance avis Google", False, error))
    else:
        review_ready = bool(reviews.get("emailTransportConfigured")) and bool(reviews.get("reviewUrlConfigured"))
        components.append(_component(
            "review_followup", "Relance avis Google", "ready" if review_ready else "configuration_required",
            "Relance neutre prête" if review_ready else "Transport e-mail et URL d’avis requis",
            critical=False,
            metrics={"sentTotal": int(reviews.get("sentTotal") or 0)},
        ))

    if seo_health is None:
        seo_health = {"totals": {"pass": 0, "warning": 1, "fail": 0}}
    totals = seo_health.get("totals") or {}
    failures = int(totals.get("fail") or 0)
    warnings = int(totals.get("warning") or 0)
    seo_state = "degraded" if failures else "configuration_required" if warnings else "ready"
    components.append(_component(
        "seo", "SEO", seo_state,
        f"{failures} échec(s), {warnings} avertissement(s)",
        critical=False,
        metrics={"pass": int(totals.get("pass") or 0), "warning": warnings, "fail": failures},
    ))

    posture, error = _safe("Sentinel", security_integrity.posture)
    if error:
        components.append(_failed("security", "Sécurité / observabilité", True, error))
    else:
        ok = bool(posture.get("ok"))
        vulnerabilities = (posture.get("vulnerabilities") or {}).get("count") or 0
        components.append(_component(
            "security", "Sécurité / observabilité", "ready" if ok else "degraded",
            "Sentinel, intégrité et dépendances conformes" if ok else "Posture Sentinel dégradée",
            critical=True,
            metrics={"vulnerabilities": int(vulnerabilities)},
        ))

    alerts, alert_error = _safe("alertes", security_alerts.summary)
    if alert_error:
        components.append(_failed("alert_delivery", "Alertes opérationnelles", False, alert_error))
    else:
        undelivered = int(alerts.get("undeliveredHighOrCritical") or 0)
        components.append(_component(
            "alert_delivery", "Alertes opérationnelles",
            "configuration_required" if undelivered else "ready",
            f"{undelivered} alerte(s) haute/critique non livrée(s)" if undelivered else "Aucune alerte haute/critique en attente de livraison",
            critical=False,
            metrics={"open": int(alerts.get("open") or 0), "undeliveredHighOrCritical": undelivered},
        ))

    counts = {state: 0 for state in _STATE_RANK}
    for item in components:
        counts[item["state"]] += 1
    overall = max((item["state"] for item in components), key=lambda state: _STATE_RANK[state])
    critical = [item for item in components if item["critical"]]
    launch_ready = all(item["state"] == "ready" for item in critical)
    blockers = [item["id"] for item in components if item["state"] != "ready"]
    return {
        "ok": True,
        "state": overall,
        "launchReady": launch_ready,
        "counts": counts,
        "blockers": blockers,
        "components": components,
        "privacy": "Le diagnostic n’expose aucun secret, token, identifiant client ou donnée Mercure nominative.",
    }
