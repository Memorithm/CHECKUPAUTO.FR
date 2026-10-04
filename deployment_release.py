from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import tarfile

import deployment_transport as transport
import deployment_github_source as github_source
from deployment_center import CapabilityReport, DeploymentTarget, assess

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_STAGE_OK_PREFIX = "CHECKUPAUTO_STAGE_OK="
_STAGE_PATH_PREFIX = "CHECKUPAUTO_STAGE_PATH="
_STAGE_STEP_PREFIX = "CHECKUPAUTO_STAGE_STEP="


@dataclass(frozen=True)
class ReleaseBundle:
    sha: str
    archive: bytes
    sha256: str
    file_count: int


@dataclass(frozen=True)
class StageResult:
    sha: str
    release_path: str
    archive_sha256: str
    file_count: int


def _release_sha(value: object) -> str:
    sha = str(value or "").strip().lower()
    if not _SHA_RE.fullmatch(sha):
        raise ValueError("SHA de release invalide")
    return sha


def _safe_member_name(name: str) -> PurePosixPath:
    raw = str(name or "")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or not path.parts:
        raise ValueError("archive de release invalide")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("archive de release invalide")
    return path


def _validate_archive(raw: bytes) -> int:
    count = 0
    try:
        archive = tarfile.open(fileobj=io.BytesIO(raw), mode="r:")
    except tarfile.TarError as exc:
        raise ValueError("archive Git invalide") from exc
    with archive:
        for member in archive.getmembers():
            _safe_member_name(member.name)
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise ValueError("archive Git contient un type de fichier non autorisé")
            if not (member.isfile() or member.isdir()):
                raise ValueError("archive Git contient un type de fichier non autorisé")
            if member.isfile():
                count += 1
    if count < 1:
        raise ValueError("archive Git vide")
    return count


def build_release_bundle(repo_root: str | Path, release_sha: str) -> ReleaseBundle:
    sha = _release_sha(release_sha)
    root = Path(repo_root).resolve()
    if not (root / ".git").exists():
        if not github_source.token_configured():
            raise ValueError("source de build distante non configurée")
        remote = github_source.build_bundle(sha)
        file_count = _validate_archive(remote.archive)
        digest = hashlib.sha256(remote.archive).hexdigest()
        if (
            remote.sha != sha
            or file_count != remote.file_count
            or not re.fullmatch(r"[0-9a-f]{64}", remote.sha256)
            or not hashlib.sha256(remote.archive).hexdigest() == remote.sha256
        ):
            raise RuntimeError("bundle GitHub incohérent")
        return ReleaseBundle(
            sha=remote.sha,
            archive=remote.archive,
            sha256=digest,
            file_count=file_count,
        )

    resolved = subprocess.run(
        ["git", "-c", f"safe.directory={root}", "-C", str(root), "rev-parse", f"{sha}^{{commit}}"],
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )
    if resolved.returncode != 0 or resolved.stdout.strip() != sha:
        raise ValueError("commit de release introuvable")

    archived = subprocess.run(
        ["git", "-c", f"safe.directory={root}", "-C", str(root), "archive", "--format=tar", sha],
        capture_output=True,
        check=False,
        timeout=60,
    )
    if archived.returncode != 0:
        raise RuntimeError("création de l archive de release impossible")
    raw = bytes(archived.stdout)
    file_count = _validate_archive(raw)
    digest = hashlib.sha256(raw).hexdigest()
    return ReleaseBundle(
        sha=sha,
        archive=raw,
        sha256=digest,
        file_count=file_count,
    )


