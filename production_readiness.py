from __future__ import annotations

from urllib.parse import urlparse

import analytics_store
import app_download
import gsc_client
import integration_hub
import ios_release_preflight
import mobile_claim_delivery
import notification_broker
import notification_preflight
import referral_engine
import referral_integrity_audit
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


_REMEDIATION = {
    "public_site": {
        "code": "restore_public_https",
        "summary": "Rétablir l’URL canonique HTTPS www.checkupauto.fr avant toute publication.",
        "verify": "Relancer le diagnostic et obtenir Site public = PRÊT.",
        "target": "#seo-control",
        "external": False,
    },
    "mercure": {
        "code": "restore_mercure_session",
        "summary": "Rétablir la session Mercure puis relancer une synchronisation des échéances.",
        "verify": "La session Mercure doit être connectée et l’inventaire lisible.",
        "target": "#mercure",
        "external": True,
    },
    "reminder_engine": {
        "code": "complete_reminder_sync",
        "summary": "Terminer la synchronisation autoritaire et résoudre toute identité Mercure mise en quarantaine.",
        "verify": "backfillComplete=true, quarantinedTargets=0 et ReminderEngine = PRÊT.",
        "target": "#notifications",
        "external": False,
    },
    "notification_broker": {
        "code": "restore_notification_broker",
        "summary": "Fermer les circuits défaillants, traiter les échecs permanents ou de requête et rétablir un rapprochement Mercure récent.",
        "verify": "Aucun circuit ouvert, aucun échec permanent ou de requête actif et aucun contrôle destinataire périmé ou en échec.",
        "target": "#notifications",
        "external": False,
    },
    "email_delivery": {
        "code": "configure_email_transport",
        "summary": "Configurer SMTP chiffré ou OAuth Gmail, puis exécuter le préflight sans envoi.",
        "verify": "Le transport e-mail doit être configured et son préflight doit être prêt.",
        "target": "#notifications",
        "external": True,
    },
    "apns": {
        "code": "configure_apns",
        "summary": "Installer la clé APNs privée, le Key ID et le Team ID hors Git, puis lancer le préflight.",
        "verify": "APNs doit être configured et le JWT ES256 local doit être valide.",
        "target": "#notifications",
        "external": True,
    },
    "ios_distribution": {
        "code": "publish_ios",
        "summary": "Publier un build TestFlight ou App Store signé et configurer son URL publique.",
        "verify": "Le canal iOS doit être testflight ou app-store avec une URL Apple valide.",
        "target": "#readiness",
        "external": True,
    },
    "ios_release_preflight": {
        "code": "complete_ios_release_preflight",
        "summary": "Corriger le projet Release iOS, Associated Domains/AASA et la chaîne de distribution Apple.",
        "verify": "Tous les contrôles du préflight iOS doivent être verts avant archive et publication.",
        "target": "#readiness",
        "external": False,
    },
    "ios_claim": {
        "code": "configure_ios_claim_domain",
        "summary": "Configurer le préfixe Apple Application Identifier et valider Associated Domains/AASA.",
        "verify": "Le QR claim doit annoncer ready=true.",
        "target": "#notifications",
        "external": True,
    },
    "google_integration": {
        "code": "authorize_google",
        "summary": "Configurer OAuth Google puis rétablir tout connecteur configuré dont la vérification distante échoue.",
        "verify": "Aucune vérification distante Google ne doit rester en échec, indisponible ou non exécutée pour un connecteur configuré.",
        "target": "#integrations",
        "external": True,
    },
    "acquisition": {
        "code": "restore_acquisition",
        "summary": "Rétablir la collecte first-party sans cookie ni identifiant visiteur.",
        "verify": "Le résumé acquisition doit être lisible par le Control Plane.",
        "target": "#pilotage",
        "external": False,
    },
    "referrals": {
        "code": "restore_referrals",
        "summary": "Rétablir le ledger de parrainage et corriger toute anomalie d’intégrité comptable.",
        "verify": "Le ledger doit répondre et l’audit d’intégrité doit retourner issues=0.",
        "target": "#referrals",
        "external": False,
    },
    "review_followup": {
        "code": "configure_review_followup",
        "summary": "Configurer le transport e-mail et l’URL Google Review avant d’activer les relances.",
        "verify": "emailTransportConfigured=true et reviewUrlConfigured=true.",
        "target": "#notifications",
        "external": True,
    },
    "seo": {
        "code": "resolve_seo_health",
        "summary": "Corriger les échecs SEO puis traiter les avertissements avant l’indexation publique.",
        "verify": "Le contrôle SEO ne doit plus contenir d’échec ; viser zéro avertissement avant lancement.",
        "target": "#seo-control",
        "external": False,
    },
    "security": {
        "code": "restore_security_posture",
        "summary": "Corriger Sentinel, intégrité ou dépendances avant toute activation publique.",
        "verify": "Sentinel doit retourner ok=true et zéro vulnérabilité connue.",
        "target": "#security",
        "external": False,
    },
    "alert_delivery": {
        "code": "configure_alert_delivery",
        "summary": "Configurer un webhook HTTPS public signé HMAC, puis traiter les alertes hautes/critiques en attente.",
        "verify": "Le relais doit être ready et undeliveredHighOrCritical doit revenir à 0.",
        "target": "#security",
        "external": True,
    },
}


