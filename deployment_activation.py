from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shlex
import subprocess

import deployment_transport as transport
from deployment_center import CapabilityReport, DeploymentTarget, assess

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ACTIVATE_OK_PREFIX = "CHECKUPAUTO_ACTIVATE_OK="
_PREVIOUS_SHA_PREFIX = "CHECKUPAUTO_PREVIOUS_SHA="
_READINESS_STATE_PREFIX = "CHECKUPAUTO_READINESS_STATE="
_ACTIVATION_ALLOWED_PREFIX = "CHECKUPAUTO_ACTIVATION_ALLOWED="
_BLOCKER_COUNT_PREFIX = "CHECKUPAUTO_BLOCKER_COUNT="


@dataclass(frozen=True)
class ActivationResult:
    sha: str
    previous_sha: str
    readiness_state: str
    activation_allowed: bool
    blocker_count: int


def _release_sha(value: object) -> str:
    sha = str(value or "").strip().lower()
    if not _SHA_RE.fullmatch(sha):
        raise ValueError("SHA de release invalide")
    return sha


def remote_activation_program() -> str:
    return r'''from __future__ import annotations
import base64
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
from urllib import request

BEGIN = "# BEGIN CHECKUPAUTO DEPLOYMENT CENTER"
END = "# END CHECKUPAUTO DEPLOYMENT CENTER"
ALLOWED_READINESS_STATES = {"ready", "configuration_required", "blocked_external", "degraded"}

root_rel, web_rel, sha, domain = sys.argv[1:5]
home = Path.home().resolve()
private_root = (home / root_rel).resolve()
web_root = (home / web_rel).resolve()
releases_root = (private_root / "releases").resolve()
release = (releases_root / sha).resolve()
current = private_root / "current"
shared = (private_root / "shared").resolve()
shared_data = (shared / "data").resolve()
shared_private = (shared / "private").resolve()
shared_security = (shared / "security").resolve()
shared_integrity = (shared / "integrity").resolve()
shared_logs = (shared / "logs").resolve()
htaccess = web_root / ".htaccess"


def fail(message: str) -> None:
    raise RuntimeError(message)


def under(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def load_marker(path: Path) -> dict:
    marker = path / ".checkupauto-release.json"
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        fail("release marker invalid")
    if payload.get("sha") != path.name or payload.get("verified") is not True:
        fail("release marker mismatch")
    digest = payload.get("archiveSha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        fail("release marker digest invalid")
    return payload


def managed_text(original: str, block: str) -> str:
    begin_count = original.count(BEGIN)
    end_count = original.count(END)
    if begin_count != end_count or begin_count > 1:
        fail("managed config markers invalid")
    base = original
    if begin_count == 1:
        start = original.index(BEGIN)
        finish = original.index(END, start) + len(END)
        base = original[:start] + original[finish:]
    base = base.rstrip()
    return base + ("\n\n" if base else "") + block.rstrip() + "\n"


def apache_quote(value: Path) -> str:
    text = str(value)
    if any(ord(ch) < 32 for ch in text) or '"' in text:
        fail("unsafe Apache path")
    return '"' + text + '"'


def atomic_write(path: Path, content: bytes, mode: int) -> None:
    temporary = path.with_name(path.name + ".checkupauto-" + str(os.getpid()))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(temporary, flags, mode)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def cron_snapshot() -> tuple[bool, str]:
    proc = subprocess.run(["crontab", "-l"], text=True, capture_output=True, check=False)
    if proc.returncode == 0:
        return True, proc.stdout
    if proc.returncode == 1:
        return False, ""
    fail("cannot read crontab")


def install_cron(original: str) -> None:
    env = {
        "CYBERCHECK_DATA_DIR": shared_data,
        "CYBERCHECK_PRIVATE_DIR": shared_private,
        "CYBERCHECK_SECURITY_DIR": shared_security,
        "CYBERCHECK_INTEGRITY_DIR": shared_integrity,
        "CYBERCHECK_GSC_CREDENTIALS_PATH": shared_private / "gsc-service-account.json",
        "CYBERCHECK_SITE_CONFIG_PATH": shared_data / "site-config.json",
    }
    assignments = " ".join(key + "=" + shlex.quote(str(value)) for key, value in env.items())
    command = " ".join([
        assignments,
        shlex.quote(str(current / ".venv" / "bin" / "python")),
        shlex.quote(str(current / "scripts" / "checkupauto-shared-tick.py")),
        ">>",
        shlex.quote(str(shared_logs / "shared-tick.log")),
        "2>&1",
    ])
    block = "\n".join([BEGIN, "*/5 * * * * " + command, END])
    configured = managed_text(original, block)
    proc = subprocess.run(["crontab", "-"], input=configured, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        fail("cannot install crontab")


def restore_cron(had_cron: bool, content: str) -> None:
    if had_cron:
        proc = subprocess.run(["crontab", "-"], input=content, text=True, capture_output=True, check=False)
    else:
        proc = subprocess.run(["crontab", "-r"], text=True, capture_output=True, check=False)
        if proc.returncode == 1:
            return
    if proc.returncode != 0:
        fail("cannot restore crontab")


def switch_current(target: Path | None) -> None:
    if current.exists() and not current.is_symlink():
        fail("current path is not a symlink")
    if target is None:
        try:
            current.unlink()
        except FileNotFoundError:
            pass
        return
    temporary = private_root / (".current-" + str(os.getpid()))
    try:
        temporary.unlink()
    except FileNotFoundError:
        pass
    os.symlink(str(target), temporary)
    os.replace(temporary, current)


def touch_restart(target: Path) -> None:
    restart_dir = target / "tmp"
    restart_dir.mkdir(mode=0o700, exist_ok=True)
    os.chmod(restart_dir, 0o700)
    restart = restart_dir / "restart.txt"
    restart.touch()
    os.chmod(restart, 0o600)


def probe_http() -> tuple[str, bool, int]:
    password_path = shared_private / "admin-password"
    if password_path.is_symlink():
        fail("admin credential symlink refused")
    password = password_path.read_text(encoding="utf-8").strip()
    if not password:
        fail("admin credential missing")
    authorization = base64.b64encode(("admin:" + password).encode("utf-8")).decode("ascii")
    public_url = "https://" + domain + "/"
    readiness_url = "https://" + domain + "/api/admin/readiness"
    last_kind = "Unavailable"
    for _attempt in range(20):
        try:
            with request.urlopen(public_url, timeout=10) as response:
                if response.status < 200 or response.status >= 400:
                    fail("public health status invalid")
                response.read(4096)
            req = request.Request(readiness_url, headers={"Authorization": "Basic " + authorization})
            with request.urlopen(req, timeout=10) as response:
                if response.status != 200:
                    fail("readiness status invalid")
                payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
            schema = payload.get("schemaVersion")
            if not isinstance(schema, int) or schema < 2:
                fail("readiness schema invalid")
            state = payload.get("state")
            if state not in ALLOWED_READINESS_STATES:
                fail("readiness state invalid")
            gate = payload.get("activationGate")
            if not isinstance(gate, dict) or not isinstance(gate.get("allowed"), bool):
                fail("readiness activation gate invalid")
            blockers = gate.get("blockingComponents")
            if not isinstance(blockers, list) or not all(isinstance(item, str) for item in blockers):
                fail("readiness blockers invalid")
            launch_ready = payload.get("launchReady")
            if not isinstance(launch_ready, bool) or launch_ready is not gate["allowed"]:
                fail("readiness launch gate inconsistent")
            return state, gate["allowed"], len(blockers)
        except Exception as exc:
            last_kind = type(exc).__name__
            time.sleep(3)
    fail("post-activation verification failed: " + last_kind)


if under(private_root, web_root):
    fail("private deployment root is inside web root")
if not web_root.is_dir():
    fail("web root missing")
if not under(releases_root, private_root):
    fail("releases root escapes private root")
if not under(shared, private_root) or under(shared, web_root):
    fail("shared state escapes private root")
for managed_path in (shared_data, shared_private, shared_security, shared_integrity, shared_logs):
    if not under(managed_path, shared) or under(managed_path, web_root):
        fail("shared state path escapes managed root")
    if not managed_path.is_dir():
        fail("shared state directory missing")
if not release.is_dir() or not under(release, releases_root):
    fail("staged release missing")
load_marker(release)
if not (release / ".venv" / "bin" / "python").is_file():
    fail("staged virtualenv missing")
if not (release / "passenger_wsgi.py").is_file():
    fail("Passenger entrypoint missing")
if not (release / "scripts" / "checkupauto-shared-tick.py").is_file():
    fail("shared scheduler missing")
if htaccess.is_symlink() or (htaccess.exists() and not htaccess.is_file()):
    fail("unmanaged .htaccess refused")

previous_release = None
previous_sha = "none"
if current.is_symlink():
    previous_release = current.resolve(strict=True)
    if not under(previous_release, releases_root):
        fail("current release is outside releases root")
    previous_marker = load_marker(previous_release)
    previous_sha = str(previous_marker["sha"])
elif current.exists():
    fail("current path is unmanaged")

had_htaccess = htaccess.exists()
old_htaccess = htaccess.read_bytes() if had_htaccess else b""
old_htaccess_mode = (htaccess.stat().st_mode & 0o777) if had_htaccess else 0o644
had_cron, old_cron = cron_snapshot()

block_lines = [
    BEGIN,
    "PassengerEnabled on",
    "PassengerAppType wsgi",
    "PassengerAppRoot " + apache_quote(current),
    "PassengerStartupFile passenger_wsgi.py",
    "PassengerPython " + apache_quote(current / ".venv" / "bin" / "python"),
    "PassengerAppEnv production",
    "SetEnv CYBERCHECK_DATA_DIR " + apache_quote(shared_data),
    "SetEnv CYBERCHECK_PRIVATE_DIR " + apache_quote(shared_private),
    "SetEnv CYBERCHECK_SECURITY_DIR " + apache_quote(shared_security),
    "SetEnv CYBERCHECK_INTEGRITY_DIR " + apache_quote(shared_integrity),
    "SetEnv CYBERCHECK_GSC_CREDENTIALS_PATH " + apache_quote(shared_private / "gsc-service-account.json"),
    "SetEnv CYBERCHECK_SITE_CONFIG_PATH " + apache_quote(shared_data / "site-config.json"),
    END,
]
original_text = old_htaccess.decode("utf-8") if old_htaccess else ""
new_htaccess = managed_text(original_text, "\n".join(block_lines)).encode("utf-8")

try:
    atomic_write(htaccess, new_htaccess, 0o644)
    install_cron(old_cron)
    switch_current(release)
    touch_restart(release)
    state, allowed, blocker_count = probe_http()
except Exception as activation_error:
    rollback_failed = False
    try:
        switch_current(previous_release)
        if previous_release is not None:
            touch_restart(previous_release)
        if had_htaccess:
            atomic_write(htaccess, old_htaccess, old_htaccess_mode)
        else:
            try:
                htaccess.unlink()
            except FileNotFoundError:
                pass
        restore_cron(had_cron, old_cron)
    except Exception:
        rollback_failed = True
    kind = type(activation_error).__name__
    if rollback_failed:
        print("activation failed; rollback failed: " + kind, file=sys.stderr)
    else:
        print("activation failed; rollback completed: " + kind, file=sys.stderr)
    raise SystemExit(1)

history = shared_logs / "deployment-history.jsonl"
record = {
    "schemaVersion": 1,
    "sha": sha,
    "previousSha": previous_sha,
    "readinessState": state,
    "activationAllowed": allowed,
    "blockerCount": blocker_count,
    "activatedAt": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
}
with history.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    handle.flush()
    os.fsync(handle.fileno())
os.chmod(history, 0o600)

print("CHECKUPAUTO_ACTIVATE_OK=" + sha)
print("CHECKUPAUTO_PREVIOUS_SHA=" + previous_sha)
print("CHECKUPAUTO_READINESS_STATE=" + state)
print("CHECKUPAUTO_ACTIVATION_ALLOWED=" + ("1" if allowed else "0"))
print("CHECKUPAUTO_BLOCKER_COUNT=" + str(blocker_count))
'''


