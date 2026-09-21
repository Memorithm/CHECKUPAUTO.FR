from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
import base64
import json
import re
import subprocess
from typing import Any

import deployment_transport as transport
from deployment_center import DeploymentTarget

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_STATE_PREFIX = "CHECKUPAUTO_UPDATE_STATE_B64="
_MAX_RELEASES = 24
_MAX_BACKUPS = 24


@dataclass(frozen=True)
class RemoteRelease:
    sha: str
    mtime: int


@dataclass(frozen=True)
class RemoteBackup:
    snapshot: str
    created_at: str
    from_sha: str
    to_sha: str
    database_count: int
    file_count: int


@dataclass(frozen=True)
class RemoteDeploymentState:
    installed: bool
    deployed_sha: str
    releases: tuple[RemoteRelease, ...]
    backups: tuple[RemoteBackup, ...] = ()


def _release_sha(value: object) -> str:
    sha = str(value or "").strip().lower()
    if not _SHA_RE.fullmatch(sha):
        raise ValueError("SHA de release invalide")
    return sha


def _safe_private_root(value: str) -> str:
    raw = str(value or "").strip()
    path = PurePosixPath(raw)
    if (
        not raw
        or path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("racine privée de déploiement invalide")
    return raw


def remote_state_script(target: DeploymentTarget) -> str:
    root = _safe_private_root(target.root_path)
    root_json = json.dumps(root)
    prefix_json = json.dumps(_STATE_PREFIX)
    return f"""python3 - <<'CHECKUPAUTO_UPDATE_STATE'
from __future__ import annotations
import base64
import json
from pathlib import Path
import re

SHA_RE = re.compile(r"^[0-9a-f]{{40}}$")
ROOT_REL = {root_json}
PREFIX = {prefix_json}
MAX_RELEASES = {_MAX_RELEASES}
MAX_BACKUPS = {_MAX_BACKUPS}

home = Path.home().resolve()
private_root = (home / ROOT_REL).resolve()
releases_root = (private_root / "releases").resolve()
backup_root = (private_root / "shared" / "backups").resolve()
current = private_root / "current"


def under(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def marker(path: Path):
    marker_path = path / ".checkupauto-release.json"
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    sha = str(payload.get("sha") or "").lower()
    digest = str(payload.get("archiveSha256") or "").lower()
    if (
        sha != path.name
        or not SHA_RE.fullmatch(sha)
        or payload.get("verified") is not True
        or len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest)
    ):
        return None
    return payload


rows = []
if releases_root.is_dir() and under(releases_root, private_root):
    for child in releases_root.iterdir():
        if child.is_symlink() or not child.is_dir() or not SHA_RE.fullmatch(child.name):
            continue
        try:
            resolved = child.resolve(strict=True)
        except OSError:
            continue
        if not under(resolved, releases_root):
            continue
        if marker(resolved) is None:
            continue
        try:
            mtime = int(resolved.stat().st_mtime)
        except OSError:
            mtime = 0
        rows.append({{"sha": child.name, "mtime": mtime}})

rows.sort(key=lambda item: (item["mtime"], item["sha"]), reverse=True)
rows = rows[:MAX_RELEASES]

deployed = ""
if current.is_symlink():
    try:
        resolved = current.resolve(strict=True)
    except OSError:
        resolved = None
    if resolved is not None and under(resolved, releases_root) and marker(resolved) is not None:
        deployed = resolved.name

backups = []
if backup_root.is_dir() and under(backup_root, private_root):
    for child in backup_root.iterdir():
        if child.is_symlink() or not child.is_dir():
            continue
        try:
            resolved = child.resolve(strict=True)
        except OSError:
            continue
        if not under(resolved, backup_root):
            continue
        manifest = resolved / "manifest.json"
        if manifest.is_symlink() or not manifest.is_file():
            continue
        try:
            item = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            continue
        from_sha = str(item.get("fromSha") or "").lower()
        to_sha = str(item.get("toSha") or "").lower()
        created_at = str(item.get("createdAt") or "")
        databases = item.get("databases")
        files = item.get("files")
        if (
            item.get("schemaVersion") != 1
            or not SHA_RE.fullmatch(from_sha)
            or not SHA_RE.fullmatch(to_sha)
            or not created_at
            or len(created_at) > 80
            or not isinstance(databases, list)
            or not isinstance(files, list)
            or len(databases) > 128
            or len(files) > 128
        ):
            continue
        try:
            mtime = int(resolved.stat().st_mtime)
        except OSError:
            mtime = 0
        backups.append({{
            "snapshot": child.name[:160],
            "createdAt": created_at,
            "fromSha": from_sha,
            "toSha": to_sha,
            "databaseCount": len(databases),
            "fileCount": len(files),
            "mtime": mtime,
        }})

backups.sort(key=lambda item: (item["mtime"], item["snapshot"]), reverse=True)
for item in backups:
    item.pop("mtime", None)
backups = backups[:MAX_BACKUPS]

payload = {{
    "schemaVersion": 1,
    "installed": bool(deployed),
    "deployedSha": deployed,
    "releases": rows,
    "backups": backups,
}}
encoded = base64.b64encode(
    json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
).decode("ascii")
print(PREFIX + encoded)
CHECKUPAUTO_UPDATE_STATE
"""


def _parse_remote_state(output: str) -> RemoteDeploymentState:
    encoded = ""
    for line in str(output or "").splitlines():
        if line.startswith(_STATE_PREFIX):
            encoded = line[len(_STATE_PREFIX):].strip()
            break
    if not encoded:
        raise RuntimeError("état de déploiement distant invalide")
    try:
        raw = base64.b64decode(encoded, validate=True)
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("état de déploiement distant invalide") from exc
    if payload.get("schemaVersion") != 1 or not isinstance(payload.get("installed"), bool):
        raise RuntimeError("état de déploiement distant invalide")

    deployed = str(payload.get("deployedSha") or "").lower()
    if deployed and not _SHA_RE.fullmatch(deployed):
        raise RuntimeError("état de déploiement distant invalide")
    if bool(payload["installed"]) is not bool(deployed):
        raise RuntimeError("état de déploiement distant incohérent")

    raw_releases = payload.get("releases")
    if not isinstance(raw_releases, list) or len(raw_releases) > _MAX_RELEASES:
        raise RuntimeError("inventaire de releases distant invalide")
    releases = []
    seen = set()
    for item in raw_releases:
        if not isinstance(item, dict):
            raise RuntimeError("inventaire de releases distant invalide")
        sha = str(item.get("sha") or "").lower()
        mtime = item.get("mtime")
        if not _SHA_RE.fullmatch(sha) or sha in seen or isinstance(mtime, bool):
            raise RuntimeError("inventaire de releases distant invalide")
        try:
            mtime_int = int(mtime)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("inventaire de releases distant invalide") from exc
        if mtime_int < 0:
            raise RuntimeError("inventaire de releases distant invalide")
        seen.add(sha)
        releases.append(RemoteRelease(sha=sha, mtime=mtime_int))
    if deployed and deployed not in seen:
        raise RuntimeError("release active absente de l inventaire distant")

    raw_backups = payload.get("backups", [])
    if not isinstance(raw_backups, list) or len(raw_backups) > _MAX_BACKUPS:
        raise RuntimeError("inventaire de sauvegardes distant invalide")
    backups = []
    backup_names = set()
    for item in raw_backups:
        if not isinstance(item, dict):
            raise RuntimeError("inventaire de sauvegardes distant invalide")
        snapshot = str(item.get("snapshot") or "")
        created_at = str(item.get("createdAt") or "")
        from_sha = str(item.get("fromSha") or "").lower()
        to_sha = str(item.get("toSha") or "").lower()
        database_count = item.get("databaseCount")
        file_count = item.get("fileCount")
        if (
            not snapshot
            or len(snapshot) > 160
            or snapshot in backup_names
            or "/" in snapshot
            or "\\" in snapshot
            or snapshot in {".", ".."}
            or not created_at
            or len(created_at) > 80
            or not _SHA_RE.fullmatch(from_sha)
            or not _SHA_RE.fullmatch(to_sha)
            or isinstance(database_count, bool)
            or isinstance(file_count, bool)
        ):
            raise RuntimeError("inventaire de sauvegardes distant invalide")
        try:
            database_count = int(database_count)
            file_count = int(file_count)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("inventaire de sauvegardes distant invalide") from exc
        if not (0 <= database_count <= 128 and 0 <= file_count <= 128):
            raise RuntimeError("inventaire de sauvegardes distant invalide")
        backup_names.add(snapshot)
        backups.append(RemoteBackup(
            snapshot=snapshot,
            created_at=created_at,
            from_sha=from_sha,
            to_sha=to_sha,
            database_count=database_count,
            file_count=file_count,
        ))

    return RemoteDeploymentState(
        installed=bool(payload["installed"]),
        deployed_sha=deployed,
        releases=tuple(releases),
        backups=tuple(backups),
    )


def read_remote_state(
    target: DeploymentTarget,
    known_hosts: str | Path,
    credential: transport.SSHCredential,
    *,
    timeout: int = 30,
) -> RemoteDeploymentState:
    cred = credential.validate(target.auth_mode)
    args = transport.ssh_arguments(target, known_hosts, cred)
    script = remote_state_script(target)
    if target.auth_mode == "password":
        result = transport._run_password_ssh(
            args,
            script,
            cred.password,
            timeout=timeout,
        )
    else:
        result = subprocess.run(
            [*args, "sh", "-s"],
            input=script,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError("lecture de la version distante impossible")
    return _parse_remote_state(result.stdout)


def _git_is_ancestor(repo_root: str | Path, older: str, newer: str) -> bool:
    root = Path(repo_root).resolve()
    if not (_SHA_RE.fullmatch(older) and _SHA_RE.fullmatch(newer)):
        return False
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={root}",
            "-C",
            str(root),
            "merge-base",
            "--is-ancestor",
            older,
            newer,
        ],
        capture_output=True,
        check=False,
        timeout=10,
    )
    return result.returncode == 0


