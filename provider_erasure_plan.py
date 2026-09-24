from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
from pathlib import Path
from typing import Iterable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import mercure_rights


_SCHEMA = 1
_AAD_PREFIX = b"checkupauto-provider-erasure-plan-v1:"
_REQUEST_RE = re.compile(r"^[0-9a-f]{32}$")
_APPOINTMENT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_APPOINTMENT_IDS = 1000


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _root() -> Path:
    return Path(
        os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate")
    ) / "provider-erasure-plans"


def _key_path() -> Path:
    return _root() / "master.key"


def _plan_path(request_id: str) -> Path:
    return _root() / f"{request_id}.enc"


def _ensure_root() -> Path:
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except PermissionError:
        pass
    return root


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _request_id(value: object) -> str:
    raw = str(value or "").strip().lower()
    if not _REQUEST_RE.fullmatch(raw):
        raise ValueError("requestId de plan d'effacement invalide")
    return raw


def _subject_hash(value: object) -> str:
    raw = str(value or "").strip()
    mercure_rights.parse_subject_ref(raw)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _appointment_ids(values: Iterable[object]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("inventaire de rendez-vous invalide")
    clean: set[str] = set()
    for value in values:
        appointment_id = str(value or "").strip()
        if not _APPOINTMENT_RE.fullmatch(appointment_id):
            raise ValueError("identifiant de rendez-vous invalide")
        clean.add(appointment_id)
        if len(clean) > MAX_APPOINTMENT_IDS:
            raise ValueError("inventaire de rendez-vous trop volumineux")
    return tuple(sorted(clean))


def _set_hash(values: tuple[str, ...]) -> str:
    canonical = json.dumps(
        list(values),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _key() -> bytes:
    root = _ensure_root()
    path = _key_path()
    if path.exists():
        raw = path.read_bytes()
        if len(raw) != 32:
            raise RuntimeError("clé du plan d'effacement invalide")
        try:
            path.chmod(0o600)
        except PermissionError:
            pass
        return raw

    raw = secrets.token_bytes(32)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raw = path.read_bytes()
        if len(raw) != 32:
            raise RuntimeError("clé du plan d'effacement invalide")
        return raw
    try:
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(root)
    return raw


def _aad(request_id: str) -> bytes:
    return _AAD_PREFIX + request_id.encode("ascii")


def _decode(path: Path, request_id: str) -> dict:
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
        if envelope.get("schemaVersion") != _SCHEMA:
            raise ValueError("schema")
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        clear = AESGCM(_key()).decrypt(nonce, ciphertext, _aad(request_id))
        payload = json.loads(clear.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("plan d'effacement chiffré illisible") from exc

    if str(payload.get("requestId") or "") != request_id:
        raise RuntimeError("plan d'effacement chiffré invalide")
    subject_hash = str(payload.get("subjectRefHash") or "")
    appointment_hash = str(payload.get("appointmentSetHash") or "")
    if not _HASH_RE.fullmatch(subject_hash) or not _HASH_RE.fullmatch(appointment_hash):
        raise RuntimeError("plan d'effacement chiffré invalide")
    try:
        appointment_ids = _appointment_ids(payload.get("appointmentIds") or [])
    except ValueError as exc:
        raise RuntimeError("plan d'effacement chiffré invalide") from exc
    if _set_hash(appointment_ids) != appointment_hash:
        raise RuntimeError("plan d'effacement chiffré invalide")
    created_at = str(payload.get("createdAt") or "")
    if not created_at or len(created_at) > 64:
        raise RuntimeError("plan d'effacement chiffré invalide")
    return {
        "requestId": request_id,
        "subjectRefHash": subject_hash,
        "appointmentIds": appointment_ids,
        "appointmentSetHash": appointment_hash,
        "createdAt": created_at,
    }


def load(request_id: object, subject_ref: object) -> dict | None:
    rid = _request_id(request_id)
    expected_subject_hash = _subject_hash(subject_ref)
    path = _plan_path(rid)
    if not path.is_file():
        return None
    payload = _decode(path, rid)
    if not hmac.compare_digest(payload["subjectRefHash"], expected_subject_hash):
        raise PermissionError("plan d'effacement lié à un autre sujet")
    return payload


def stage(
    request_id: object,
    subject_ref: object,
    appointment_ids: Iterable[object],
) -> dict:
    """Persist the first verified provider appointment set, encrypted at rest."""
    rid = _request_id(request_id)
    subject_hash = _subject_hash(subject_ref)
    clean = _appointment_ids(appointment_ids)
    existing = load(rid, subject_ref)
    if existing is not None:
        return existing

    root = _ensure_root()
    payload = {
        "requestId": rid,
        "subjectRefHash": subject_hash,
        "appointmentIds": list(clean),
        "appointmentSetHash": _set_hash(clean),
        "createdAt": _now_iso(),
    }
    clear = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_key()).encrypt(nonce, clear, _aad(rid))
    envelope = {
        "schemaVersion": _SCHEMA,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }

    fd, temp_name = tempfile.mkstemp(prefix=".provider-erasure-", dir=root, text=True)
    temp = Path(temp_name)
    target = _plan_path(rid)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(envelope, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, target)
            try:
                target.chmod(0o600)
            except PermissionError:
                pass
            _fsync_dir(root)
        except FileExistsError:
            return load(rid, subject_ref) or {}
    finally:
        temp.unlink(missing_ok=True)
    return load(rid, subject_ref) or {}


def clear(
    request_id: object,
    subject_ref: object,
    appointment_set_hash: object,
) -> bool:
    rid = _request_id(request_id)
    expected = str(appointment_set_hash or "").strip().lower()
    if not _HASH_RE.fullmatch(expected):
        raise ValueError("empreinte d'inventaire invalide")
    payload = load(rid, subject_ref)
    if payload is None:
        return False
    if not hmac.compare_digest(payload["appointmentSetHash"], expected):
        raise RuntimeError("empreinte d'inventaire du plan incompatible")
    path = _plan_path(rid)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    _fsync_dir(_root())
    return True
