from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import base64
import fcntl
import json
import os
import re
import secrets
import tempfile
import threading
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from deployment_center import DeploymentTarget

_SCHEMA = 1
_AAD = b"checkupauto-deployment-vault-v1"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
KEY_FILE_ENV = "CYBERCHECK_DEPLOYMENT_VAULT_KEY_FILE"
SYSTEMD_CREDENTIAL = "deployment-vault.key"
_THREAD_LOCK = threading.RLock()


def _external_key_path() -> Path | None:
    """Key kept outside the vault directory (audit S-15).

    ``CYBERCHECK_DEPLOYMENT_VAULT_KEY_FILE`` names it explicitly; otherwise a
    systemd ``LoadCredential=deployment-vault.key:...`` is used when present.
    """
    explicit = os.environ.get(KEY_FILE_ENV, "").strip()
    if explicit:
        return Path(explicit).expanduser()
    credentials = os.environ.get("CREDENTIALS_DIRECTORY", "").strip()
    if credentials and (Path(credentials) / SYSTEMD_CREDENTIAL).is_file():
        return Path(credentials) / SYSTEMD_CREDENTIAL
    return None


class DeploymentVault:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser()
        external = _external_key_path()
        self.external_key = external is not None
        self.key_path = external if external is not None else self.root / "master.key"
        self.data_path = self.root / "targets.enc"

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)

    @contextmanager
    def _locked(self):
        """Serialise read-modify-write cycles across threads and processes."""
        self._ensure_root()
        with _THREAD_LOCK:
            fd = os.open(self.root / ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def _read_key(self) -> bytes:
        try:
            fd = os.open(self.key_path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as exc:
            raise RuntimeError("clé du coffre de déploiement invalide") from exc
        with os.fdopen(fd, "rb") as handle:
            raw = handle.read(33)
        if len(raw) != 32:
            raise RuntimeError("clé du coffre de déploiement invalide")
        return raw

    def _key(self) -> bytes:
        self._ensure_root()
        if self.external_key:
            return self._read_key()
        if self.key_path.exists() or self.key_path.is_symlink():
            return self._read_key()
        raw = secrets.token_bytes(32)
        fd = os.open(
            self.key_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        try:
            os.write(fd, raw)
        finally:
            os.close(fd)
        return raw

    def _read_records(self) -> dict[str, dict[str, Any]]:
        if not self.data_path.exists():
            return {}
        key = self._key()
        payload = json.loads(self.data_path.read_text(encoding="utf-8"))
        if payload.get("schemaVersion") != _SCHEMA:
            raise RuntimeError("version du coffre de déploiement non supportée")
        try:
            nonce = base64.b64decode(payload["nonce"], validate=True)
            encrypted = base64.b64decode(payload["ciphertext"], validate=True)
            clear = AESGCM(key).decrypt(nonce, encrypted, _AAD)
            records = json.loads(clear.decode("utf-8"))
        except Exception as exc:
            raise RuntimeError("coffre de déploiement illisible") from exc
        if not isinstance(records, dict):
            raise RuntimeError("coffre de déploiement invalide")
        return records

    def _write_records(self, records: dict[str, dict[str, Any]]) -> None:
        key = self._key()
        nonce = secrets.token_bytes(12)
        clear = json.dumps(
            records,
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
            prefix=".targets-",
            dir=self.root,
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

    @staticmethod
    def _name(value: object) -> str:
        name = str(value or "").strip()
        if not _NAME_RE.fullmatch(name):
            raise ValueError("nom de cible invalide")
        return name

    def store(
        self,
        name: str,
        target: DeploymentTarget,
        *,
        identity_file: str = "",
        password: str = "",
    ) -> None:
        key = self._name(name)
        if target.auth_mode == "key":
            if not identity_file:
                raise ValueError("chemin de clé SSH requis")
            secret = {"identityFile": str(Path(identity_file).expanduser())}
        elif target.auth_mode == "password":
            if not password or "\n" in password or "\r" in password:
                raise ValueError("mot de passe SSH invalide")
            secret = {"password": password}
        else:
            raise ValueError("mode d authentification invalide")
        with self._locked():
            records = self._read_records()
            records[key] = {
                "target": target.public_dict(),
                "credential": secret,
            }
            self._write_records(records)

    def load(self, name: str) -> dict[str, Any]:
        key = self._name(name)
        records = self._read_records()
        if key not in records:
            raise KeyError("cible de déploiement inconnue")
        return records[key]

    def delete(self, name: str) -> bool:
        key = self._name(name)
        with self._locked():
            records = self._read_records()
            removed = records.pop(key, None) is not None
            if removed:
                self._write_records(records)
        return removed

    def summaries(self) -> list[dict[str, Any]]:
        records = self._read_records()
        rows = []
        for name, record in sorted(records.items()):
            target = dict(record.get("target") or {})
            rows.append({
                "name": name,
                "provider": target.get("provider"),
                "host": target.get("host"),
                "port": target.get("port"),
                "username": target.get("username"),
                "domain": target.get("domain"),
                "rootPath": target.get("root_path") or target.get("rootPath"),
                "webRootPath": target.get("web_root_path") or target.get("webRootPath"),
                "authMode": target.get("auth_mode") or target.get("authMode"),
                "credentialStored": True,
            })
        return rows
