"""Private editable acquiring-sheet registry, never a payment authorization.

No API credential or card data is accepted. Import is explicit and fills only
missing fields; it is never rerun automatically at application startup.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import secrets
import stat
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PROVIDER = "payline_monext"
AAD = b"checkupauto-payment-contract-v1"
MAX_BYTES = 32768
SPECS = (
    ("platform", "Plateforme", "Accepteur", r"Payline(?: /)? Monext", 40),
    ("brand", "Enseigne", "Accepteur", r"[^\x00-\x1f\x7f<>]{1,100}", 100),
    ("siret", "SIRET", "Accepteur", r"[0-9]{14}", 14),
    ("mcc", "Code MCC", "Accepteur", r"[0-9]{4}", 4),
    ("bankCode", "Code banque", "Acquéreur", r"[0-9]{5}", 5),
    ("acquirerBin", "BIN (identifiant acquéreur)", "Acquéreur", r"[0-9]{1,16}", 16),
    ("acquirerTpe", "TPE (Merchant Id de la fiche bancaire)", "Acquéreur", r"[0-9]{1,20}", 20),
    ("nlsa", "NLSA", "Acquéreur", r"[0-9]{1,6}", 6),
    ("ertTpe", "ERT TPE", "Acquéreur", r"[0-9]{1,4}", 4),
    ("allowedErt", "ERT autorisées", "Acquéreur", r"[0-9]{1,4}(?:/[0-9]{1,4}){0,7}", 39),
    ("currency", "Devise", "Acquéreur", r"EUR", 3),
    ("bin3dsCb", "BIN 3DS CB (3DSv2)", "3-D Secure", r"[0-9]{1,16}", 16),
    ("bin3dsVisa", "BIN 3DS Visa", "3-D Secure", r"[0-9]{1,16}", 16),
    ("bin3dsMc", "BIN 3DS Mastercard", "3-D Secure", r"[0-9]{1,16}", 16),
    ("merchantIdMc", "Merchant ID Mastercard", "3-D Secure", r"[0-9]{1,20}", 20),
)
FIELDS = {row[0]: row for row in SPECS}


class ContractInvalid(ValueError):
    pass


class ContractConflict(RuntimeError):
    pass


class ContractStorageError(RuntimeError):
    pass


def parse_json(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ContractInvalid("duplicate_field")
            result[key] = value
        return result
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise ContractInvalid("body_too_large")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise ContractInvalid("invalid_json") from None
    if not isinstance(data, dict):
        raise ContractInvalid("object_required")
    return data


def validate_fields(fields: object) -> dict[str, str]:
    if not isinstance(fields, dict) or set(fields) - set(FIELDS):
        raise ContractInvalid("unknown_contract_field")
    result = {}
    for name, value in fields.items():
        if not isinstance(value, str):
            raise ContractInvalid("text_fields_required")
        # Identifiers stay strings, including their leading zeroes.
        value = value.strip()
        if value and (len(value) > FIELDS[name][4] or not re.fullmatch(FIELDS[name][3], value)):
            raise ContractInvalid("contract_field_invalid:" + name)
        result[name] = value
    return result


def validate_import(data: object) -> dict[str, str]:
    if (not isinstance(data, dict) or set(data) != {"schemaVersion", "provider", "fields"}
        or type(data["schemaVersion"]) is not int or data["schemaVersion"] != 1
        or data["provider"] != PROVIDER):
        raise ContractInvalid("contract_import_invalid")
    return validate_fields(data["fields"])


class ContractStore:
    def __init__(self, root: Path | str | None = None):
        self.root = (Path(root) if root is not None else
                     Path(os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate")) / "payments")
        if not self.root.is_absolute() or self.root.resolve().is_relative_to(Path(__file__).resolve().parent):
            raise ContractStorageError("private_store_outside_source_required")

    def _check(self, path: Path, *, directory: bool = False):
        info = path.lstat()
        correct_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
        if not correct_type or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ContractStorageError("private_store_permissions_invalid")

    @contextlib.contextmanager
    def _lock(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._check(self.root, directory=True)
        path = self.root / "contract.lock"
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            self._check(path)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _key(self, create: bool) -> bytes:
        path = self.root / "contract.key"
        if not path.exists() and not path.is_symlink():
            if not create:
                raise ContractStorageError("contract_key_missing")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(secrets.token_bytes(32))
                handle.flush()
                os.fsync(handle.fileno())
        self._check(path)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            key = handle.read(33)
        if len(key) != 32:
            raise ContractStorageError("contract_key_invalid")
        return key

    def _read(self):
        path = self.root / "contract.enc"
        if not path.exists() and not path.is_symlink():
            return {"revision": 0, "fields": {name: "" for name in FIELDS}, "audit": []}
        self._check(path)
        if path.stat().st_size > 131072:
            raise ContractStorageError("contract_store_invalid")
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as handle:
                raw = handle.read(131073)
            clear = AESGCM(self._key(False)).decrypt(raw[:12], raw[12:], AAD)
            state = json.loads(clear.decode("utf-8"))
            if (set(state) != {"revision", "fields", "audit"} or type(state["revision"]) is not int
                or state["revision"] < 1 or set(state["fields"]) != set(FIELDS)
                or not isinstance(state["audit"], list) or len(state["audit"]) > 100):
                raise ValueError
            validate_fields(state["fields"])
            return state
        except Exception:
            raise ContractStorageError("contract_store_unreadable") from None

    def _write(self, state):
        nonce = secrets.token_bytes(12)
        raw = nonce + AESGCM(self._key(True)).encrypt(nonce, json.dumps(state, ensure_ascii=False).encode(), AAD)
        fd, name = tempfile.mkstemp(prefix=".contract-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.root / "contract.enc")
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @staticmethod
    def _view(state):
        return {
            "ok": True, "provider": PROVIDER, "revision": state["revision"],
            "fields": dict(state["fields"]), "audit": list(reversed(state["audit"][-20:])),
            "schema": [{"name": k, "label": label, "group": group, "pattern": pattern, "maxLength": length}
                       for k, label, group, pattern, length in SPECS],
            "status": {"contractRecorded": any(state["fields"].values()), "contractVerified": False,
                       "apiCredentialsConfigured": False, "checkoutBound": False, "livePaymentsEnabled": False},
        }

    def snapshot(self):
        with self._lock():
            return self._view(self._read())

    def update(self, data: object):
        if (not isinstance(data, dict) or set(data) != {"revision", "mode", "fields"}
            or type(data["revision"]) is not int or data["revision"] < 0
            or data["mode"] not in {"manual", "import_missing"}):
            raise ContractInvalid("update_invalid")
        fields = validate_fields(data["fields"])
        with self._lock():
            state = self._read()
            if state["revision"] != data["revision"]:
                raise ContractConflict("contract_changed_reload_required")
            changed = []
            for name, value in fields.items():
                if data["mode"] == "import_missing" and state["fields"][name]:
                    continue
                if state["fields"][name] != value:
                    changed.append(name)
                    state["fields"][name] = value
            if changed:
                state["revision"] += 1
                state["audit"] = (state["audit"] + [{"revision": state["revision"], "source": data["mode"],
                    "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    "changedFields": sorted(changed)}])[-100:]
                self._write(state)
            result = self._view(state)
            result["changedFields"] = sorted(changed)
            return result
