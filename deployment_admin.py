from __future__ import annotations

from pathlib import Path
import datetime as dt
import fcntl
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import uuid

import deployment_center as center
import deployment_executor as executor
import deployment_source as deployment_source
import deployment_transport as transport
import deployment_update as deployment_update
from deployment_vault import DeploymentVault

ROOT = Path(__file__).resolve().parent
_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_FINGERPRINT_RE = re.compile(r"^SHA256:[A-Za-z0-9+/]{20,80}={0,2}$")
_HOST_KEY_TYPES = {
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "ssh-rsa",
}
_JOB_THREAD_LOCK = threading.RLock()


def _private_dir() -> Path:
    return Path(
        os.environ.get("CYBERCHECK_PRIVATE_DIR", "/root/CyberCheckPrivate")
    ).expanduser()


def _local_admin_password() -> str:
    path = _private_dir() / "admin-password"
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("credential admin local indisponible")
    password = path.read_text(encoding="utf-8").strip()
    if not (12 <= len(password) <= 256) or "\n" in password or "\r" in password or "\x00" in password:
        raise RuntimeError("credential admin local invalide")
    return password


def _deployment_state_dir() -> Path:
    raw = str(os.environ.get("CYBERCHECK_DEPLOYMENT_STATE_DIR") or "").strip()
    return Path(raw).expanduser() if raw else _private_dir() / "deployment"


def _vault_root() -> Path:
    raw = str(os.environ.get("CYBERCHECK_DEPLOYMENT_VAULT") or "").strip()
    return Path(raw).expanduser() if raw else _deployment_state_dir() / "vault"


def _known_hosts_path() -> Path:
    raw = str(os.environ.get("CYBERCHECK_DEPLOYMENT_KNOWN_HOSTS") or "").strip()
    return Path(raw).expanduser() if raw else _deployment_state_dir() / "known_hosts"


def _jobs_dir() -> Path:
    raw = str(os.environ.get("CYBERCHECK_DEPLOYMENT_JOBS_DIR") or "").strip()
    return Path(raw).expanduser() if raw else _deployment_state_dir() / "jobs"


def _vault() -> DeploymentVault:
    return DeploymentVault(_vault_root())


def _record_target(record: dict) -> center.DeploymentTarget:
    target = dict(record.get("target") or {})
    return center.validate_target({
        "provider": target.get("provider"),
        "host": target.get("host"),
        "port": target.get("port"),
        "username": target.get("username"),
        "domain": target.get("domain"),
        "rootPath": target.get("root_path") or target.get("rootPath"),
        "webRootPath": target.get("web_root_path") or target.get("webRootPath"),
        "authMode": target.get("auth_mode") or target.get("authMode"),
    })


def _record_credential(
    record: dict,
    target: center.DeploymentTarget,
) -> transport.SSHCredential:
    raw = dict(record.get("credential") or {})
    if target.auth_mode == "key":
        return transport.SSHCredential(
            identity_file=str(raw.get("identityFile") or "")
        )
    return transport.SSHCredential(password=str(raw.get("password") or ""))


def _load_target(name: str):
    record = _vault().load(name)
    target = _record_target(record)
    credential = _record_credential(record, target)
    return target, credential


def _source_state() -> deployment_source.DeploymentSourceState:
    return deployment_source.detect_source(ROOT)


def _current_sha() -> str:
    state = _source_state()
    if not state.sha:
        raise RuntimeError("SHA de release local indisponible")
    return state.sha


def status() -> dict:
    source = _source_state()
    return {
        "ok": True,
        "profiles": center.provider_profiles(),
        "targets": targets(),
        "currentSha": source.sha,
        "source": source.public_dict(),
        "knownHostsConfigured": _known_hosts_path().is_file(),
        "jobs": list_jobs(12),
    }


def targets() -> list[dict]:
    return _vault().summaries()


def _preserved_credential(name: str, auth_mode: str) -> dict:
    try:
        existing = _vault().load(name)
    except KeyError:
        return {}
    target = _record_target(existing)
    if target.auth_mode != auth_mode:
        return {}
    return dict(existing.get("credential") or {})


