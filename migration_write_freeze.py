"""Migration cutover write-freeze state.

The marker lives in the private runtime data directory, not in the release.
Its presence fails closed for mutating HTTP traffic and shared-host background
workers until the operator explicitly removes it after migration/rollback.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

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
