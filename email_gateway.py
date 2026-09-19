from __future__ import annotations

import base64
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import parseaddr
import os
import smtplib
import ssl

import requests

import integration_hub as google_integration

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GMAIL_TRANSIENT_STATUS = {429, 500, 502, 503, 504}
GMAIL_TRANSIENT_REASONS = {
    "backendError",
    "dailyLimitExceeded",
    "internalError",
    "quotaExceeded",
    "rateLimitExceeded",
    "userRateLimitExceeded",
}
SMTP_CONFIGURATION_CODES = {530, 534, 535, 538}


class EmailDeliveryError(RuntimeError):
    """Typed delivery failure safe to persist in NotificationBroker diagnostics."""

    def __init__(
        self,
        message: str,
        *,
        transport: str,
        status: int = 0,
        reason: str = "",
        retry_after: str = "",
        retryable: bool = False,
        configuration_error: bool = False,
        permanent: bool = False,
    ):
        self.transport = str(transport or "email")[:40]
        self.status = int(status or 0)
        self.reason = str(reason or "")[:80]
        self.retry_after = str(retry_after or "")[:80]
        self.retryable = bool(retryable)
        self.configuration_error = bool(configuration_error)
        self.permanent = bool(permanent)
        super().__init__(str(message or "Erreur de livraison e-mail")[:180])

    @property
    def failure_class(self) -> str:
        if self.configuration_error:
            return "configuration"
        if self.permanent:
            return "permanent"
        return "transient"


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    sender: str
    mode: str
    username: str = ""
    password: str = field(default="", repr=False)
    timeout: float = 20.0


def _env(name: str) -> str:
    return str(os.environ.get(name, "") or "").strip()


def valid_email(value: object) -> bool:
    raw = str(value or "").strip()
    if not raw or len(raw) > 254 or any(ord(ch) < 32 for ch in raw):
        return False
    name, address = parseaddr(raw)
    if name and address != raw:
        return False
    if address != raw or address.count("@") != 1:
        return False
    local, domain = address.rsplit("@", 1)
    return bool(local and "." in domain and not domain.startswith(".") and not domain.endswith("."))


def load_config() -> SMTPConfig | None:
    sender = _env("CYBERCHECK_SMTP_FROM")
    if not sender:
        return None
    host = _env("CYBERCHECK_SMTP_HOST") or "127.0.0.1"
    mode = (_env("CYBERCHECK_SMTP_MODE") or "plain").lower()
    if mode not in {"starttls", "ssl", "plain"}:
        raise ValueError("CYBERCHECK_SMTP_MODE must be starttls, ssl or plain")
    default_port = 465 if mode == "ssl" else (587 if mode == "starttls" else 25)
    try:
        port = int(_env("CYBERCHECK_SMTP_PORT") or default_port)
    except ValueError as exc:
        raise ValueError("CYBERCHECK_SMTP_PORT invalid") from exc
    if port < 1 or port > 65535:
        raise ValueError("CYBERCHECK_SMTP_PORT invalid")
    if not valid_email(sender):
        raise ValueError("CYBERCHECK_SMTP_FROM invalid")
    username = _env("CYBERCHECK_SMTP_USERNAME")
    password = _env("CYBERCHECK_SMTP_PASSWORD")
    if bool(username) != bool(password):
        raise ValueError("CYBERCHECK_SMTP_USERNAME and CYBERCHECK_SMTP_PASSWORD must be configured together")
    if username and mode == "plain":
        raise ValueError("SMTP authentication requires starttls or ssl")
    return SMTPConfig(host=host, port=port, sender=sender, mode=mode, username=username, password=password)


def _transport_mode() -> str:
    mode = (_env("CYBERCHECK_EMAIL_TRANSPORT") or "auto").lower()
    if mode not in {"auto", "smtp", "gmail"}:
        raise ValueError("CYBERCHECK_EMAIL_TRANSPORT must be auto, smtp or gmail")
    return mode


def _gmail_sender() -> str:
    configured = str(google_integration.settings().get("gmailSender") or "").strip()
    return configured or _env("CYBERCHECK_GMAIL_FROM")


def smtp_configured() -> bool:
    try:
        return load_config() is not None
    except ValueError:
        return False


def gmail_configured() -> bool:
    try:
        sender = _gmail_sender()
        return valid_email(sender) and google_integration.has_scopes([GMAIL_SEND_SCOPE])
    except (OSError, google_integration.IntegrationError):
        return False