def save_target(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("configuration de cible invalide")
    name = str(payload.get("name") or "").strip()
    target_payload = payload.get("target")
    target = center.validate_target(target_payload)
    credential = payload.get("credential")
    credential = credential if isinstance(credential, dict) else {}

    vault = _vault()
    if target.auth_mode == "password":
        password = str(credential.get("password") or "")
        if not password:
            password = str(
                _preserved_credential(name, "password").get("password") or ""
            )
        if not password:
            raise ValueError("mot de passe SSH requis")
        vault.store(name, target, password=password)
    else:
        identity = str(credential.get("identityFile") or "").strip()
        if not identity:
            identity = str(
                _preserved_credential(name, "key").get("identityFile") or ""
            )
        if not identity:
            raise ValueError("chemin de clé SSH requis")
        resolved = Path(identity).expanduser().resolve()
        private = _private_dir().resolve()
        if resolved != private and private not in resolved.parents:
            raise ValueError("la clé SSH doit être stockée dans l espace privé")
        vault.store(name, target, identity_file=str(resolved))

    return {
        "ok": True,
        "target": next(
            row for row in vault.summaries() if row["name"] == name
        ),
    }


def delete_target(name: str) -> dict:
    return {"ok": True, "deleted": _vault().delete(name)}


def _scan_lines(target: center.DeploymentTarget) -> list[str]:
    keyscan = shutil.which("ssh-keyscan")
    if not keyscan:
        raise RuntimeError("ssh-keyscan indisponible")
    result = subprocess.run(
        [
            keyscan,
            "-T",
            "6",
            "-p",
            str(target.port),
            target.host,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    lines = []
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or len(line) > 8192:
            continue
        parts = line.split()
        if len(parts) != 3 or parts[1] not in _HOST_KEY_TYPES:
            continue
        lines.append(line)
    if not lines:
        raise RuntimeError("aucune clé hôte SSH exploitable")
    return lines[:12]


def _fingerprint(line: str) -> str:
    keygen = shutil.which("ssh-keygen")
    if not keygen:
        raise RuntimeError("ssh-keygen indisponible")
    result = subprocess.run(
        [keygen, "-lf", "-", "-E", "sha256"],
        input=line + "\n",
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    if result.returncode != 0:
        raise RuntimeError("empreinte SSH impossible")
    fields = result.stdout.strip().split()
    value = next((x for x in fields if x.startswith("SHA256:")), "")
    if not _FINGERPRINT_RE.fullmatch(value):
        raise RuntimeError("empreinte SSH invalide")
    return value


def scan_host_keys(name: str) -> dict:
    target, _credential = _load_target(name)
    rows = []
    seen = set()
    for line in _scan_lines(target):
        fp = _fingerprint(line)
        if fp in seen:
            continue
        seen.add(fp)
        rows.append({
            "keyType": line.split()[1],
            "fingerprint": fp,
        })
    return {
        "ok": True,
        "name": name,
        "host": target.host,
        "port": target.port,
        "keys": rows,
        "trusted": trusted_host_key(name),
    }


def _host_token(target: center.DeploymentTarget) -> str:
    return target.host if target.port == 22 else f"[{target.host}]:{target.port}"


def trusted_host_key(name: str) -> dict | None:
    target, _credential = _load_target(name)
    path = _known_hosts_path()
    if not path.is_file():
        return None
    token = _host_token(target)
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 3 or token not in parts[0].split(","):
            continue
        try:
            return {
                "keyType": parts[1],
                "fingerprint": _fingerprint(line),
            }
        except RuntimeError:
            continue
    return None


def trust_host_key(name: str, fingerprint: str) -> dict:
    fingerprint = str(fingerprint or "").strip()
    if not _FINGERPRINT_RE.fullmatch(fingerprint):
        raise ValueError("empreinte SSH invalide")
    target, _credential = _load_target(name)
    candidate = None
    for line in _scan_lines(target):
        if _fingerprint(line) == fingerprint:
            candidate = line
            break
    if not candidate:
        raise RuntimeError("l empreinte SSH a changé ou n est plus présentée")

    path = _known_hosts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    token = _host_token(target)
    existing = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if parts and token in parts[0].split(","):
                continue
            if line.strip():
                existing.append(line.rstrip())
    existing.append(candidate)

    fd, tmp_name = tempfile.mkstemp(prefix=".known-hosts-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(existing) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        path.chmod(0o600)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
    return {
        "ok": True,
        "trusted": {
            "keyType": candidate.split()[1],
            "fingerprint": fingerprint,
        },
    }


def _local_runtime_flags() -> tuple[bool, bool]:
    adapter = (
        (ROOT / "passenger_wsgi.py").is_file()
        or (ROOT / "deploy" / "passenger_wsgi.py").is_file()
    )
    tick = (ROOT / "scripts" / "checkupauto-shared-tick.py").is_file()
    return adapter, tick


def probe(name: str) -> dict:
    target, credential = _load_target(name)
    adapter, tick = _local_runtime_flags()
    capabilities = transport.probe_target(
        target,
        _known_hosts_path(),
        credential,
        passenger_wsgi_adapter=adapter,
        shared_host_tick=tick,
        timeout=30,
    )
    assessment = center.assess(target, capabilities)
    return {
        "ok": True,
        "target": transport.sanitized_connection(target),
        "capabilities": {
            "pythonVersion": capabilities.python_version,
            "nodeVersion": capabilities.node_version,
            "passenger": capabilities.passenger,
            "systemd": capabilities.systemd,
            "cron": capabilities.cron,
            "symlink": capabilities.symlink,
            "writableRoot": capabilities.writable_root,
            "writableWebRoot": capabilities.writable_web_root,
            "freeDiskMb": capabilities.free_disk_mb,
            "passengerWsgiAdapter": capabilities.passenger_wsgi_adapter,
            "sharedHostTick": capabilities.shared_host_tick,
        },
        "assessment": assessment,
    }


def update_status(name: str) -> dict:
    target, credential = _load_target(name)
    return deployment_update.update_status(
        target,
        _known_hosts_path(),
        credential,
        _current_sha(),
        ROOT,
        timeout=30,
    )


def plan(name: str, sha: str = "") -> dict:
    report = probe(name)
    target, _credential = _load_target(name)
    capabilities = center.CapabilityReport(
        python_version=report["capabilities"]["pythonVersion"],
        node_version=report["capabilities"]["nodeVersion"],
        passenger=report["capabilities"]["passenger"],
        systemd=report["capabilities"]["systemd"],
        cron=report["capabilities"]["cron"],
        symlink=report["capabilities"]["symlink"],
        writable_root=report["capabilities"]["writableRoot"],
        writable_web_root=report["capabilities"]["writableWebRoot"],
        free_disk_mb=report["capabilities"]["freeDiskMb"],
        passenger_wsgi_adapter=report["capabilities"]["passengerWsgiAdapter"],
        shared_host_tick=report["capabilities"]["sharedHostTick"],
    )
    return center.installation_plan(
        target,
        sha or _current_sha(),
        capabilities,
    )


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=".job-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        path.chmod(0o600)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _job_path(job_id: str) -> Path:
    value = str(job_id or "").strip().lower()
    if not _JOB_ID_RE.fullmatch(value):
        raise ValueError("identifiant de job invalide")
    return _jobs_dir() / f"{value}.json"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _write_job(job: dict) -> None:
    _atomic_json(_job_path(job["id"]), job)


def job(job_id: str) -> dict:
    path = _job_path(job_id)
    if not path.is_file():
        raise KeyError("job de déploiement inconnu")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("job de déploiement invalide")
    return payload


def list_jobs(limit: int = 12) -> list[dict]:
    root = _jobs_dir()
    if not root.is_dir():
        return []
    rows = []
    for path in sorted(
        root.glob("*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )[:max(1, min(int(limit), 50))]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _execution_lock():
    root = _jobs_dir()
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    handle = (root / "deployment.lock").open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("un déploiement est déjà en cours")
    return handle


def _result_payload(result) -> dict:
    return {
        "action": result.action,
        "sha": result.sha,
        "previousSha": result.previous_sha,
        "staged": result.staged,
        "archiveSha256": result.archive_sha256,
        "fileCount": result.file_count,
        "readinessState": result.readiness_state,
        "activationAllowed": result.activation_allowed,
        "blockerCount": result.blocker_count,
    }


def _run_job(
    record: dict,
    lock_handle,
    name: str,
    action: str,
    sha: str,
) -> None:
    try:
        record["state"] = "running"
        record["startedAt"] = _now()
        _write_job(record)
        target, credential = _load_target(name)
        admin_password = _local_admin_password()
        if action in {"install", "update"}:
            result = executor.execute_deployment(
                action,
                target,
                _known_hosts_path(),
                credential,
                ROOT,
                sha,
                admin_password=admin_password,
            )
        else:
            result = executor.execute_rollback(
                target,
                _known_hosts_path(),
                credential,
                ROOT,
                sha,
                admin_password=admin_password,
            )
        record["state"] = "succeeded"
        record["result"] = _result_payload(result)
    except Exception as exc:
        record["state"] = "failed"
        record["error"] = type(exc).__name__
        record["detail"] = "Le déploiement a échoué. Vérifiez le diagnostic de la cible puis réessayez."
    finally:
        record["finishedAt"] = _now()
        _write_job(record)
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        finally:
            lock_handle.close()


def start_job(
    name: str,
    action: str,
    *,
    sha: str = "",
) -> dict:
    action = str(action or "").strip().lower()
    if action not in {"install", "update", "rollback"}:
        raise ValueError("action de déploiement invalide")
    _load_target(name)
    source = _source_state()
    if action in {"install", "update"} and not source.build_capable:
        raise RuntimeError("source de build indisponible pour install/update")
    selected_sha = str(sha or "").strip().lower()
    if action in {"install", "update"} and not selected_sha:
        selected_sha = source.sha
    if not re.fullmatch(r"[0-9a-f]{40}", selected_sha):
        raise ValueError("SHA de release invalide")

    lock_handle = _execution_lock()
    record = {
        "id": uuid.uuid4().hex,
        "name": str(name),
        "action": action,
        "sha": selected_sha,
        "state": "queued",
        "createdAt": _now(),
        "startedAt": "",
        "finishedAt": "",
    }
    _write_job(record)
    response = dict(record)
    worker_record = dict(record)
    thread = threading.Thread(
        target=_run_job,
        args=(worker_record, lock_handle, str(name), action, selected_sha),
        daemon=True,
        name=f"CheckupAutoDeploy-{record['id'][:8]}",
    )
    with _JOB_THREAD_LOCK:
        thread.start()
    return response
