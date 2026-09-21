from __future__ import annotations

from email.utils import parseaddr
from pathlib import Path
import base64
import ipaddress
import json
import os
import re
import secrets
import tempfile
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_SCHEMA = 1
_AAD = b"checkupauto-email-settings-v1"
_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$"
)


def state_dir() -> Path:
    raw = str(os.environ.get("CYBERCHECK_EMAIL_STATE_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    private = Path(
        os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate")
    ).expanduser()
    return private / "email"


def _valid_email(value: object) -> bool:
    raw = str(value or "").strip()
    if not raw or len(raw) > 254 or any(ord(ch) < 32 for ch in raw):
        return False
    name, address = parseaddr(raw)
    if name and address != raw:
        return False
    if address != raw or address.count("@") != 1:
        return False
    local, domain = address.rsplit("@", 1)
    return bool(
        local
        and "." in domain
        and not domain.startswith(".")
        and not domain.endswith(".")
    )


def _host(value: object) -> str:
    raw = str(value or "").strip().lower()
    if not raw or any(ch.isspace() for ch in raw):
        raise ValueError("hôte SMTP invalide")
    try:
        ipaddress.ip_address(raw)
        return raw
    except ValueError:
        pass
    if not _HOST_RE.fullmatch(raw):
        raise ValueError("hôte SMTP invalide")
    return raw


def _is_loopback(host: str) -> bool:
    value = str(host or "").strip().lower()
    if value in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _port(value: object, mode: str) -> int:
    if value in {None, ""}:
        return 465 if mode == "ssl" else 587 if mode == "starttls" else 25
    if isinstance(value, bool):
        raise ValueError("port SMTP invalide")
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("port SMTP invalide") from exc
    if not 1 <= port <= 65535:
        raise ValueError("port SMTP invalide")
    return port


class EmailSettingsStore:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root).expanduser() if root is not None else state_dir()
        self.key_path = self.root / "master.key"
        self.data_path = self.root / "transport.enc"

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)

    def _key(self) -> bytes:
        self._ensure_root()
        if self.key_path.exists():
            raw = self.key_path.read_bytes()
            if len(raw) != 32:
                raise RuntimeError("clé du coffre e-mail invalide")
            return raw
        raw = secrets.token_bytes(32)
        fd = os.open(
            self.key_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            os.write(fd, raw)
        finally:
            os.close(fd)
        return raw

    def load(self) -> dict[str, Any]:
        if not self.data_path.is_file():
            return {}
        try:
            envelope = json.loads(self.data_path.read_text(encoding="utf-8"))
            if envelope.get("schemaVersion") != _SCHEMA:
                raise ValueError("schema")
            nonce = base64.b64decode(envelope["nonce"], validate=True)
            encrypted = base64.b64decode(envelope["ciphertext"], validate=True)
            clear = AESGCM(self._key()).decrypt(nonce, encrypted, _AAD)
            payload = json.loads(clear.decode("utf-8"))
        except Exception as exc:
            raise RuntimeError("coffre e-mail illisible") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("coffre e-mail invalide")
        return payload

    def _write(self, payload: dict[str, Any]) -> None:
        key = self._key()
        nonce = secrets.token_bytes(12)
        clear = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        encrypted = AESGCM(key).encrypt(nonce, clear, _AAD)
        envelope = {
            "schemaVersion": _SCHEMA,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(encrypted).decode("ascii"),
        }
        self._ensure_root()
        fd, tmp_name = tempfile.mkstemp(
            prefix=".transport-",
            dir=str(self.root),
            text=True,
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(envelope, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.data_path)
            self.data_path.chmod(0o600)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("configuration e-mail invalide")
        transport = str(payload.get("transportMode") or "auto").strip().lower()
        if transport not in {"auto", "smtp", "gmail"}:
            raise ValueError("transport e-mail invalide")

        smtp = payload.get("smtp")
        smtp = smtp if isinstance(smtp, dict) else {}
        previous = self.load()
        previous_smtp = previous.get("smtp")
        previous_smtp = previous_smtp if isinstance(previous_smtp, dict) else {}

        sender = str(smtp.get("sender") or "").strip()
        host_raw = str(smtp.get("host") or "").strip()
        username = str(smtp.get("username") or "").strip()
        password = str(smtp.get("password") or "")
        mode = str(smtp.get("mode") or "starttls").strip().lower()

        configure_smtp = bool(sender or host_raw or username or password or transport == "smtp")
        smtp_payload: dict[str, Any] = {}
        if configure_smtp:
            if not _valid_email(sender):
                raise ValueError("adresse expéditeur SMTP invalide")
            host = _host(host_raw or "127.0.0.1")
            if mode not in {"starttls", "ssl", "plain"}:
                raise ValueError("mode SMTP invalide")
            port = _port(smtp.get("port"), mode)
            if not password and username:
                if (
                    str(previous_smtp.get("username") or "") == username
                    and str(previous_smtp.get("password") or "")
                ):
                    password = str(previous_smtp["password"])
            if bool(username) != bool(password):
                raise ValueError("identifiant et mot de passe SMTP requis ensemble")
            if username and mode == "plain":
                raise ValueError("authentification SMTP exige TLS")
            if not _is_loopback(host) and not username:
                raise ValueError("authentification requise pour un relais SMTP distant")
            smtp_payload = {
                "host": host,
                "port": port,
                "sender": sender,
                "mode": mode,
                "username": username,
                "password": password,
            }

        record = {
            "transportMode": transport,
            "smtp": smtp_payload,
        }
        self._write(record)
        return self.summary(record)

    def delete(self) -> bool:
        removed = False
        for path in (self.data_path, self.key_path):
            try:
                path.unlink()
                removed = True
            except FileNotFoundError:
                pass
        return removed

    def summary(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        record = payload if payload is not None else self.load()
        smtp = record.get("smtp")
        smtp = smtp if isinstance(smtp, dict) else {}
        return {
            "configured": bool(record),
            "transportMode": str(record.get("transportMode") or "auto"),
            "smtp": {
                "configured": bool(smtp),
                "host": str(smtp.get("host") or ""),
                "port": int(smtp.get("port") or 0),
                "sender": str(smtp.get("sender") or ""),
                "mode": str(smtp.get("mode") or ""),
                "username": str(smtp.get("username") or ""),
                "passwordStored": bool(smtp.get("password")),
            },
        }


def load() -> dict[str, Any]:
    return EmailSettingsStore().load()


def save(payload: dict[str, Any]) -> dict[str, Any]:
    return EmailSettingsStore().save(payload)


def delete() -> bool:
    return EmailSettingsStore().delete()


def summary() -> dict[str, Any]:
    return EmailSettingsStore().summary()