def remote_activation_script(target: DeploymentTarget, release_sha: str) -> str:
    sha = _release_sha(release_sha)
    if not target.web_root_path:
        raise ValueError("l activation mutualisée exige une racine web distincte")
    args = " ".join([
        shlex.quote(target.root_path),
        shlex.quote(target.web_root_path),
        sha,
        shlex.quote(target.domain),
    ])
    return "python3 - " + args + " <<'CHECKUPAUTO_ACTIVATE'\n" + remote_activation_program() + "\nCHECKUPAUTO_ACTIVATE\n"


def _parse_activation_output(output: str, expected_sha: str) -> ActivationResult:
    sha = _release_sha(expected_sha)
    values: dict[str, str] = {}
    prefixes = {
        _ACTIVATE_OK_PREFIX: "sha",
        _PREVIOUS_SHA_PREFIX: "previous",
        _READINESS_STATE_PREFIX: "state",
        _ACTIVATION_ALLOWED_PREFIX: "allowed",
        _BLOCKER_COUNT_PREFIX: "blockers",
    }
    for line in str(output or "").splitlines():
        for prefix, key in prefixes.items():
            if line.startswith(prefix):
                values[key] = line[len(prefix):].strip()
                break
    if values.get("sha") != sha:
        raise RuntimeError("réponse d activation distante invalide")
    previous = values.get("previous", "")
    if previous != "none" and not _SHA_RE.fullmatch(previous):
        raise RuntimeError("réponse d activation distante invalide")
    if values.get("allowed") not in {"0", "1"}:
        raise RuntimeError("réponse d activation distante invalide")
    try:
        blockers = int(values.get("blockers", ""))
    except ValueError as exc:
        raise RuntimeError("réponse d activation distante invalide") from exc
    state = values.get("state", "")
    if blockers < 0 or state not in {"ready", "configuration_required", "blocked_external", "degraded"}:
        raise RuntimeError("réponse d activation distante invalide")
    return ActivationResult(
        sha=sha,
        previous_sha="" if previous == "none" else previous,
        readiness_state=state,
        activation_allowed=values["allowed"] == "1",
        blocker_count=blockers,
    )


def activate_release(
    target: DeploymentTarget,
    capabilities: CapabilityReport,
    known_hosts: str | Path,
    credential: transport.SSHCredential,
    release_sha: str,
    *,
    timeout: int = 180,
) -> ActivationResult:
    readiness = assess(target, capabilities)
    if not readiness["ok"]:
        raise RuntimeError("cible de déploiement non prête")
    script = remote_activation_script(target, release_sha)
    cred = credential.validate(target.auth_mode)
    args = transport.ssh_arguments(target, known_hosts, cred)
    if target.auth_mode == "password":
        result = transport._run_password_ssh(args, script, cred.password, timeout=timeout)
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
        raise RuntimeError("activation distante impossible; état restauré si possible")
    return _parse_activation_output(result.stdout, release_sha)


def rollback_release(
    target: DeploymentTarget,
    capabilities: CapabilityReport,
    known_hosts: str | Path,
    credential: transport.SSHCredential,
    release_sha: str,
    *,
    timeout: int = 180,
) -> ActivationResult:
    return activate_release(
        target,
        capabilities,
        known_hosts,
        credential,
        release_sha,
        timeout=timeout,
    )
