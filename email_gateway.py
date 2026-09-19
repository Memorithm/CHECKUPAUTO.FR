from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
import os
import smtplib
import ssl


@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    sender: str
    mode: str
    timeout: float = 20.0


def _env(name: str) -> str:
    return str(os.environ.get(name, "") or "").strip()


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
    return SMTPConfig(
        host=host,
        port=port,
        sender=sender,
        mode=mode,
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


def configured() -> bool:
    try:
        return load_config() is not None
    except ValueError:
        return False


def send_email(to: str, subject: str, text: str, html: str = "") -> dict:
    cfg = load_config()
    if cfg is None:
        raise RuntimeError("SMTP Checkup Auto non configuré")
    recipient = str(to or "").strip()
    if not valid_email(recipient):
        raise ValueError("Adresse destinataire invalide")
    subject = str(subject or "").replace("\r", " ").replace("\n", " ").strip()[:180]
    if not subject:
        raise ValueError("Objet email requis")
    message = EmailMessage()
    message["From"] = cfg.sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(str(text or ""))
    if html:
        message.add_alternative(str(html), subtype="html")

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