class ProductionActivationBlocked(RuntimeError):
    def __init__(self, blockers: list[str]):
        self.blockers = tuple(str(item) for item in blockers)
        super().__init__("production_activation_blocked:" + ",".join(self.blockers))


def require_activation(report: dict) -> dict:
    gate = report.get("activationGate") or {}
    if not bool(gate.get("allowed")):
        raise ProductionActivationBlocked(list(gate.get("blockingComponents") or []))
    return report


def _component(key: str, label: str, state: str, detail: str, *, critical: bool, metrics: dict | None = None) -> dict:
    if state not in _STATE_RANK:
        raise ValueError(f"état readiness invalide: {state}")
    remediation = None if state == "ready" else dict(_REMEDIATION.get(key) or {
        "code": "investigate_component",
        "summary": "Analyser ce composant puis relancer le diagnostic.",
        "verify": "Le composant doit revenir à l’état ready.",
        "target": "#readiness",
        "external": False,
    })
    return {
        "id": key,
        "label": label,
        "state": state,
        "critical": bool(critical),
        "detail": str(detail),
        "metrics": metrics or {},
        "remediation": remediation,
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


def _google_integration_component(integrations: dict) -> dict:
    oauth = bool(integrations.get("oauthAuthorized"))
    oauth_health = integrations.get("oauthHealth") or {}
    oauth_state = str(oauth_health.get("state") or ("ready" if oauth else "awaiting_authorization"))
    oauth_client = integrations.get("oauthClient") or {}
    web_client_verified = bool(oauth_client.get("webClientVerified"))
    redirect_uri_allowed = bool(oauth_client.get("redirectUriAllowed"))
    redirect_uri_count = int(oauth_client.get("redirectUriCount") or 0)
    connectors = integrations.get("connectors") or []
    connected = sum(1 for item in connectors if item.get("connected"))
    verified = sum(1 for item in connectors if item.get("verification") == "verified")
    failed = sum(1 for item in connectors if item.get("verification") == "failed")
    unavailable = sum(1 for item in connectors if item.get("verification") == "unavailable")
    unverified = sum(1 for item in connectors if item.get("verification") == "unverified")

    def verification_source(item):
        explicit = str(item.get("verificationSource") or "").strip()
        if explicit:
            return explicit
        # Backward-compatible inference for older IntegrationHub payloads and tests.
        if item.get("id") == "gmail" and item.get("verification"):
            return "operational_delivery"
        if item.get("id") == "maps_places" and item.get("verification") == "unverified":
            return "configuration"
        if item.get("verification") in {"verified", "failed", "unavailable"}:
            return "remote_api"
        return ""

    remote_checked = sum(
        1 for item in connectors
        if verification_source(item) == "remote_api"
        and item.get("verification") in {"verified", "failed", "unavailable"}
    )
    operational_checked = sum(
        1 for item in connectors
        if verification_source(item) == "operational_delivery"
        and item.get("verification") in {"verified", "failed", "unavailable"}
    )
    configuration_only = sum(
        1 for item in connectors
        if verification_source(item) == "configuration"
        and item.get("verification") == "unverified"
    )

    if oauth and not redirect_uri_allowed:
        google_state = "degraded"
        google_detail = "OAuth actif · callback CheckupAuto à autoriser dans le client Application Web"
    elif failed:
        google_state = "degraded"
        google_detail = f"{failed} connecteur(s) configuré(s) refusé(s) par Google"
    elif unavailable:
        google_state = "degraded"
        google_detail = f"{unavailable} vérification(s) d’intégration temporairement indisponible(s)"
    elif unverified:
        google_state = "degraded"
        google_detail = f"{unverified} connecteur(s) configuré(s) sans preuve de vérification exploitable"
    elif oauth or connected:
        google_state = "ready"
        google_detail = f"{connected} connecteur(s) connecté(s)"
    elif oauth_state in {"token_expired", "reauthorization_required", "oauth_client_missing"}:
        google_state = "degraded"
        google_detail = "Session OAuth Google à renouveler"
    else:
        google_state = "configuration_required"
        google_detail = "OAuth Google non configuré"

    return _component(
        "google_integration", "IntegrationHub Google", google_state, google_detail,
        critical=False,
        metrics={
            "oauthAuthorized": oauth,
            "oauthState": oauth_state,
            "webClientVerified": web_client_verified,
            "redirectUriAllowed": redirect_uri_allowed,
            "redirectUriCount": redirect_uri_count,
            "connectedConnectors": connected,
            "verifiedConnectors": verified,
            "failedVerifications": failed,
            "unavailableVerifications": unavailable,
            "unverifiedVerifications": unverified,
            "remoteCheckedConnectors": remote_checked,
            "operationalCheckedConnectors": operational_checked,
            "configurationOnlyConnectors": configuration_only,
        },
    )


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
        quarantined_targets = int(reminder.get("quarantinedTargets") or 0)
        complete = (
            bool(reminder.get("ok"))
            and bool(reminder.get("backfillComplete"))
            and quarantined_targets == 0
        )
        if quarantined_targets:
            reminder_detail = f"{quarantined_targets} cible(s) Mercure en quarantaine d’identité"
        elif complete:
            reminder_detail = "Inventaire autoritaire synchronisé"
        else:
            reminder_detail = "Synchronisation des échéances incomplète"
        components.append(_component(
            "reminder_engine", "ReminderEngine", "ready" if complete else "degraded",
            reminder_detail,
            critical=True,
            metrics={
                "inventory": int(reminder.get("inventory") or 0),
                "quarantinedTargets": quarantined_targets,
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
        failure_counts = broker.get("failureCounts") or {}
        circuits = int(resilience.get("circuitsOpen") or 0)
        permanent_failures = int(resilience.get("permanentFailures") or 0)
        request_failures = int(failure_counts.get("request") or 0)
        permanent_history = int(resilience.get("permanentFailureHistory") or permanent_failures)
        permanent_acknowledged = int(resilience.get("permanentAcknowledged") or 0)
        permanent_resolved = int(resilience.get("permanentResolved") or 0)
        recipient_checks = resilience.get("recipientChecks") or {}
        recipient_tracked = int(recipient_checks.get("tracked") or 0)
        recipient_fresh = int(recipient_checks.get("fresh") or 0)
        recipient_stale = int(recipient_checks.get("stale") or 0)
        recipient_unchecked = int(recipient_checks.get("unchecked") or 0)
        recipient_changed = int(recipient_checks.get("changed") or 0)
        recipient_lookup_failed = int(recipient_checks.get("lookupFailed") or 0)
        recipient_stale_after = int(recipient_checks.get("staleAfterSeconds") or 0)
        recipient_reconciliation_degraded = recipient_tracked > 0 and (
            recipient_stale > 0 or recipient_lookup_failed > 0
        )
        broker_degraded = (
            circuits > 0 or permanent_failures > 0 or request_failures > 0 or recipient_reconciliation_degraded
        )
        broker_issues = []
        if circuits:
            broker_issues.append(f"{circuits} circuit(s) ouvert(s)")
        if permanent_failures:
            broker_issues.append(f"{permanent_failures} échec(s) permanent(s) à traiter")
        if request_failures:
            broker_issues.append(f"{request_failures} échec(s) de requête non retentable(s) à corriger")
        if recipient_stale:
            broker_issues.append(f"{recipient_stale} contrôle(s) destinataire périmé(s)")
        if recipient_lookup_failed:
            broker_issues.append(f"{recipient_lookup_failed} contrôle(s) Mercure en échec")
        if broker_issues:
            broker_detail = " · ".join(broker_issues)
        elif permanent_acknowledged:
            broker_detail = f"Broker opérationnel · {permanent_acknowledged} incident(s) permanent(s) acquitté(s)"
        else:
            broker_detail = "Broker et ledger opérationnels"
        components.append(_component(
            "notification_broker", "NotificationBroker", "degraded" if broker_degraded else "ready",
            broker_detail,
            critical=True,
            metrics={
                "circuitsOpen": circuits,
                "permanentFailures": permanent_failures,
                "requestFailures": request_failures,
                "permanentFailureHistory": permanent_history,
                "permanentAcknowledged": permanent_acknowledged,
                "permanentResolved": permanent_resolved,
                "recipientChecksTracked": recipient_tracked,
                "recipientChecksFresh": recipient_fresh,
                "recipientChecksStale": recipient_stale,
                "recipientChecksUnchecked": recipient_unchecked,
                "recipientCorrectionsDetected": recipient_changed,
                "recipientLookupFailed": recipient_lookup_failed,
                "recipientChecksStaleAfterSeconds": recipient_stale_after,
            },
        ))
        preflight, preflight_error = _safe("notification preflight", notification_preflight.run)
        channels = broker.get("channels") or {}
        email = channels.get("email") or {}
        email_configured = bool(email.get("configured"))
        email_probe = ((preflight or {}).get("email") or {}) if not preflight_error else {}
        email_ready = email_configured and not preflight_error and bool(email_probe.get("ok"))
        if not email_configured:
            email_state = "configuration_required"
            email_detail = "SMTP ou Gmail OAuth requis"
        elif email_ready:
            email_state = "ready"
            email_detail = f"Transport {email.get('transport')} validé par préflight"
        else:
            email_state = "degraded"
            email_detail = "Transport e-mail configuré mais préflight non prêt"
        components.append(_component(
            "email_delivery", "Livraison e-mail", email_state, email_detail,
            critical=True,
            metrics={
                "transport": email.get("transport") or "none",
                "preflightState": email_probe.get("state") or ("unavailable" if preflight_error else "unknown"),
            },
        ))
        push = channels.get("push") or {}
        push_configured = bool(push.get("configured"))
        push_probe = ((preflight or {}).get("push") or {}) if not preflight_error else {}
        push_ready = push_configured and not preflight_error and bool(push_probe.get("ready"))
        if not push_configured:
            push_state = "configuration_required"
            push_detail = "Clé APNs, Key ID et Team ID requis"
        elif push_ready:
            push_state = "ready"
            push_detail = "Identifiants APNs validés localement"
        else:
            push_state = "degraded"
            push_detail = "APNs configuré mais préflight local non prêt"
        components.append(_component(
            "apns", "Push APNs", push_state, push_detail,
            critical=False,
            metrics={
                "preflightState": push_probe.get("state") or ("unavailable" if preflight_error else "unknown"),
                "keyValid": bool(push_probe.get("keyValid")),
            },
        ))

    distribution, error = _safe("distribution iOS", lambda: app_download.status(config))
    if error:
        components.append(_failed("ios_distribution", "Distribution iOS", False, error))
    else:
        ios = distribution.get("ios") or {}
        available = bool(ios.get("available")) and bool(ios.get("targetUrl"))
        components.append(_component(
            "ios_distribution", "Distribution iOS", "ready" if available else "blocked_external",
            f"Canal {ios.get('channel')} actif" if available else "Publication TestFlight ou App Store requise",
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

    release, error = _safe("préflight Release iOS", lambda: ios_release_preflight.status(config))
    if error:
        components.append(_failed("ios_release_preflight", "Préflight Release iOS", False, error))
    else:
        release_state = str(release.get("state") or "degraded")
        if release_state not in _STATE_RANK:
            release_state = "degraded"
        details = {
            "ready": "Projet iOS, AASA et distribution Apple cohérents",
            "configuration_required": "Préfixe Apple requis pour valider AASA et le claim",
            "blocked_external": "Projet iOS cohérent ; publication TestFlight ou App Store requise",
            "degraded": "Configuration Release iOS incohérente",
        }
        failed_checks = [item.get("code") for item in release.get("checks") or [] if not item.get("ok")]
        components.append(_component(
            "ios_release_preflight", "Préflight Release iOS", release_state, details[release_state],
            critical=False,
            metrics={
                "projectReady": bool(release.get("projectReady")),
                "associationReady": bool(release.get("associationReady")),
                "publicationReady": bool(release.get("publicationReady")),
                "channel": release.get("channel") or "pending",
                "failedChecks": failed_checks,
            },
        ))

    google_canonical = str((config.get("seo") or {}).get("canonicalUrl") or "").strip()
    google_parsed = urlparse(google_canonical)
    google_origin = f"{google_parsed.scheme}://{google_parsed.netloc}" if google_parsed.scheme and google_parsed.netloc else ""
    integrations, error = _safe(
        "IntegrationHub",
        lambda: integration_hub.status(gsc_client.credential_info(), google_origin),
    )
    if error:
        components.append(_failed("google_integration", "IntegrationHub Google", False, error))
    else:
        components.append(_google_integration_component(integrations))

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

    referral_snapshot, error = _safe("parrainage", lambda: {
        "accounts": referral_engine.list_accounts(100),
        "integrity": referral_integrity_audit.status(),
    })
    if error:
        components.append(_failed("referrals", "Parrainage / cagnotte", False, error))
    else:
        accounts = referral_snapshot.get("accounts") or []
        integrity = referral_snapshot.get("integrity") or {}
        integrity_metrics = integrity.get("metrics") or {}
        integrity_issues = int(integrity.get("issues") or 0)
        integrity_ok = bool(integrity.get("ok")) and integrity_issues == 0
        components.append(_component(
            "referrals", "Parrainage / cagnotte", "ready" if integrity_ok else "degraded",
            "Ledger de parrainage opérationnel et cohérent" if integrity_ok else "Anomalies d’intégrité du ledger de parrainage",
            critical=False,
            metrics={
                "accounts": len(accounts),
                "rewardCents": referral_engine.configured_reward_cents(),
                "integrityIssues": integrity_issues,
                "accountsInDebt": int(integrity_metrics.get("accountsInDebt") or 0),
                "ambiguousLegacyReferences": int(integrity_metrics.get("ambiguousLegacyReferences") or 0),
                "missingEarns": int(integrity_metrics.get("missingEarns") or 0),
                "orphanEarns": int(integrity_metrics.get("orphanEarns") or 0),
                "amountMismatches": int(integrity_metrics.get("amountMismatches") or 0),
                "missingReversals": int(integrity_metrics.get("missingReversals") or 0),
                "orphanReversals": int(integrity_metrics.get("orphanReversals") or 0),
            },
        ))

    reviews, error = _safe("avis Google", review_followup.status)
    if error:
        components.append(_failed("review_followup", "Relance avis Google", False, error))
    else:
        review_transport_configured = bool(reviews.get("emailTransportConfigured"))
        review_transport_ready = bool(reviews.get("emailTransportReady"))
        review_url_ready = bool(reviews.get("reviewUrlConfigured"))
        review_ready = review_transport_ready and review_url_ready
        if review_ready:
            review_state = "ready"
            review_detail = "Relance neutre prête"
        elif review_transport_configured and review_url_ready:
            review_state = "degraded"
            review_detail = "Transport e-mail configuré mais préflight non prêt"
        else:
            review_state = "configuration_required"
            review_detail = "Transport e-mail et URL d’avis valides requis"
        components.append(_component(
            "review_followup", "Relance avis Google", review_state, review_detail,
            critical=False,
            metrics={
                "sentTotal": int(reviews.get("sentTotal") or 0),
                "emailPreflightState": reviews.get("emailPreflightState") or "unknown",
            },
        ))

    if seo_health is None:
        seo_health = {"totals": {"pass": 0, "warning": 1, "fail": 0}}
    totals = seo_health.get("totals") or {}
    failures = int(totals.get("fail") or 0)
    warnings = int(totals.get("warning") or 0)
    infos = int(totals.get("info") or 0)
    seo_state = "degraded" if failures else "configuration_required" if warnings else "ready"
    components.append(_component(
        "seo", "SEO", seo_state,
        f"{failures} échec(s), {warnings} avertissement(s), {infos} information(s)",
        critical=False,
        metrics={"pass": int(totals.get("pass") or 0), "info": infos, "warning": warnings, "fail": failures},
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
        delivery = alerts.get("delivery") or {}
        retry = delivery.get("retry") or {}
        last_failure = retry.get("lastFailure") or {}
        delivery_ready = bool(delivery.get("ready"))
        delivery_state = str(delivery.get("state") or ("ready" if delivery_ready else "awaiting_webhook"))
        if not delivery_ready:
            state = "configuration_required" if delivery_state in {"awaiting_webhook", "awaiting_signing_secret"} else "degraded"
            detail = "Relais d’alertes externe à configurer" if state == "configuration_required" else "Relais d’alertes externe invalide ou indisponible"
        elif undelivered:
            state = "degraded"
            detail = f"{undelivered} alerte(s) haute/critique encore à relayer"
        else:
            state = "ready"
            detail = "Relais d’alertes externe prêt et aucune alerte haute/critique en attente"
        components.append(_component(
            "alert_delivery", "Alertes opérationnelles", state, detail,
            critical=False,
            metrics={
                "open": int(alerts.get("open") or 0),
                "undeliveredHighOrCritical": undelivered,
                "deliveryState": delivery_state,
                "signed": bool(delivery.get("signed")),
                "endpointHost": delivery.get("endpointHost"),
                "retryEligible": int(retry.get("eligible") or 0),
                "retryDeferred": int(retry.get("deferred") or 0),
                "lastFailureReason": last_failure.get("reason"),
                "lastFailureAt": last_failure.get("at"),
                "nextAttemptAt": last_failure.get("nextAttemptAt"),
            },
        ))

    counts = {state: 0 for state in _STATE_RANK}
    for item in components:
        counts[item["state"]] += 1
    overall = max((item["state"] for item in components), key=lambda state: _STATE_RANK[state])
    critical = [item for item in components if item["critical"]]
    critical_blockers = [item["id"] for item in critical if item["state"] != "ready"]
    launch_ready = not critical_blockers
    blockers = [item["id"] for item in components if item["state"] != "ready"]
    return {
        "ok": True,
        "schemaVersion": 2,
        "state": overall,
        "launchReady": launch_ready,
        "counts": counts,
        "blockers": blockers,
        "criticalBlockers": critical_blockers,
        "activationGate": {
            "allowed": launch_ready,
            "state": "open" if launch_ready else "blocked",
            "policy": "all_critical_components_ready",
            "blockingComponents": critical_blockers,
        },
        "components": components,
        "privacy": "Le diagnostic n’expose aucun secret, token, identifiant client ou donnée Mercure nominative.",
    }