def active_transport() -> str | None:
    try:
        mode = _transport_mode()
    except ValueError:
        return None
    if mode in {"auto", "smtp"} and smtp_configured():
        return "smtp-relay"
    if mode in {"auto", "gmail"} and gmail_configured():
        return "gmail-api"
    return None


def configured() -> bool:
    return active_transport() is not None


def transport_status() -> dict:
    try:
        requested = _transport_mode()
        config_error = ""
    except ValueError as exc:
        return {
            "configured": False,
            "transport": "none",
            "requested": "invalid",
            "smtpAvailable": smtp_configured(),
            "gmailAvailable": False,
            "state": "invalid_configuration",
            "error": str(exc),
        }
    smtp_available = smtp_configured()
    gmail_available = gmail_configured()
    transport = None
    if requested in {"auto", "smtp"} and smtp_available:
        transport = "smtp-relay"
    elif requested in {"auto", "gmail"} and gmail_available:
        transport = "gmail-api"
    ready = transport is not None
    return {
        "configured": ready,
        "transport": transport or "none",
        "requested": requested,
        "smtpAvailable": smtp_available,
        "gmailAvailable": gmail_available,
        "state": "ready" if ready else "awaiting_configuration",
        "error": config_error,
    }


def _message(to: str, sender: str, subject: str, text: str, html: str = "") -> EmailMessage:
    recipient = str(to or "").strip()
    if not valid_email(recipient):
        raise ValueError("Adresse destinataire invalide")
    if not valid_email(sender):
        raise ValueError("Adresse expéditeur invalide")
    clean_subject = str(subject or "").replace("\r", " ").replace("\n", " ").strip()[:180]
    if not clean_subject:
        raise ValueError("Objet email requis")
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = clean_subject
    message.set_content(str(text or ""))
    if html:
        message.add_alternative(str(html), subtype="html")
    return message


def _smtp_code(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _smtp_error(exc: Exception) -> EmailDeliveryError:
    transport = "smtp-relay"
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        code = _smtp_code(getattr(exc, "smtp_code", 0))
        return EmailDeliveryError(
            f"SMTP authentification refusée ({code or 'erreur'})",
            transport=transport,
            status=code,
            reason="authentication",
            configuration_error=True,
        )
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        codes = []
        for item in (getattr(exc, "recipients", {}) or {}).values():
            if isinstance(item, (tuple, list)) and item:
                codes.append(_smtp_code(item[0]))
        code = next((item for item in codes if 400 <= item < 500), 0) or next((item for item in codes if item), 0)
        retryable = bool(code and 400 <= code < 500)
        return EmailDeliveryError(
            f"SMTP destinataire refusé ({code or 'erreur'})",
            transport=transport,
            status=code,
            reason="recipient_refused",
            retryable=retryable,
            permanent=not retryable,
        )
    if isinstance(exc, smtplib.SMTPSenderRefused):
        code = _smtp_code(getattr(exc, "smtp_code", 0))
        retryable = 400 <= code < 500
        return EmailDeliveryError(
            f"SMTP expéditeur refusé ({code or 'erreur'})",
            transport=transport,
            status=code,
            reason="sender_refused",
            retryable=retryable,
            configuration_error=not retryable,
        )
    if isinstance(exc, smtplib.SMTPNotSupportedError):
        return EmailDeliveryError(
            "SMTP fonctionnalité requise indisponible",
            transport=transport,
            reason="not_supported",
            configuration_error=True,
        )
    if isinstance(exc, smtplib.SMTPResponseException):
        code = _smtp_code(getattr(exc, "smtp_code", 0))
        if code in SMTP_CONFIGURATION_CODES:
            return EmailDeliveryError(
                f"SMTP configuration refusée ({code})",
                transport=transport,
                status=code,
                reason="configuration",
                configuration_error=True,
            )
        retryable = 400 <= code < 500
        permanent = 500 <= code < 600
        return EmailDeliveryError(
            f"SMTP erreur protocolaire ({code or 'erreur'})",
            transport=transport,
            status=code,
            reason="smtp_response",
            retryable=retryable,
            permanent=permanent,
        )
    if isinstance(exc, (smtplib.SMTPServerDisconnected, TimeoutError, OSError, smtplib.SMTPException)):
        return EmailDeliveryError(
            "SMTP indisponible",
            transport=transport,
            reason="transport",
            retryable=True,
        )
    return EmailDeliveryError("SMTP indisponible", transport=transport, reason="unknown", retryable=True)


def _open_smtp(cfg: SMTPConfig):
    context = ssl.create_default_context()
    if cfg.mode == "ssl":
        client = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=cfg.timeout, context=context)
    else:
        client = smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout)
    client.ehlo()
    if cfg.mode == "starttls":
        client.starttls(context=context)
        client.ehlo()
    if cfg.username:
        client.login(cfg.username, cfg.password)
    return client


