from __future__ import annotations

import base64
import ipaddress
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import parseaddr
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
import tempfile

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
GMAIL_PROVIDER_REASONS = GMAIL_TRANSIENT_REASONS | {
    "authError",
    "badRequest",
    "domainPolicy",
    "notFound",
    "permissionDenied",
}
GMAIL_STATUS_REASON_MAP = {
    "INVALID_ARGUMENT": "badRequest",
    "UNAUTHENTICATED": "authError",
    "PERMISSION_DENIED": "permissionDenied",
    "RESOURCE_EXHAUSTED": "quotaExceeded",
    "NOT_FOUND": "notFound",
    "INTERNAL": "internalError",
    "UNAVAILABLE": "backendError",
    "DEADLINE_EXCEEDED": "backendError",
}
SMTP_CONFIGURATION_CODES = {530, 534, 535, 538}
SMTP_PRIVATE_SCHEMA = "checkupauto.smtp-private/v1"
SMTP_PRIVATE_FILENAME = "smtp-transport.json"
_HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")


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


def _bool_env(name: str) -> bool:
    return _env(name).lower() in {"1", "true", "yes", "on"}


def _local_smtp_host(host: str) -> bool:
    value = str(host or "").strip().lower()
    if value in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _remote_smtp_authentication_missing(cfg: SMTPConfig) -> bool:
    return (
        not cfg.username
        and not _local_smtp_host(cfg.host)
        and not _bool_env("CYBERCHECK_SMTP_ALLOW_UNAUTHENTICATED_REMOTE")
    )


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


def _private_dir() -> Path:
    return Path(
        os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate")
    ).expanduser()


def _smtp_private_path() -> Path:
    return _private_dir() / "integrations" / SMTP_PRIVATE_FILENAME


def _ensure_smtp_private_dir() -> Path:
    root = _smtp_private_path().parent
    if root.exists() and root.is_symlink():
        raise RuntimeError("répertoire SMTP privé invalide")
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    return root


def _clean_host(value: object) -> str:
    host = str(value or "").strip().lower()
    if (
        not _HOST_RE.fullmatch(host)
        or host.startswith(".")
        or host.endswith(".")
        or ".." in host
    ):
        raise ValueError("hôte SMTP invalide")
    return host


def _clean_secret(value: object) -> str:
    secret = str(value or "")
    if not secret or len(secret) > 512 or any(ord(ch) < 32 for ch in secret):
        raise ValueError("mot de passe SMTP invalide")
    return secret


def _smtp_config_from_values(
    *,
    host: object,
    port: object,
    sender: object,
    mode: object,
    username: object = "",
    password: object = "",
) -> SMTPConfig:
    clean_host = _clean_host(host)
    clean_mode = str(mode or "").strip().lower()
    if clean_mode not in {"starttls", "ssl", "plain"}:
        raise ValueError("mode SMTP invalide")
    try:
        clean_port = int(port)
    except (TypeError, ValueError) as exc:
        raise ValueError("port SMTP invalide") from exc
    if clean_port < 1 or clean_port > 65535:
        raise ValueError("port SMTP invalide")
    clean_sender = str(sender or "").strip()
    if not valid_email(clean_sender):
        raise ValueError("expéditeur SMTP invalide")
    clean_username = str(username or "").strip()
    clean_password = str(password or "")
    if bool(clean_username) != bool(clean_password):
        raise ValueError("identifiant et mot de passe SMTP requis ensemble")
    if clean_username:
        if len(clean_username) > 254 or any(ord(ch) < 32 for ch in clean_username):
            raise ValueError("identifiant SMTP invalide")
        clean_password = _clean_secret(clean_password)
        if clean_mode == "plain":
            raise ValueError("SMTP authentication requires starttls or ssl")
    return SMTPConfig(
        host=clean_host,
        port=clean_port,
        sender=clean_sender,
        mode=clean_mode,
        username=clean_username,
        password=clean_password,
    )


def _load_environment_config() -> SMTPConfig | None:
    sender = _env("CYBERCHECK_SMTP_FROM")
    if not sender:
        return None
    host = _env("CYBERCHECK_SMTP_HOST") or "127.0.0.1"
    mode = (_env("CYBERCHECK_SMTP_MODE") or "plain").lower()
    default_port = 465 if mode == "ssl" else (587 if mode == "starttls" else 25)
    port = _env("CYBERCHECK_SMTP_PORT") or str(default_port)
    return _smtp_config_from_values(
        host=host,
        port=port,
        sender=sender,
        mode=mode,
        username=_env("CYBERCHECK_SMTP_USERNAME"),
        password=_env("CYBERCHECK_SMTP_PASSWORD"),
    )