def classify_update(
    remote: RemoteDeploymentState,
    desired_sha: str,
    repo_root: str | Path,
) -> dict[str, Any]:
    desired = _release_sha(desired_sha)
    deployed = remote.deployed_sha
    if not remote.installed:
        state = "not_installed"
        update_available = False
    elif deployed == desired:
        state = "up_to_date"
        update_available = False
    elif _git_is_ancestor(repo_root, deployed, desired):
        state = "update_available"
        update_available = True
    elif _git_is_ancestor(repo_root, desired, deployed):
        state = "remote_ahead"
        update_available = False
    else:
        state = "diverged"
        update_available = False

    release_shas = [item.sha for item in remote.releases]
    rollback = [sha for sha in release_shas if sha != deployed][:8]
    return {
        "schemaVersion": 1,
        "state": state,
        "installed": remote.installed,
        "deployedSha": deployed,
        "desiredSha": desired,
        "updateAvailable": update_available,
        "releases": [asdict(item) for item in remote.releases],
        "backups": [asdict(item) for item in remote.backups],
        "backupCount": len(remote.backups),
        "latestBackup": asdict(remote.backups[0]) if remote.backups else None,
        "rollbackCandidates": rollback,
    }


def update_status(
    target: DeploymentTarget,
    known_hosts: str | Path,
    credential: transport.SSHCredential,
    desired_sha: str,
    repo_root: str | Path,
    *,
    timeout: int = 30,
) -> dict[str, Any]:
    remote = read_remote_state(
        target,
        known_hosts,
        credential,
        timeout=timeout,
    )
    return classify_update(remote, desired_sha, repo_root)
