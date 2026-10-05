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