def _close_smtp(client) -> None:
    if client is None:
        return
    try:
        client.quit()
    except Exception:
        try:
            client.close()
        except Exception:
            pass


def _send_smtp(cfg: SMTPConfig, to: str, subject: str, text: str, html: str = "") -> dict:
    message = _message(to, cfg.sender, subject, text, html)
    client = None
    try:
        client = _open_smtp(cfg)
        refused = client.send_message(message)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    except EmailDeliveryError:
        raise
    except Exception as exc:
        raise _smtp_error(exc) from exc
    finally:
        _close_smtp(client)
    return {"ok": True, "channel": "email", "transport": "smtp-relay"}


def _safe_reason(value: object) -> str:
    raw = str(value or "")
    return "".join(ch for ch in raw if ch.isalnum() or ch in "._-")[:80]


def _gmail_response_error(response) -> EmailDeliveryError:
    status = _smtp_code(getattr(response, "status_code", 0))
    reason = ""
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            errors = error.get("errors")
            if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                reason = _safe_reason(errors[0].get("reason"))
            if not reason:
                reason = _safe_reason(error.get("status"))
    except Exception:
        pass
    retry_after = str(getattr(response, "headers", {}).get("Retry-After", "") or "")[:80]
    retryable = status in GMAIL_TRANSIENT_STATUS or reason in GMAIL_TRANSIENT_REASONS
    configuration_error = status in {401, 403} and not retryable
    permanent = status >= 400 and not retryable and not configuration_error
    suffix = f" · {reason}" if reason else ""
    return EmailDeliveryError(
        f"Gmail API a refusé l’envoi (HTTP {status}){suffix}",
        transport="gmail-api",
        status=status,
        reason=reason or "gmail_http_error",
        retry_after=retry_after,
        retryable=retryable,
        configuration_error=configuration_error,
        permanent=permanent,
    )


def _google_token_error(exc: google_integration.IntegrationError) -> EmailDeliveryError:
    status = _smtp_code(getattr(exc, "status", 0))
    retry_after = str(getattr(exc, "retry_after", "") or "")[:80]
    retryable = bool(getattr(exc, "retryable", False)) or isinstance(exc.__cause__, requests.RequestException)
    return EmailDeliveryError(
        "Google OAuth temporairement indisponible" if retryable else "Google OAuth doit être reconfiguré",
        transport="gmail-api",
        status=status,
        reason="oauth",
        retry_after=retry_after,
        retryable=retryable,
        configuration_error=not retryable,
    )


