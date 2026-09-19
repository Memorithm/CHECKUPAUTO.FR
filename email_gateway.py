from __future__ import annotations

import base64
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
import os
import smtplib
import ssl

import requests

import integration_hub as google_integration

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    sender: str
    mode: str
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
    return SMTPConfig(host=host, port=port, sender=sender, mode=mode)


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
    sender = _gmail_sender()
    return valid_email(sender) and google_integration.has_scopes([GMAIL_SEND_SCOPE])


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
        requested = "invalid"
        config_error = str(exc)
    return {
        "configured": configured(),
        "transport": active_transport() or "none",
        "requested": requested,
        "smtpAvailable": smtp_configured(),
        "gmailAvailable": gmail_configured(),
        "state": "ready" if configured() else "awaiting_configuration",
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


def _send_smtp(cfg: SMTPConfig, to: str, subject: str, text: str, html: str = "") -> dict:
    message = _message(to, cfg.sender, subject, text, html)
    context = ssl.create_default_context()
    if cfg.mode == "ssl":
        client = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=cfg.timeout, context=context)
    else:
        client = smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout)
    try:
        client.ehlo()
        if cfg.mode == "starttls":
            client.starttls(context=context)
            client.ehlo()
        refused = client.send_message(message)
        if refused:
            raise RuntimeError("SMTP a refusé un ou plusieurs destinataires")
    finally:
        try:
            client.quit()
        except Exception:
            client.close()
    return {"ok": True, "channel": "email", "transport": "smtp-relay"}


def _send_gmail(to: str, subject: str, text: str, html: str = "") -> dict:
    sender = _gmail_sender()
    if not valid_email(sender):
        raise RuntimeError("Adresse d’envoi Gmail non configurée")
    token = google_integration.google_access_token([GMAIL_SEND_SCOPE])
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
        raise RuntimeError("Gmail API indisponible") from exc
    if response.status_code >= 400:
        raise RuntimeError(f"Gmail API a refusé l’envoi (HTTP {response.status_code})")
    try:
        message_id = str((response.json() or {}).get("id") or "")
    except Exception:
        message_id = ""
    return {"ok": True, "channel": "email", "transport": "gmail-api", "messageId": message_id}


def send_email(to: str, subject: str, text: str, html: str = "") -> dict:
    mode = _transport_mode()
    if mode in {"auto", "smtp"}:
        cfg = load_config()
        if cfg is not None:
            return _send_smtp(cfg, to, subject, text, html)
        if mode == "smtp":
            raise RuntimeError("SMTP Checkup Auto non configuré")
    if mode in {"auto", "gmail"}:
        if gmail_configured():
            return _send_gmail(to, subject, text, html)
        if mode == "gmail":
            raise RuntimeError("Gmail Checkup Auto non configuré")
    raise RuntimeError("Aucun transport e-mail Checkup Auto n’est configuré")