def _private_smtp_exists() -> bool:
    path = _smtp_private_path()
    try:
        return path.exists()
    except PermissionError as exc:
        if not _env("CYBERCHECK_PRIVATE_DIR"):
            return False
        raise RuntimeError("configuration SMTP privée inaccessible") from exc


def _load_private_smtp_payload() -> dict | None:
    path = _smtp_private_path()
    if not _private_smtp_exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("configuration SMTP privée invalide")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError("configuration SMTP privée invalide") from exc
    if not isinstance(payload, dict) or payload.get("schema") != SMTP_PRIVATE_SCHEMA:
        raise RuntimeError("configuration SMTP privée invalide")
    return payload


def _private_smtp_config() -> SMTPConfig | None:
    payload = _load_private_smtp_payload()
    if payload is None:
        return None
    return _smtp_config_from_values(
        host=payload.get("host"),
        port=payload.get("port"),
        sender=payload.get("sender"),
        mode=payload.get("mode"),
        username=payload.get("username"),
        password=payload.get("password"),
    )


def load_config() -> SMTPConfig | None:
    environment = _load_environment_config()
    if environment is not None:
        return environment
    return _private_smtp_config()


def smtp_config_info() -> dict:
    source = "environment" if _env("CYBERCHECK_SMTP_FROM") else (
        "private" if _private_smtp_exists() else "none"
    )
    try:
        cfg = load_config()
    except Exception:
        return {
            "configured": False,
            "source": source,
            "state": "invalid_configuration",
            "host": "",
            "port": 0,
            "mode": "",
            "sender": "",
            "username": "",
            "usernameConfigured": False,
            "passwordConfigured": False,
        }
    if cfg is None:
        return {
            "configured": False,
            "source": "none",
            "state": "awaiting_configuration",
            "host": "",
            "port": 0,
            "mode": "",
            "sender": "",
            "username": "",
            "usernameConfigured": False,
            "passwordConfigured": False,
        }
    return {
        "configured": True,
        "source": source,
        "state": "configured",
        "host": cfg.host,
        "port": cfg.port,
        "mode": cfg.mode,
        "sender": cfg.sender,
        "username": cfg.username,
        "usernameConfigured": bool(cfg.username),
        "passwordConfigured": bool(cfg.password),
    }


def save_private_smtp_config(payload: object) -> dict:
    if _env("CYBERCHECK_SMTP_FROM"):
        raise RuntimeError("configuration SMTP pilotée par environnement")
    if not isinstance(payload, dict):
        raise ValueError("configuration SMTP invalide")
    allowed = {"host", "port", "mode", "sender", "username", "password"}
    if set(payload) - allowed:
        raise ValueError("champ SMTP inattendu")
    required = {"host", "port", "mode", "sender", "username"}
    if not required.issubset(payload):
        raise ValueError("configuration SMTP incomplète")

    previous = _load_private_smtp_payload() or {}
    username = str(payload.get("username") or "").strip()
    supplied_password = str(payload.get("password") or "")
    if supplied_password:
        password = supplied_password
    elif username and username == str(previous.get("username") or "").strip():
        password = str(previous.get("password") or "")
    else:
        password = ""

    cfg = _smtp_config_from_values(
        host=payload.get("host"),
        port=payload.get("port"),
        sender=payload.get("sender"),
        mode=payload.get("mode"),
        username=username,
        password=password,
    )
    data = {
        "schema": SMTP_PRIVATE_SCHEMA,
        "host": cfg.host,
        "port": cfg.port,
        "mode": cfg.mode,
        "sender": cfg.sender,
        "username": cfg.username,
        "password": cfg.password,
    }
    root = _ensure_smtp_private_dir()
    target = _smtp_private_path()
    if target.exists() and target.is_symlink():
        raise RuntimeError("configuration SMTP privée invalide")
    fd, temporary = tempfile.mkstemp(prefix=".smtp-", suffix=".json", dir=root)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        target.chmod(0o600)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return smtp_config_info()


