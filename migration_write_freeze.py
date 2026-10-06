"""Migration cutover write-freeze state.

The marker lives in the private runtime data directory, not in the release.
Its presence fails closed for mutating HTTP traffic and shared-host background
workers until the operator explicitly removes it after migration/rollback.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import tempfile

MARKER_NAME=".migration-write-freeze.json"
SCHEMA_VERSION=1

READ_ONLY_PATHS=frozenset({
    "/",
    "/index.html",
    "/style.css",
    "/app.js",
    "/robots.txt",
    "/sitemap.xml",
    "/llms.txt",
    "/mentions-legales",
    "/confidentialite",
    "/cookies",
    "/cgv",
    "/retractation",
    "/zone-tarifs",
    "/.well-known/security.txt",
    "/.well-known/apple-app-site-association",
    "/apple-app-site-association",
    "/api/site-config",
    "/api/app/status",
    "/api/public/deployment-provenance",
})
READ_ONLY_PREFIXES=("/assets/","/3d/")


def request_allowed(method: object, path: object) -> bool:
    """Allow only explicitly read-only surfaces while a migration freeze is active."""
    verb=str(method or "").upper()
    if verb=="OPTIONS":
        return True
    if verb not in {"GET","HEAD"}:
        return False
    clean=str(path or "/").split("?",1)[0]
    if not clean.startswith("/") or "\x00" in clean:
        return False
    return clean in READ_ONLY_PATHS or any(clean.startswith(prefix) for prefix in READ_ONLY_PREFIXES)


def marker_path() -> Path:
    return Path(os.environ.get("CYBERCHECK_DATA_DIR","/root/CyberCheckData"))/MARKER_NAME


def status() -> dict:
    path=marker_path()
    if path.is_symlink():
        return {
            "active":True,
            "valid":False,
            "state":"invalid_marker",
            "reason":"symlink",
        }
    if not path.exists():
        return {
            "active":False,
            "valid":True,
            "state":"inactive",
            "reason":"",
        }
    if not path.is_file():
        return {
            "active":True,
            "valid":False,
            "state":"invalid_marker",
            "reason":"not_file",
        }
    try:
        raw=path.read_bytes()
        if not raw or len(raw)>4096:
            raise ValueError("size")
        payload=json.loads(raw.decode("utf-8"))
        if not isinstance(payload,dict):
            raise ValueError("shape")
        if payload.get("schemaVersion")!=SCHEMA_VERSION:
            raise ValueError("schema")
        if payload.get("state")!="frozen":
            raise ValueError("state")
        created=str(payload.get("createdAt") or "")
        parsed=dt.datetime.fromisoformat(created)
        if parsed.tzinfo is None:
            raise ValueError("timestamp")
        reason=str(payload.get("reason") or "")
        if len(reason)>160 or any(ord(ch)<32 for ch in reason):
            raise ValueError("reason")
        return {
            "active":True,
            "valid":True,
            "state":"frozen",
            "reason":reason,
            "createdAt":parsed.isoformat(timespec="seconds"),
        }
    except Exception:
        # A malformed marker is not permission to resume writes.
        return {
            "active":True,
            "valid":False,
            "state":"invalid_marker",
            "reason":"malformed",
        }


def active() -> bool:
    return bool(status()["active"])


def _validated_reason(value: object) -> str:
    reason=str(value or "").strip()
    if not reason or len(reason)>160 or any(ord(ch)<32 for ch in reason):
        raise ValueError("freeze reason invalid")
    return reason


def _sync_directory(path: Path) -> None:
    fd=os.open(path,os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def engage(reason: object="hostinger_cutover", *, now: dt.datetime|None=None) -> dict:
    path=marker_path()
    parent=path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise RuntimeError("migration data directory invalid")
    current=status()
    if current.get("active"):
        if current.get("valid"):
            return current
        raise RuntimeError("invalid migration marker must be resolved manually")

    clean_reason=_validated_reason(reason)
    instant=now or dt.datetime.now(dt.timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("freeze timestamp must be timezone-aware")
    payload={
        "schemaVersion":SCHEMA_VERSION,
        "state":"frozen",
        "createdAt":instant.astimezone(dt.timezone.utc).isoformat(timespec="seconds"),
        "reason":clean_reason,
    }
    raw=(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")
    fd,temp_name=tempfile.mkstemp(prefix=".migration-write-freeze.",dir=str(parent))
    temp=Path(temp_name)
    try:
        with os.fdopen(fd,"wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        temp.chmod(0o600)
        if path.exists() or path.is_symlink():
            raise RuntimeError("migration marker appeared during freeze")
        os.replace(temp,path)
        _sync_directory(parent)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    result=status()
    if not result.get("active") or not result.get("valid"):
        raise RuntimeError("migration freeze verification failed")
    return result


def release(confirm: object) -> dict:
    if str(confirm or "")!="UNFREEZE":
        raise PermissionError("explicit UNFREEZE confirmation required")
    path=marker_path()
    parent=path.parent
    current=status()
    if not current.get("active"):
        return current
    if not current.get("valid"):
        raise RuntimeError("invalid migration marker cannot be removed automatically")
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("migration marker changed before unfreeze")
    path.unlink()
    _sync_directory(parent)
    result=status()
    if result.get("active"):
        raise RuntimeError("migration unfreeze verification failed")
    return result


def _parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(description="Contrôle atomique du gel d'écriture de migration CheckupAuto.")
    sub=parser.add_subparsers(dest="command",required=True)
    sub.add_parser("status")
    freeze=sub.add_parser("freeze")
    freeze.add_argument("--reason",default="hostinger_cutover")
    unfreeze=sub.add_parser("unfreeze")
    unfreeze.add_argument("--confirm",required=True)
    return parser


def main() -> int:
    args=_parser().parse_args()
    try:
        if args.command=="status":
            result=status()
        elif args.command=="freeze":
            result=engage(args.reason)
        else:
            result=release(args.confirm)
    except Exception as exc:
        print(json.dumps({"ok":False,"error":type(exc).__name__,"detail":str(exc)},ensure_ascii=False))
        return 2
    print(json.dumps({"ok":True,**result},ensure_ascii=False,sort_keys=True,separators=(",",":")))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