def _send_gmail(to: str, subject: str, text: str, html: str = "") -> dict:
    sender = _gmail_sender()
    if not valid_email(sender):
        raise EmailDeliveryError(
            "Adresse d’envoi Gmail non configurée",
            transport="gmail-api",
            reason="sender_configuration",
            configuration_error=True,
        )
    try:
        token = google_integration.google_access_token([GMAIL_SEND_SCOPE])
    except google_integration.IntegrationError as exc:
        raise _google_token_error(exc) from exc
    message = _message(to, sender, subject, text, html)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    try:
        response = requests.post(
            GMAIL_SEND_URL,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            json={"raw": raw},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise EmailDeliveryError(
            "Gmail API indisponible",
            transport="gmail-api",
            reason="transport",
            retryable=True,
        ) from exc
    if response.status_code >= 400:
        raise _gmail_response_error(response)
    try:
        message_id = str((response.json() or {}).get("id") or "")
    except Exception:
        message_id = ""
    return {"ok": True, "channel": "email", "transport": "gmail-api", "messageId": message_id}



def _preflight_failure(transport: str, exc: EmailDeliveryError) -> dict:
    if exc.configuration_error:
        state = "invalid_configuration"
    elif exc.retryable:
        state = "provider_unavailable"
    elif exc.permanent:
        state = "provider_rejected"
    else:
        state = "failed"
    return {
        "transport": transport,
        "ready": False,
        "state": state,
        "failureClass": exc.failure_class,
        "status": exc.status,
        "reason": exc.reason,
        "retryAfter": exc.retry_after,
    }


def smtp_preflight() -> dict:
    """Validate SMTP configuration/connectivity without sending a message."""
    try:
        cfg = load_config()
    except ValueError as exc:
        return {"transport": "smtp-relay", "ready": False, "state": "invalid_configuration", "failureClass": "configuration", "status": 0, "reason": str(exc)[:120]}
    if cfg is None:
        return {"transport": "smtp-relay", "ready": False, "state": "awaiting_configuration", "failureClass": "configuration", "status": 0, "reason": "sender_missing"}
    client = None
    try:
        client = _open_smtp(cfg)
        code, _ = client.noop()
        code = _smtp_code(code)
        if code >= 400:
            raise smtplib.SMTPResponseException(code, b"NOOP refused")
    except Exception as exc:
        return _preflight_failure("smtp-relay", _smtp_error(exc))
    finally:
        _close_smtp(client)
    return {
        "transport": "smtp-relay",
        "ready": True,
        "state": "ready",
        "failureClass": "",
        "status": 200,
        "reason": "connection_validated",
        "tls": cfg.mode in {"starttls", "ssl"},
        "authentication": bool(cfg.username),
    }


def gmail_preflight() -> dict:
    """Validate Gmail sender, scope and OAuth refresh without sending a message."""
    sender = _gmail_sender()
    if not valid_email(sender):
        return {"transport": "gmail-api", "ready": False, "state": "awaiting_configuration", "failureClass": "configuration", "status": 0, "reason": "sender_missing_or_invalid"}
    try:
        scope_ok = google_integration.has_scopes([GMAIL_SEND_SCOPE])
    except (OSError, google_integration.IntegrationError):
        scope_ok = False
    if not scope_ok:
        return {"transport": "gmail-api", "ready": False, "state": "awaiting_configuration", "failureClass": "configuration", "status": 0, "reason": "gmail_send_scope_missing"}
    try:
        token = google_integration.google_access_token([GMAIL_SEND_SCOPE], force_refresh=True)
        if not token:
            raise google_integration.IntegrationError("Jeton Google absent")
    except google_integration.IntegrationError as exc:
        return _preflight_failure("gmail-api", _google_token_error(exc))
    return {"transport": "gmail-api", "ready": True, "state": "ready", "failureClass": "", "status": 200, "reason": "oauth_token_validated"}


def preflight() -> dict:
    try:
        requested = _transport_mode()
    except ValueError as exc:
        requested = "invalid"
        mode_error = str(exc)[:120]
    else:
        mode_error = ""
    smtp = smtp_preflight()
    gmail = gmail_preflight()
    active = active_transport() or "none"
    selected = smtp if active == "smtp-relay" else gmail if active == "gmail-api" else None
    return {
        "ok": bool(selected and selected.get("ready")),
        "requested": requested,
        "activeTransport": active,
        "state": selected.get("state") if selected else ("invalid_configuration" if mode_error else "awaiting_configuration"),
        "error": mode_error,
        "transports": [smtp, gmail],
    }

def send_email(to: str, subject: str, text: str, html: str = "") -> dict:
    mode = _transport_mode()
    if mode in {"auto", "smtp"}:
        cfg = load_config()
        if cfg is not None:
            return _send_smtp(cfg, to, subject, text, html)
        if mode == "smtp":
            raise EmailDeliveryError(
                "SMTP Checkup Auto non configuré",
                transport="smtp-relay",
                reason="configuration",
                configuration_error=True,
            )
    if mode in {"auto", "gmail"}:
        if gmail_configured():
            return _send_gmail(to, subject, text, html)
        if mode == "gmail":
            raise EmailDeliveryError(
                "Gmail Checkup Auto non configuré",
                transport="gmail-api",
                reason="configuration",
                configuration_error=True,
            )
    raise EmailDeliveryError(
        "Aucun transport e-mail Checkup Auto n’est configuré",
        transport="email:none",
        reason="configuration",
        configuration_error=True,
    )
