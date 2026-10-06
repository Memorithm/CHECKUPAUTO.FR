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
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_SCHEMA=1
_AAD_PREFIX=b"checkupauto-customer-erasure-plan-v1:"
_REQUEST_RE=re.compile(r"^[0-9a-f]{32}$")
_HASH_RE=re.compile(r"^[0-9a-f]{64}$")


def _root() -> Path:
    return Path(os.environ.get("CYBERCHECK_PRIVATE_DIR","/root/CyberCheckPrivate"))/"customer-erasure-plans"


def _key_path() -> Path:
    return _root()/"master.key"


def _plan_path(request_id: str) -> Path:
    return _root()/f"{request_id}.enc"


def _fsync_dir(path: Path) -> None:
    try:
        fd=os.open(path,os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _ensure_root() -> Path:
    root=_root()
    root.mkdir(parents=True,exist_ok=True)
    try:
        root.chmod(0o700)
    except PermissionError:
        pass
    return root


def _key() -> bytes:
    root=_ensure_root()
    path=_key_path()
    if path.is_symlink():
        raise RuntimeError("clé du plan client invalide")
    if path.exists():
        raw=path.read_bytes()
        if len(raw)!=32:
            raise RuntimeError("clé du plan client invalide")
        try:
            path.chmod(0o600)
        except PermissionError:
            pass
        return raw

    raw=secrets.token_bytes(32)
    fd,temp_name=tempfile.mkstemp(prefix=".customer-erasure-key-",dir=root)
    temp=Path(temp_name)
    try:
        os.fchmod(fd,0o600)
        os.write(fd,raw)
        os.fsync(fd)
        os.close(fd)
        fd=-1
        try:
            os.link(temp,path)
            _fsync_dir(root)
        except FileExistsError:
            pass
    finally:
        if fd>=0:
            os.close(fd)
        temp.unlink(missing_ok=True)
    stored=path.read_bytes()
    if len(stored)!=32:
        raise RuntimeError("clé du plan client invalide")
    return stored


def _request_id(value: object) -> str:
    raw=str(value or "").strip().lower()
    if not _REQUEST_RE.fullmatch(raw):
        raise ValueError("requestId de plan client invalide")
    return raw


def _email_hash(value: object) -> str:
    raw=str(value or "").strip().lower()
    if not raw or len(raw)>254:
        raise ValueError("sujet du plan client invalide")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _account_id(value: object) -> str:
    raw=str(value or "").strip().lower()
    try:
        parsed=uuid.UUID(raw)
    except (ValueError,AttributeError) as exc:
        raise ValueError("accountId de plan client invalide") from exc
    if str(parsed)!=raw:
        raise ValueError("accountId de plan client invalide")
    return raw


def _aad(request_id: str) -> bytes:
    return _AAD_PREFIX+request_id.encode("ascii")


def _decode(path: Path, request_id: str) -> dict:
    try:
        envelope=json.loads(path.read_text(encoding="utf-8"))
        if envelope.get("schemaVersion")!=_SCHEMA:
            raise ValueError("schema")
        nonce=base64.b64decode(envelope["nonce"],validate=True)
        ciphertext=base64.b64decode(envelope["ciphertext"],validate=True)
        clear=AESGCM(_key()).decrypt(nonce,ciphertext,_aad(request_id))
        payload=json.loads(clear.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("plan d'effacement client chiffré illisible") from exc
    if str(payload.get("requestId") or "")!=request_id:
        raise RuntimeError("plan d'effacement client invalide")
    subject_hash=str(payload.get("subjectHash") or "")
    account_id=_account_id(payload.get("accountId"))
    account_hash=str(payload.get("accountHash") or "")
    if not _HASH_RE.fullmatch(subject_hash) or not _HASH_RE.fullmatch(account_hash):
        raise RuntimeError("plan d'effacement client invalide")
    if not hmac.compare_digest(account_hash,hashlib.sha256(account_id.encode("ascii")).hexdigest()):
        raise RuntimeError("plan d'effacement client invalide")
    return {
        "requestId":request_id,
        "subjectHash":subject_hash,
        "accountId":account_id,
        "accountHash":account_hash,
        "identityCount":max(0,int(payload.get("identityCount") or 0)),
        "reportCount":max(0,int(payload.get("reportCount") or 0)),
        "createdAt":str(payload.get("createdAt") or ""),
    }


def load(request_id: object, subject_email: object) -> dict | None:
    rid=_request_id(request_id)
    path=_plan_path(rid)
    if not path.is_file():
        return None
    payload=_decode(path,rid)
    expected=_email_hash(subject_email)
    if not hmac.compare_digest(payload["subjectHash"],expected):
        raise PermissionError("plan d'effacement client lié à un autre sujet")
    return payload


def stage(
    request_id: object,
    subject_email: object,
    account_id: object,
    *,
    identity_count: int,
    report_count: int,
) -> dict:
    rid=_request_id(request_id)
    subject_hash=_email_hash(subject_email)
    account=_account_id(account_id)
    existing=load(rid,subject_email)
    if existing is not None:
        if not hmac.compare_digest(
            existing["accountHash"],
            hashlib.sha256(account.encode("ascii")).hexdigest(),
        ):
            raise RuntimeError("plan d'effacement client incohérent")
        return existing

    payload={
        "requestId":rid,
        "subjectHash":subject_hash,
        "accountId":account,
        "accountHash":hashlib.sha256(account.encode("ascii")).hexdigest(),
        "identityCount":max(0,int(identity_count)),
        "reportCount":max(0,int(report_count)),
        "createdAt":datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }
    root=_ensure_root()
    clear=json.dumps(payload,sort_keys=True,separators=(",",":")).encode("utf-8")
    nonce=secrets.token_bytes(12)
    envelope={
        "schemaVersion":_SCHEMA,
        "nonce":base64.b64encode(nonce).decode("ascii"),
        "ciphertext":base64.b64encode(AESGCM(_key()).encrypt(nonce,clear,_aad(rid))).decode("ascii"),
    }
    fd,temp_name=tempfile.mkstemp(prefix=".customer-erasure-",dir=root,text=True)
    temp=Path(temp_name)
    target=_plan_path(rid)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as handle:
            json.dump(envelope,handle,sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp,target)
            _fsync_dir(root)
        except FileExistsError:
            raced=load(rid,subject_email)
            if raced is None:
                raise RuntimeError("plan d'effacement client concurrent introuvable")
            return raced
    finally:
        temp.unlink(missing_ok=True)
    stored=load(rid,subject_email)
    if stored is None:
        raise RuntimeError("plan d'effacement client non persisté")
    return stored


def clear(request_id: object, subject_email: object) -> bool:
    rid=_request_id(request_id)
    payload=load(rid,subject_email)
    if payload is None:
        return False
    path=_plan_path(rid)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    _fsync_dir(_root())
    return True