def remote_stage_script(target: DeploymentTarget, bundle: ReleaseBundle) -> str:
    if not target.web_root_path:
        raise ValueError("le staging mutualisé exige une racine web distincte")
    sha = _release_sha(bundle.sha)
    if not re.fullmatch(r"[0-9a-f]{64}", bundle.sha256):
        raise ValueError("empreinte d archive invalide")
    if bundle.file_count < 1:
        raise ValueError("archive de release vide")
    remote_python = (
        "/opt/alt/python312/bin/python3"
        if target.provider == "planethoster-n0c"
        else "python3"
    )
    replacements = {
        "__PRIVATE_ROOT__": shlex.quote(target.root_path),
        "__REMOTE_PYTHON__": shlex.quote(remote_python),
        "__RELEASE_SHA__": sha,
        "__ARCHIVE_DIGEST__": shlex.quote(bundle.sha256),
        "__ARCHIVE_PAYLOAD__": base64.b64encode(bundle.archive).decode("ascii"),
        "__STAGE_OK_PREFIX__": _STAGE_OK_PREFIX,
        "__STAGE_PATH_PREFIX__": _STAGE_PATH_PREFIX,
        "__STAGE_STEP_PREFIX__": _STAGE_STEP_PREFIX,
    }
    script = """set -eu
umask 077
root=__PRIVATE_ROOT__
sha=__RELEASE_SHA__
expected_digest=__ARCHIVE_DIGEST__
checkupauto_python=__REMOTE_PYTHON__
case "$root" in /*|*../*|../*|*'/..') echo 'invalid private root' >&2; exit 20 ;; esac
private_root="$HOME/$root"
releases="$private_root/releases"
printf '__STAGE_STEP_PREFIX__layout\n'
release="$releases/$sha"
shared="$private_root/shared"
mkdir -p "$releases" "$shared/data" "$shared/private" "$shared/security" "$shared/integrity" "$shared/logs"
chmod 700 "$private_root" "$releases" "$shared" "$shared/data" "$shared/private" "$shared/security" "$shared/integrity" "$shared/logs"
if [ -e "$release" ]; then
  printf '__STAGE_STEP_PREFIX__existing_release\n'
  "$checkupauto_python" - "$release" "$sha" "$expected_digest" <<'CHECKUPAUTO_VERIFY_EXISTING'
from __future__ import annotations
import json
from pathlib import Path
import sys
release = Path(sys.argv[1])
sha = sys.argv[2]
digest = sys.argv[3]
marker = release / ".checkupauto-release.json"
try:
    payload = json.loads(marker.read_text(encoding="utf-8"))
except Exception as exc:
    raise SystemExit("existing release marker is invalid") from exc
if payload.get("sha") != sha or payload.get("archiveSha256") != digest or payload.get("verified") is not True:
    raise SystemExit("existing release does not match requested bundle")
CHECKUPAUTO_VERIFY_EXISTING
  printf '__STAGE_OK_PREFIX__%s\n' "$sha"
  printf '__STAGE_PATH_PREFIX__%s\n' "$release"
  exit 0
fi
incoming="$releases/.incoming-$sha-$$"
trap 'rm -rf "$incoming"' EXIT HUP INT TERM
mkdir "$incoming"
printf '__STAGE_STEP_PREFIX__archive_transfer\n'
cat > "$incoming/archive.b64" <<'CHECKUPAUTO_ARCHIVE'
__ARCHIVE_PAYLOAD__
CHECKUPAUTO_ARCHIVE
mkdir "$incoming/release"
printf '__STAGE_STEP_PREFIX__archive_extract\n'
"$checkupauto_python" - "$incoming/archive.b64" "$incoming/release" "$expected_digest" <<'CHECKUPAUTO_EXTRACT'
from __future__ import annotations
import base64
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile

archive_path = Path(sys.argv[1])
destination = Path(sys.argv[2])
expected_digest = sys.argv[3]
try:
    raw = base64.b64decode(archive_path.read_bytes().strip(), validate=True)
except Exception as exc:
    raise SystemExit("release archive encoding is invalid") from exc
if hashlib.sha256(raw).hexdigest() != expected_digest:
    raise SystemExit("release archive digest mismatch")

with tarfile.open(fileobj=__import__("io").BytesIO(raw), mode="r:") as archive:
    members = archive.getmembers()
    if not members:
        raise SystemExit("release archive is empty")
    for member in members:
        path = PurePosixPath(member.name)
        if not member.name or path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
            raise SystemExit("unsafe archive member")
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise SystemExit("unsupported archive member")
        output = destination.joinpath(*path.parts)
        if member.isdir():
            output.mkdir(parents=True, exist_ok=True)
            os.chmod(output, 0o700)
            continue
        if not member.isfile():
            raise SystemExit("unsupported archive member")
        output.parent.mkdir(parents=True, exist_ok=True)
        source = archive.extractfile(member)
        if source is None:
            raise SystemExit("archive member cannot be read")
        mode = 0o600 | (member.mode & 0o100)
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        with os.fdopen(fd, "wb") as handle:
            shutil.copyfileobj(source, handle, length=1024 * 1024)
        os.chmod(output, mode)
archive_path.unlink()
CHECKUPAUTO_EXTRACT
candidate="$incoming/release"
[ -f "$candidate/requirements.txt" ] || { echo 'requirements.txt missing from release' >&2; exit 21; }
[ -f "$candidate/passenger_wsgi.py" ] || { echo 'Passenger entrypoint missing from release' >&2; exit 22; }
[ -f "$candidate/scripts/checkupauto-shared-tick.py" ] || { echo 'shared scheduler missing from release' >&2; exit 23; }
[ -f "$candidate/scripts/checkupauto-update-safety.py" ] || { echo 'update safety helper missing from release' >&2; exit 24; }
printf '__STAGE_STEP_PREFIX__venv\n'
"$checkupauto_python" -m venv "$candidate/.venv"
printf '__STAGE_STEP_PREFIX__dependencies\n'
"$candidate/.venv/bin/python" -m pip install --disable-pip-version-check --no-input -r "$candidate/requirements.txt"
printf '__STAGE_STEP_PREFIX__compile\n'
"$candidate/.venv/bin/python" -m compileall -q "$candidate"
printf '__STAGE_STEP_PREFIX__marker\n'
"$checkupauto_python" - "$candidate/.checkupauto-release.json" "$sha" "$expected_digest" <<'CHECKUPAUTO_MARK'
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
path = Path(sys.argv[1])
payload = {
    "schemaVersion": 1,
    "sha": sys.argv[2],
    "archiveSha256": sys.argv[3],
    "verified": True,
}
path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
os.chmod(path, 0o600)
CHECKUPAUTO_MARK
printf '__STAGE_STEP_PREFIX__commit\n'
mv "$candidate" "$release"
printf '__STAGE_OK_PREFIX__%s\n' "$sha"
printf '__STAGE_PATH_PREFIX__%s\n' "$release"
"""
    for token, value in replacements.items():
        script = script.replace(token, value)
    return script


