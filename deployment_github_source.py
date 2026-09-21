from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from io import BytesIO
import os
from pathlib import Path, PurePosixPath
import re
import tarfile
from urllib.parse import quote, urlparse

import requests


DEFAULT_REPOSITORY = "Memorithm/CHECKUPAUTO.FR"
DEFAULT_BRANCH = "main"
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 192 * 1024 * 1024
MAX_MEMBERS = 20000
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,160}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-\.]{20,500}$")
_ALLOWED_REDIRECT_HOSTS = {"codeload.github.com"}


@dataclass(frozen=True)
class GitHubSourceConfig:
    repository: str
    branch: str
    token_file: Path

    def public_dict(self) -> dict:
        return {
            "provider": "github",
            "repository": self.repository,
            "branch": self.branch,
            "tokenConfigured": token_configured(self.token_file),
        }


@dataclass(frozen=True)
class RemoteBundle:
    sha: str
    archive: bytes
    sha256: str
    file_count: int


def _private_dir() -> Path:
    return Path(
        os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate")
    ).expanduser()


def _repository(value: object) -> str:
    raw = str(value or "").strip()
    if not _REPO_RE.fullmatch(raw):
        raise ValueError("dépôt GitHub invalide")
    return raw


def _branch(value: object) -> str:
    raw = str(value or "").strip()
    if (
        not _BRANCH_RE.fullmatch(raw)
        or raw.startswith("/")
        or raw.endswith("/")
        or ".." in PurePosixPath(raw).parts
    ):
        raise ValueError("branche GitHub invalide")
    return raw


def _token_file(value: str | Path | None = None) -> Path:
    raw = str(value or os.environ.get("CYBERCHECK_UPDATE_GITHUB_TOKEN_FILE") or "").strip()
    return Path(raw).expanduser() if raw else _private_dir() / "github-update-token"


def _config_path(value: str | Path | None = None) -> Path:
    raw = str(
        value
        or os.environ.get("CYBERCHECK_UPDATE_GITHUB_CONFIG_FILE")
        or ""
    ).strip()
    return (
        Path(raw).expanduser()
        if raw
        else _private_dir() / "github-update-source.json"
    )


def _read_saved_config(path: str | Path | None = None) -> dict:
    candidate = _config_path(path)
    if candidate.is_symlink() or not candidate.is_file():
        return {}
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError("configuration GitHub de mise à jour invalide") from exc
    if payload.get("schemaVersion") != 1:
        raise RuntimeError("configuration GitHub de mise à jour invalide")
    return {
        "repository": _repository(payload.get("repository")),
        "branch": _branch(payload.get("branch")),
    }


def config() -> GitHubSourceConfig:
    saved = _read_saved_config()
    return GitHubSourceConfig(
        repository=_repository(
            saved.get("repository")
            or os.environ.get("CYBERCHECK_UPDATE_GITHUB_REPOSITORY")
            or DEFAULT_REPOSITORY
        ),
        branch=_branch(
            saved.get("branch")
            or os.environ.get("CYBERCHECK_UPDATE_GITHUB_BRANCH")
            or DEFAULT_BRANCH
        ),
        token_file=_token_file(),
    )


