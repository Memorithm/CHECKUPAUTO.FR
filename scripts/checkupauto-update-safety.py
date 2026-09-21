#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
from urllib.parse import quote

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SQLITE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
SQLITE_MAGIC = b"SQLite format 3\x00"
RELEASE_KEEP_DEFAULT = 5
BACKUP_KEEP_DEFAULT = 12
STALE_INCOMING_SECONDS = 24 * 3600


def _sha(value: object, *, allow_none: bool = False) -> str:
    raw = str(value or "").strip().lower()
    if allow_none and raw == "none":
        return raw
    if not SHA_RE.fullmatch(raw):
        raise ValueError("SHA invalide")
    return raw


def _private_root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("racine privée absente")
    shared = (root / "shared").resolve()
    releases = (root / "releases").resolve()
    if root not in shared.parents or root not in releases.parents:
        raise ValueError("racine privée invalide")
    return root


def _under(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_file(path: Path) -> bool:
    if path.is_symlink() or not path.is_file() or path.suffix.lower() not in SQLITE_SUFFIXES:
        return False
    try:
        with path.open("rb") as handle:
            return handle.read(16) == SQLITE_MAGIC
    except OSError:
        return False


def _backup_database(source: Path, destination: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    uri = "file:" + quote(str(source), safe="/") + "?mode=ro"
    src = sqlite3.connect(uri, uri=True, timeout=10)
    dst = sqlite3.connect(destination, timeout=10)
    try:
        src.backup(dst)
        row = dst.execute("PRAGMA quick_check").fetchone()
        if not row or row[0] != "ok":
            raise RuntimeError("SQLite backup quick_check failed")
    finally:
        dst.close()
        src.close()
    os.chmod(destination, 0o600)
    return {
        "sha256": _sha256(destination),
        "bytes": destination.stat().st_size,
    }


def _snapshot_name(from_sha: str, to_sha: str, now: dt.datetime | None = None) -> str:
    instant = now or dt.datetime.now(dt.timezone.utc)
    stamp = instant.strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{from_sha[:12]}-to-{to_sha[:12]}"


def backup_shared_state(
    private_root: str | Path,
    from_sha: str,
    to_sha: str,
    *,
    now: dt.datetime | None = None,
) -> dict:
    root = _private_root(private_root)
    previous = _sha(from_sha)
    target = _sha(to_sha)
    shared = (root / "shared").resolve()
    backup_root = (shared / "backups").resolve()
    if not _under(backup_root, shared):
        raise RuntimeError("backup root escapes shared state")
    backup_root.mkdir(parents=True, exist_ok=True)
    os.chmod(backup_root, 0o700)

    name = _snapshot_name(previous, target, now=now)
    snapshot = (backup_root / name).resolve()
    if not _under(snapshot, backup_root) or snapshot.exists():
        raise RuntimeError("backup snapshot collision")
    snapshot.mkdir(mode=0o700)

    groups = {
        "data": (shared / "data").resolve(),
        "security": (shared / "security").resolve(),
    }
    databases = []
    files = []
    try:
        for label, source_root in groups.items():
            if not source_root.is_dir() or not _under(source_root, shared):
                continue
            for source in sorted(source_root.rglob("*")):
                if not _sqlite_file(source):
                    continue
                resolved = source.resolve(strict=True)
                if not _under(resolved, source_root):
                    raise RuntimeError("SQLite source escapes shared state")
                relative = resolved.relative_to(source_root)
                destination = snapshot / label / relative
                info = _backup_database(resolved, destination)
                databases.append({
                    "sourceGroup": label,
                    "relativePath": str(relative),
                    **info,
                })

        config = shared / "data" / "site-config.json"
        if config.is_file() and not config.is_symlink():
            resolved = config.resolve(strict=True)
            if not _under(resolved, shared / "data"):
                raise RuntimeError("site config escapes shared state")
            destination = snapshot / "data" / "site-config.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(resolved, destination)
            os.chmod(destination, 0o600)
            files.append({
                "sourceGroup": "data",
                "relativePath": "site-config.json",
                "sha256": _sha256(destination),
                "bytes": destination.stat().st_size,
            })

        manifest = {
            "schemaVersion": 1,
            "createdAt": (now or dt.datetime.now(dt.timezone.utc)).isoformat(),
            "fromSha": previous,
            "toSha": target,
            "databases": databases,
            "files": files,
        }
        manifest_path = snapshot / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.chmod(manifest_path, 0o600)
        return {
            "ok": True,
            "snapshot": name,
            "databaseCount": len(databases),
            "fileCount": len(files),
        }
    except Exception:
        shutil.rmtree(snapshot, ignore_errors=True)
        raise


def _valid_release(path: Path, releases_root: Path) -> tuple[bool, float]:
    if path.is_symlink() or not path.is_dir() or not SHA_RE.fullmatch(path.name):
        return False, 0.0
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return False, 0.0
    if not _under(resolved, releases_root):
        return False, 0.0
    marker = resolved / ".checkupauto-release.json"
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        return False, 0.0
    digest = str(payload.get("archiveSha256") or "")
    if (
        payload.get("sha") != path.name
        or payload.get("verified") is not True
        or len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest)
    ):
        return False, 0.0
    try:
        return True, resolved.stat().st_mtime
    except OSError:
        return False, 0.0


def cleanup_after_activation(
    private_root: str | Path,
    current_sha: str,
    previous_sha: str,
    *,
    release_keep: int = RELEASE_KEEP_DEFAULT,
    backup_keep: int = BACKUP_KEEP_DEFAULT,
    now_ts: float | None = None,
) -> dict:
    root = _private_root(private_root)
    current = _sha(current_sha)
    previous = _sha(previous_sha, allow_none=True)
    if release_keep < 2 or release_keep > 20:
        raise ValueError("rétention releases invalide")
    if backup_keep < 1 or backup_keep > 50:
        raise ValueError("rétention backups invalide")

    releases_root = (root / "releases").resolve()
    shared = (root / "shared").resolve()
    backup_root = (shared / "backups").resolve()
    now_value = float(now_ts if now_ts is not None else dt.datetime.now(dt.timezone.utc).timestamp())

    verified = []
    if releases_root.is_dir():
        for child in releases_root.iterdir():
            valid, mtime = _valid_release(child, releases_root)
            if valid:
                verified.append((child.name, mtime, child.resolve()))

    verified.sort(key=lambda row: (row[1], row[0]), reverse=True)
    keep = {current}
    if previous != "none":
        keep.add(previous)
    for release_sha, _mtime, _path in verified:
        if len(keep) >= release_keep:
            break
        keep.add(release_sha)

    pruned_releases = []
    for release_sha, _mtime, path in verified:
        if release_sha in keep:
            continue
        shutil.rmtree(path)
        pruned_releases.append(release_sha)

    stale_incoming = 0
    if releases_root.is_dir():
        for child in releases_root.iterdir():
            if child.is_symlink() or not child.is_dir() or not child.name.startswith(".incoming-"):
                continue
            try:
                resolved = child.resolve(strict=True)
                age = now_value - resolved.stat().st_mtime
            except OSError:
                continue
            if _under(resolved, releases_root) and age >= STALE_INCOMING_SECONDS:
                shutil.rmtree(resolved)
                stale_incoming += 1

    pruned_backups = 0
    if backup_root.is_dir() and _under(backup_root, shared):
        snapshots = []
        for child in backup_root.iterdir():
            if child.is_symlink() or not child.is_dir():
                continue
            try:
                resolved = child.resolve(strict=True)
                manifest = resolved / "manifest.json"
                payload = json.loads(manifest.read_text(encoding="utf-8"))
                created = str(payload.get("createdAt") or "")
                if payload.get("schemaVersion") != 1 or not created:
                    continue
                mtime = resolved.stat().st_mtime
            except Exception:
                continue
            if _under(resolved, backup_root):
                snapshots.append((mtime, resolved))
        snapshots.sort(key=lambda row: row[0], reverse=True)
        for _mtime, path in snapshots[backup_keep:]:
            shutil.rmtree(path)
            pruned_backups += 1

    return {
        "ok": True,
        "keptReleaseCount": len(keep),
        "prunedReleaseCount": len(pruned_releases),
        "prunedBackupCount": pruned_backups,
        "prunedIncomingCount": stale_incoming,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CheckupAuto update safety helper")
    sub = parser.add_subparsers(dest="command", required=True)

    backup = sub.add_parser("backup")
    backup.add_argument("--private-root", required=True)
    backup.add_argument("--from-sha", required=True)
    backup.add_argument("--to-sha", required=True)

    cleanup = sub.add_parser("cleanup")
    cleanup.add_argument("--private-root", required=True)
    cleanup.add_argument("--current-sha", required=True)
    cleanup.add_argument("--previous-sha", required=True)
    cleanup.add_argument("--release-keep", type=int, default=RELEASE_KEEP_DEFAULT)
    cleanup.add_argument("--backup-keep", type=int, default=BACKUP_KEEP_DEFAULT)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "backup":
        result = backup_shared_state(
            args.private_root,
            args.from_sha,
            args.to_sha,
        )
    else:
        result = cleanup_after_activation(
            args.private_root,
            args.current_sha,
            args.previous_sha,
            release_keep=args.release_keep,
            backup_keep=args.backup_keep,
        )
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