def _parse_stage_output(output: str, bundle: ReleaseBundle) -> StageResult:
    values: dict[str, str] = {}
    for line in str(output or "").splitlines():
        if line.startswith(_STAGE_OK_PREFIX):
            values["sha"] = line[len(_STAGE_OK_PREFIX):].strip()
        elif line.startswith(_STAGE_PATH_PREFIX):
            values["path"] = line[len(_STAGE_PATH_PREFIX):].strip()
    if values.get("sha") != bundle.sha or not values.get("path"):
        raise RuntimeError("réponse de staging distante invalide")
    return StageResult(
        sha=bundle.sha,
        release_path=values["path"],
        archive_sha256=bundle.sha256,
        file_count=bundle.file_count,
    )


def _last_stage_step(output: str) -> str:
    allowed = {
        "layout", "existing_release", "archive_transfer", "archive_extract",
        "venv", "dependencies", "compile", "marker", "commit",
    }
    last = ""
    for line in str(output or "").splitlines():
        if line.startswith(_STAGE_STEP_PREFIX):
            candidate = line[len(_STAGE_STEP_PREFIX):].strip()
            if candidate in allowed:
                last = candidate
    return last or "unknown"


def stage_release(
    target: DeploymentTarget,
    capabilities: CapabilityReport,
    known_hosts: str | Path,
    credential: transport.SSHCredential,
    repo_root: str | Path,
    release_sha: str,
    *,
    timeout: int = 900,
) -> StageResult:
    readiness = assess(target, capabilities)
    if not readiness["ok"]:
        raise RuntimeError("cible de déploiement non prête")
    bundle = build_release_bundle(repo_root, release_sha)
    script = remote_stage_script(target, bundle)
    cred = credential.validate(target.auth_mode)
    args = transport.ssh_arguments(target, known_hosts, cred)
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
        step = _last_stage_step(result.stdout)
        raise RuntimeError("staging distant de la release impossible:" + step)
    return _parse_stage_output(result.stdout, bundle)