def save_config(
    repository: str,
    branch: str,
    path: str | Path | None = None,
) -> dict:
    repo = _repository(repository)
    ref = _branch(branch)
    target = _config_path(path)
    root = target.parent
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    if target.is_symlink():
        raise RuntimeError("chemin configuration GitHub invalide")
    payload = {
        "schemaVersion": 1,
        "repository": repo,
        "branch": ref,
    }
    temporary = root / (".github-update-source-" + os.urandom(8).hex())
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        target.chmod(0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return {
        "repository": repo,
        "branch": ref,
    }


def configure_source(
    repository: str,
    branch: str,
    *,
    token: str = "",
) -> dict:
    repo = _repository(repository)
    ref = _branch(branch)
    raw_token = str(token or "").strip()
    if raw_token and not _TOKEN_RE.fullmatch(raw_token):
        raise ValueError("token GitHub invalide")
    saved = save_config(repo, ref)
    if raw_token:
        save_token(raw_token)
    return {
        **saved,
        "tokenConfigured": token_configured(),
    }


def token_configured(path: str | Path | None = None) -> bool:
    candidate = _token_file(path)
    if candidate.is_symlink() or not candidate.is_file():
        return False
    try:
        mode = candidate.stat().st_mode & 0o777
        if mode & 0o077:
            return False
        token = candidate.read_text(encoding="ascii").strip()
    except Exception:
        return False
    return bool(_TOKEN_RE.fullmatch(token))


def _read_token(path: str | Path | None = None) -> str:
    candidate = _token_file(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise RuntimeError("token GitHub de mise à jour absent")
    mode = candidate.stat().st_mode & 0o777
    if mode & 0o077:
        raise RuntimeError("permissions du token GitHub trop ouvertes")
    token = candidate.read_text(encoding="ascii").strip()
    if not _TOKEN_RE.fullmatch(token):
        raise RuntimeError("token GitHub de mise à jour invalide")
    return token


def save_token(token: str, path: str | Path | None = None) -> dict:
    raw = str(token or "").strip()
    if not _TOKEN_RE.fullmatch(raw):
        raise ValueError("token GitHub invalide")
    target = _token_file(path)
    root = target.parent
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    if target.is_symlink():
        raise RuntimeError("chemin token GitHub invalide")
    temporary = root / (".github-update-token-" + os.urandom(8).hex())
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(raw + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        target.chmod(0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return {"configured": True}


def remove_token(path: str | Path | None = None) -> bool:
    target = _token_file(path)
    if target.is_symlink():
        raise RuntimeError("chemin token GitHub invalide")
    try:
        target.unlink()
        return True
    except FileNotFoundError:
        return False


def public_status() -> dict:
    cfg = config()
    return cfg.public_dict()


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "CheckupAuto-DeploymentCenter/1",
    }


def _json_response(response, *, max_bytes: int = 2 * 1024 * 1024) -> dict:
    if response.status_code != 200:
        raise RuntimeError("requête GitHub de mise à jour refusée")
    raw = bytes(response.content)
    if len(raw) > max_bytes:
        raise RuntimeError("réponse GitHub trop volumineuse")
    try:
        payload = response.json()
    except Exception as exc:
        raise RuntimeError("réponse GitHub invalide") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("réponse GitHub invalide")
    return payload


def _session(session=None):
    return session if session is not None else requests.Session()


def latest_sha(*, session=None) -> str:
    cfg = config()
    token = _read_token(cfg.token_file)
    branch = quote(cfg.branch, safe="")
    url = f"https://api.github.com/repos/{cfg.repository}/commits/{branch}"
    response = _session(session).get(
        url,
        headers=_headers(token),
        timeout=(5, 30),
        allow_redirects=False,
    )
    payload = _json_response(response)
    sha = str(payload.get("sha") or "").lower()
    if not _SHA_RE.fullmatch(sha):
        raise RuntimeError("SHA GitHub invalide")
    return sha


def resolve_sha(sha: str, *, session=None) -> str:
    value = str(sha or "").strip().lower()
    if not _SHA_RE.fullmatch(value):
        raise ValueError("SHA GitHub invalide")
    cfg = config()
    token = _read_token(cfg.token_file)
    url = f"https://api.github.com/repos/{cfg.repository}/commits/{value}"
    response = _session(session).get(
        url,
        headers=_headers(token),
        timeout=(5, 30),
        allow_redirects=False,
    )
    payload = _json_response(response)
    resolved = str(payload.get("sha") or "").lower()
    if not hmac_compare(value, resolved):
        raise RuntimeError("commit GitHub inattendu")
    return resolved


def hmac_compare(left: str, right: str) -> bool:
    import hmac
    return hmac.compare_digest(str(left), str(right))


def is_ancestor(older: str, newer: str, *, session=None) -> bool:
    base = str(older or "").strip().lower()
    head = str(newer or "").strip().lower()
    if not (_SHA_RE.fullmatch(base) and _SHA_RE.fullmatch(head)):
        return False
    if hmac_compare(base, head):
        return True
    cfg = config()
    token = _read_token(cfg.token_file)
    url = f"https://api.github.com/repos/{cfg.repository}/compare/{base}...{head}"
    response = _session(session).get(
        url,
        headers=_headers(token),
        timeout=(5, 30),
        allow_redirects=False,
    )
    payload = _json_response(response)
    status = str(payload.get("status") or "")
    return status in {"ahead", "identical"}


def _download_tarball(sha: str, *, session=None) -> bytes:
    value = resolve_sha(sha, session=session)
    cfg = config()
    token = _read_token(cfg.token_file)
    client = _session(session)
    url = f"https://api.github.com/repos/{cfg.repository}/tarball/{value}"
    first = client.get(
        url,
        headers=_headers(token),
        timeout=(5, 30),
        allow_redirects=False,
    )
    if first.status_code not in {301, 302, 303, 307, 308}:
        raise RuntimeError("redirection archive GitHub absente")
    location = str(first.headers.get("Location") or "").strip()
    parsed = urlparse(location)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_REDIRECT_HOSTS
        or parsed.username
        or parsed.password
        or (parsed.port not in {None, 443})
    ):
        raise RuntimeError("redirection archive GitHub non autorisée")

    response = client.get(
        location,
        headers={"User-Agent": "CheckupAuto-DeploymentCenter/1"},
        timeout=(5, 60),
        allow_redirects=False,
        stream=True,
    )
    if response.status_code != 200:
        raise RuntimeError("téléchargement archive GitHub impossible")
    length = response.headers.get("Content-Length")
    if length:
        try:
            announced = int(length)
        except ValueError as exc:
            raise RuntimeError("taille archive GitHub invalide") from exc
        if announced < 0 or announced > MAX_DOWNLOAD_BYTES:
            raise RuntimeError("archive GitHub trop volumineuse")
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=1024 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_DOWNLOAD_BYTES:
            raise RuntimeError("archive GitHub trop volumineuse")
        chunks.append(bytes(chunk))
    raw = b"".join(chunks)
    if not raw:
        raise RuntimeError("archive GitHub vide")
    return raw


def _normalize_tarball(raw: bytes) -> tuple[bytes, int]:
    try:
        source = tarfile.open(fileobj=BytesIO(raw), mode="r:*")
    except tarfile.TarError as exc:
        raise RuntimeError("archive GitHub invalide") from exc

    output = BytesIO()
    file_count = 0
    total_size = 0
    with source, tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as target:
        members = source.getmembers()
        if not members or len(members) > MAX_MEMBERS:
            raise RuntimeError("archive GitHub invalide")
        roots = set()
        for member in members:
            path = PurePosixPath(member.name)
            if not path.parts:
                continue
            roots.add(path.parts[0])
        if len(roots) != 1:
            raise RuntimeError("archive GitHub sans racine unique")
        root = next(iter(roots))

        for member in members:
            path = PurePosixPath(member.name)
            if not path.parts or path.parts[0] != root:
                raise RuntimeError("archive GitHub invalide")
            relative_parts = path.parts[1:]
            if not relative_parts:
                continue
            relative = PurePosixPath(*relative_parts)
            if (
                relative.is_absolute()
                or any(part in {"", ".", ".."} for part in relative.parts)
                or member.issym()
                or member.islnk()
                or member.isdev()
                or member.isfifo()
            ):
                raise RuntimeError("archive GitHub contient un membre interdit")
            if not (member.isfile() or member.isdir()):
                raise RuntimeError("archive GitHub contient un membre interdit")

            info = tarfile.TarInfo(str(relative))
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = 0
            if member.isdir():
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                target.addfile(info)
                continue

            size = int(member.size)
            if size < 0 or size > MAX_UNCOMPRESSED_BYTES:
                raise RuntimeError("fichier archive GitHub trop volumineux")
            total_size += size
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise RuntimeError("archive GitHub décompressée trop volumineuse")
            stream = source.extractfile(member)
            if stream is None:
                raise RuntimeError("fichier archive GitHub illisible")
            info.size = size
            info.mode = 0o755 if (member.mode & 0o111) else 0o644
            target.addfile(info, stream)
            file_count += 1

    normalized = output.getvalue()
    if file_count < 1:
        raise RuntimeError("archive GitHub vide")
    return normalized, file_count


def build_bundle(sha: str, *, session=None) -> RemoteBundle:
    value = str(sha or "").strip().lower()
    if not _SHA_RE.fullmatch(value):
        raise ValueError("SHA GitHub invalide")
    raw = _download_tarball(value, session=session)
    archive, file_count = _normalize_tarball(raw)
    digest = hashlib.sha256(archive).hexdigest()
    return RemoteBundle(
        sha=value,
        archive=archive,
        sha256=digest,
        file_count=file_count,
    )
