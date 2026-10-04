from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
import base64
import json
import re
import subprocess
from typing import Any

import deployment_transport as transport
import deployment_github_source as github_source
from deployment_center import DeploymentTarget

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_STATE_PREFIX = "CHECKUPAUTO_UPDATE_STATE_B64="
_MAX_RELEASES = 24


@dataclass(frozen=True)
class RemoteRelease:
    sha: str
    mtime: int


@dataclass(frozen=True)
class RemoteDeploymentState:
    installed: bool
    deployed_sha: str
    releases: tuple[RemoteRelease, ...]


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
    return f"""if command -v python3 >/dev/null 2>&1; then
  checkupauto_python=python3
elif [ -x /opt/alt/python312/bin/python3 ]; then
  checkupauto_python=/opt/alt/python312/bin/python3
else
  exit 127
fi
"$checkupauto_python" - <<'CHECKUPAUTO_UPDATE_STATE'
from __future__ import annotations
import base64
import json
from pathlib import Path
import re

SHA_RE = re.compile(r"^[0-9a-f]{{40}}$")
ROOT_REL = {root_json}
PREFIX = {prefix_json}
MAX_RELEASES = {_MAX_RELEASES}

home = Path.home().resolve()
private_root = (home / ROOT_REL).resolve()
releases_root = (private_root / "releases").resolve()
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

payload = {{
    "schemaVersion": 1,
    "installed": bool(deployed),
    "deployedSha": deployed,
    "releases": rows,
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
    return RemoteDeploymentState(
        installed=bool(payload["installed"]),
        deployed_sha=deployed,
        releases=tuple(releases),
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
    if not (root / ".git").exists():
        if not github_source.token_configured():
            return False
        return github_source.is_ancestor(older, newer)
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