def delete_private_smtp_config() -> dict:
    path = _smtp_private_path()
    if path.is_symlink():
        raise RuntimeError("configuration SMTP privée invalide")
    if path.exists() and not path.is_file():
        raise RuntimeError("configuration SMTP privée invalide")
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return smtp_config_info()


def _transport_mode() -> str:
    mode = (_env("CYBERCHECK_EMAIL_TRANSPORT") or "auto").lower()
    if mode not in {"auto", "smtp", "gmail"}:
        raise ValueError("CYBERCHECK_EMAIL_TRANSPORT must be auto, smtp or gmail")
    return mode


def _configuration_error(transport: str) -> EmailDeliveryError:
    return EmailDeliveryError(
        "Configuration du transport e-mail invalide",
        transport=transport,
        reason="configuration",
        configuration_error=True,
    )


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
        return valid_email(sender) and google_integration.has_usable_scopes([GMAIL_SEND_SCOPE])
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
    state = "ready" if ready else "awaiting_configuration"
    if transport == "smtp-relay":
        cfg = load_config()
        if cfg is not None and _remote_smtp_authentication_missing(cfg):
            state = "awaiting_credentials"
    return {
        "configured": ready,
        "transport": transport or "none",
        "requested": requested,
        "smtpAvailable": smtp_available,
        "gmailAvailable": gmail_available,
        "state": state,
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
    if _remote_smtp_authentication_missing(cfg):
        raise EmailDeliveryError(
            "SMTP distant : authentification requise avant livraison",
            transport="smtp-relay",
            reason="authentication_required_for_remote_relay",
            configuration_error=True,
        )
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


def _gmail_reason(value: object) -> str:
    raw = str(value or "")
    return raw if raw in GMAIL_PROVIDER_REASONS else ""


def _gmail_status_reason(value: object) -> str:
    return GMAIL_STATUS_REASON_MAP.get(str(value or ""), "")


def _safe_retry_after(value: object) -> str:
    raw = str(value or "").strip()
    return raw if raw.isdigit() and len(raw) <= 10 else ""


def _gmail_response_error(response) -> EmailDeliveryError:
    status = _smtp_code(getattr(response, "status_code", 0))
    reason = ""
    try:
        payload = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            errors = error.get("errors")
            if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                reason = _gmail_reason(errors[0].get("reason"))
            if not reason:
                reason = _gmail_status_reason(error.get("status"))
    except Exception:
        pass
    retry_after = _safe_retry_after(getattr(response, "headers", {}).get("Retry-After", ""))
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
    retry_after = _safe_retry_after(getattr(exc, "retry_after", ""))
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
    """Validate SMTP transport without sending DATA or creating a message."""
    try:
        cfg = load_config()
    except ValueError as exc:
        return {"transport": "smtp-relay", "ready": False, "state": "invalid_configuration", "failureClass": "configuration", "status": 0, "reason": str(exc)[:120]}
    if cfg is None:
        return {"transport": "smtp-relay", "ready": False, "state": "awaiting_configuration", "failureClass": "configuration", "status": 0, "reason": "sender_missing"}
    if _remote_smtp_authentication_missing(cfg):
        return {
            "transport": "smtp-relay",
            "ready": False,
            "state": "awaiting_credentials",
            "failureClass": "configuration",
            "status": 0,
            "reason": "authentication_required_for_remote_relay",
            "tls": cfg.mode in {"starttls", "ssl"},
            "authentication": False,
        }
    client = None
    try:
        client = _open_smtp(cfg)
        code, _ = client.mail(cfg.sender)
        code = _smtp_code(code)
        if code >= 400:
            raise smtplib.SMTPResponseException(code, b"MAIL FROM refused")
        reset_code, _ = client.rset()
        reset_code = _smtp_code(reset_code)
        if reset_code >= 400:
            raise smtplib.SMTPResponseException(reset_code, b"RSET refused")
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
        "reason": "sender_envelope_validated",
        "tls": cfg.mode in {"starttls", "ssl"},
        "authentication": bool(cfg.username),
        "senderValidated": True,
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
    try:
        mode = _transport_mode()
    except ValueError as exc:
        raise _configuration_error("email:none") from exc
    if mode in {"auto", "smtp"}:
        try:
            cfg = load_config()
        except ValueError as exc:
            raise _configuration_error("smtp-relay") from exc
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
