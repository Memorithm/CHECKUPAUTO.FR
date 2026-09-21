from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import subprocess

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class DeploymentSourceState:
    mode: str
    sha: str
    build_capable: bool
    reason: str

    def public_dict(self) -> dict:
        return asdict(self)


def _git_sha(root: Path) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={root}",
            "-C",
            str(root),
            "rev-parse",
            "HEAD",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    sha = result.stdout.strip().lower()
    if result.returncode == 0 and _SHA_RE.fullmatch(sha):
        return sha
    return ""


def _release_marker_sha(root: Path) -> str:
    marker = root / ".checkupauto-release.json"
    if marker.is_symlink() or not marker.is_file():
        return ""
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        return ""
    sha = str(payload.get("sha") or "").strip().lower()
    digest = str(payload.get("archiveSha256") or "").strip().lower()
    if (
        not _SHA_RE.fullmatch(sha)
        or payload.get("verified") is not True
        or len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest)
    ):
        return ""
    return sha


def detect_source(root: str | Path) -> DeploymentSourceState:
    path = Path(root).resolve()

    if (path / ".git").exists():
        sha = _git_sha(path)
        if sha:
            return DeploymentSourceState(
                mode="git_checkout",
                sha=sha,
                build_capable=True,
                reason="checkout Git local disponible",
            )
        return DeploymentSourceState(
            mode="git_invalid",
            sha="",
            build_capable=False,
            reason="checkout Git présent mais SHA illisible",
        )

    marker_sha = _release_marker_sha(path)
    if marker_sha:
        return DeploymentSourceState(
            mode="packaged_release",
            sha=marker_sha,
            build_capable=False,
            reason="release packagée sans dépôt Git local",
        )

    return DeploymentSourceState(
        mode="unavailable",
        sha="",
        build_capable=False,
        reason="source de déploiement indisponible",
    )
