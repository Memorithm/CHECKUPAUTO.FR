from __future__ import annotations

import uuid
from pathlib import Path

import marketing_consent
import mobile_devices
import notification_broker
import notification_privacy
import privacy_suppression


EMAIL_CATEGORY = "marketing_email"
PUSH_CATEGORY = "marketing_push"


def _reference(value: object) -> str:
    clean = str(value or "").strip()
    if not clean or len(clean) > 160:
        raise ValueError("référence marketing invalide")
    return clean


def _installation_id(value: object) -> str:
    raw = str(value or "").strip().lower()
    try:
        parsed = uuid.UUID(raw)
    except (ValueError, AttributeError) as exc:
        raise ValueError("installationId invalide") from exc
    if str(parsed) != raw:
        raise ValueError("installationId invalide")
    return raw


def _consent_evidence(result: dict) -> dict:
    return {
        "reason": str(result.get("reason") or ""),
        "consentId": str(result.get("consentId") or ""),
        "statementVersion": str(result.get("statementVersion") or ""),
        "statementHash": str(result.get("statementHash") or ""),
        "validUntil": str(result.get("validUntil") or ""),
    }


def send_email(
    recipient: str,
    subject: str,
    text: str,
    html: str = "",
    *,
    reference: object,
    consent_db_path: Path | str | None = None,
) -> dict:
    """Send a B2C marketing e-mail only after explicit-consent authorization.

    Transactional e-mail continues to use NotificationBroker directly. This
    facade is intentionally specific to direct-marketing sends so accepting
    CGV or receiving a service message can never implicitly authorize a
    campaign.
    """
    ref = _reference(reference)
    authorization = marketing_consent.require_authorized(
        "email", recipient, db_path=consent_db_path
    )
    normalized_recipient = str(recipient or "").strip().lower()
    notification_privacy.bind_marketing_recipient(
        privacy_suppression.identity_hash("email", normalized_recipient),
        "email",
        normalized_recipient,
    )
    delivery = notification_broker.send_email(
        recipient,
        subject,
        text,
        html,
        category=EMAIL_CATEGORY,
        reference=ref,
    )
    return {
        "ok": bool(delivery.get("ok")),
        "channel": "email",
        "reference": ref,
        "consent": _consent_evidence(authorization),
        "delivery": delivery,
    }


def _active_push_target(installation_id: str) -> tuple[str, str]:
    mobile_devices.init_db()
    with mobile_devices.connect() as db:
        row = db.execute(
            """SELECT device_token,environment,disabled_at
               FROM mobile_device WHERE installation_id=?""",
            (installation_id,),
        ).fetchone()
    if row is None or str(row["disabled_at"] or "") or not str(row["device_token"] or ""):
        raise PermissionError("canal push marketing indisponible")
    environment = str(row["environment"] or "").strip().lower()
    if environment not in {"sandbox", "production"}:
        raise PermissionError("canal push marketing indisponible")
    return str(row["device_token"]), environment


def send_push(
    installation_id: object,
    title: str,
    body: str,
    *,
    reference: object,
    data: dict | None = None,
    consent_db_path: Path | str | None = None,
) -> dict:
    """Send marketing push only to the token bound to a consented installation.

    Callers never supply the APNs token. It is resolved from the authoritative
    mobile-device registry after consent succeeds, preventing a consent record
    for one installation from being combined with another device token.
    """
    install = _installation_id(installation_id)
    ref = _reference(reference)
    authorization = marketing_consent.require_authorized(
        "push", install, db_path=consent_db_path
    )
    token, environment = _active_push_target(install)
    notification_privacy.bind_marketing_recipient(
        privacy_suppression.identity_hash("installation", install),
        "push",
        f"{environment}:{token}",
    )
    delivery = notification_broker.send_push(
        token,
        title,
        body,
        category=PUSH_CATEGORY,
        reference=ref,
        data=data,
        environment=environment,
    )
    return {
        "ok": bool(delivery.get("ok")),
        "channel": "push",
        "reference": ref,
        "consent": _consent_evidence(authorization),
        "delivery": delivery,
    }


def send_sms(*args, **kwargs):
    raise NotImplementedError("transport SMS marketing non configuré")


def call_phone(*args, **kwargs):
    raise NotImplementedError("transport téléphonique marketing non configuré")
